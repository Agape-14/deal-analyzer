"""Read-only operational probes; never return paths, records or exceptions."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import os
from pathlib import Path
import shutil

from alembic.script import ScriptDirectory
from sqlalchemy import func, inspect, or_, select, text

READINESS_TIMEOUT_SECONDS = 5
QUEUE_WARNING_SECONDS = 600
MIN_FREE_BYTES = 16 * 1024 * 1024
WARNING_FREE_BYTES = 64 * 1024 * 1024


def _production():
    return bool(os.getenv("RAILWAY_PROJECT_ID") or os.getenv("RAILWAY_ENVIRONMENT")
                or os.getenv("RAILWAY_ENVIRONMENT_NAME")) or os.getenv("PRODUCTION", "").lower() in {"1", "true", "yes"}


def _schema_state(connection):
    from app.database import Base
    import app.models  # noqa: F401 -- registers the actual application schema

    inspector = inspect(connection)
    tables = set(inspector.get_table_names())
    missing_tables, missing_columns = [], 0
    for table in Base.metadata.sorted_tables:
        if table.name not in tables:
            missing_tables.append(table.name)
            continue
        columns = {column["name"] for column in inspector.get_columns(table.name)}
        missing_columns += len(set(table.columns.keys()) - columns)
    schema = {"status": "error" if missing_tables or missing_columns else "ok",
              "code": "schema_incomplete" if missing_tables or missing_columns else "schema_available",
              "missing_table_count": len(missing_tables), "missing_column_count": missing_columns,
              "column_presence_only": True}
    scripts = ScriptDirectory(str(Path(__file__).resolve().parents[2] / "alembic"))
    expected = set(scripts.get_heads())
    if "alembic_version" not in tables:
        migrations = {"status": "error" if _production() else "warning", "code": "migration_tracking_missing",
                      "at_expected_head": False, "expected_head_count": len(expected)}
    else:
        current = set(connection.execute(text("SELECT version_num FROM alembic_version")).scalars())
        matches = bool(expected) and current == expected
        migrations = {"status": "ok" if matches else "error",
                      "code": "migrations_current" if matches else "migration_head_mismatch",
                      "at_expected_head": matches, "expected_head_count": len(expected),
                      "current_head_count": len(current)}
    return schema, migrations


def _storage_state(db_engine):
    # Match ingestion's configured location without importing its router,
    # whose module initialization creates directories.
    base = Path(__file__).resolve().parents[2]
    uploads = Path(os.getenv("UPLOADS_DIR", str(Path(os.getenv("DB_DIR", str(base))) / "uploads")))
    locations = [("uploads", uploads)]
    if db_engine.dialect.name == "sqlite":
        database = db_engine.url.database
        if database and database != ":memory:":
            locations.append(("database", Path(database).resolve().parent))
    checks = []
    for kind, path in locations:
        try:
            accessible = path.is_dir() and os.access(path, os.R_OK | os.W_OK | os.X_OK)
            space = shutil.disk_usage(path) if path.is_dir() else None
            enough = space is not None and space.free >= MIN_FREE_BYTES
            warning = space is not None and space.free < WARNING_FREE_BYTES
            checks.append({"kind": kind, "status": "error" if not accessible or not enough else "warning" if warning else "ok",
                           "code": "storage_unavailable" if not accessible else "storage_space_critical" if not enough
                           else "storage_space_low" if warning else "storage_available",
                           "accessible": accessible, "free_bytes": space.free if space else None,
                           "total_bytes": space.total if space else None})
        except OSError:
            checks.append({"kind": kind, "status": "error", "code": "storage_unavailable", "accessible": False})
    status = "error" if any(check["status"] == "error" for check in checks) else "warning" if any(check["status"] == "warning" for check in checks) else "ok"
    return {"status": status, "checks": checks,
            "permission_check_only": True, "note": "Filesystem permissions and free space; no write probe was performed."}


async def _job_state(connection, now):
    from app.models import Deal, ReviewJob

    active = ReviewJob.__table__.join(Deal.__table__, ReviewJob.deal_id == Deal.id)
    where = Deal.deleted_at.is_(None)
    counts = dict((await connection.execute(
        select(ReviewJob.status, func.count()).select_from(active).where(where).group_by(ReviewJob.status)
    )).all())
    expired = (await connection.execute(select(func.count()).select_from(active).where(
        where, ReviewJob.status == "running", or_(ReviewJob.lease_until.is_(None), ReviewJob.lease_until < now)
    ))).scalar_one()
    oldest = (await connection.execute(select(func.min(ReviewJob.next_attempt_at)).select_from(active).where(
        where, ReviewJob.status == "queued", ReviewJob.next_attempt_at <= now
    ))).scalar_one()
    if oldest is not None and oldest.tzinfo:
        oldest = oldest.astimezone(timezone.utc).replace(tzinfo=None)
    age = max(0, int((now - oldest).total_seconds())) if oldest is not None else None
    workers = os.getenv("REVIEW_WORKERS_ENABLED", "1").lower() not in {"0", "false", "no"}
    warnings = []
    if expired:
        warnings.append("expired_review_leases")
    if age is not None and age >= QUEUE_WARNING_SECONDS:
        warnings.append("review_queue_overdue" if workers else "review_workers_disabled_with_pending_jobs")
    return {"status": "warning" if warnings else "ok", "codes": warnings, "workers_enabled": workers,
            "queued_count": counts.get("queued", 0), "running_count": counts.get("running", 0),
            "failed_count": counts.get("failed", 0), "paused_count": counts.get("paused", 0),
            "expired_lease_count": expired, "oldest_due_queue_age_seconds": age,
            "queue_warning_seconds": QUEUE_WARNING_SECONDS}


async def _collect(db_engine, now):
    checks = {}
    try:
        if (db_engine.dialect.name == "sqlite" and db_engine.url.database
                and db_engine.url.database != ":memory:" and not Path(db_engine.url.database).is_file()):
            # A missing SQLite database must not be created by a read probe.
            raise FileNotFoundError
        async with db_engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
            checks["database"] = {"status": "ok", "code": "database_reachable", "engine": db_engine.dialect.name}
            try:
                checks["schema"], checks["migrations"] = await connection.run_sync(_schema_state)
            except Exception:
                checks["schema"] = {"status": "error", "code": "schema_check_failed"}
                checks["migrations"] = {"status": "error", "code": "migration_check_failed"}
            if checks["schema"]["status"] != "error":
                try:
                    checks["review_jobs"] = await _job_state(connection, now)
                except Exception:
                    checks["review_jobs"] = {"status": "warning", "codes": ["review_job_check_failed"]}
            else:
                checks["review_jobs"] = {"status": "warning", "codes": ["review_job_schema_unavailable"]}
    except Exception:
        checks["database"] = {"status": "error", "code": "database_unavailable"}
    checks["storage"] = await asyncio.to_thread(_storage_state, db_engine)
    deploy_ready = not any(check["status"] == "error" for check in checks.values())
    warnings = any(check["status"] == "warning" for check in checks.values())
    return {"status": "not_ready" if not deploy_ready else "degraded" if warnings else "ready",
            "deploy_ready": deploy_ready, "checked_at": now.replace(tzinfo=timezone.utc).isoformat(), "checks": checks}


async def readiness_report(*, db_engine=None, now=None):
    """Bound each probe; failed checks expose stable codes, never exception text."""
    if db_engine is None:
        from app.database import engine
        db_engine = engine
    now = now or datetime.now(timezone.utc)
    if now.tzinfo:
        now = now.astimezone(timezone.utc).replace(tzinfo=None)
    try:
        return await asyncio.wait_for(_collect(db_engine, now), timeout=READINESS_TIMEOUT_SECONDS)
    except Exception:
        return {"status": "not_ready", "deploy_ready": False,
                "checked_at": now.replace(tzinfo=timezone.utc).isoformat(),
                "checks": {"probe": {"status": "error", "code": "readiness_check_failed"}}}

"""Readiness checks use synthetic local state, with no providers or live data."""
from datetime import datetime, timedelta
import json
from types import SimpleNamespace

import pytest
from sqlalchemy import select, text

pytestmark = pytest.mark.asyncio


async def test_existing_liveness_and_minimal_readiness_are_compatible(client):
    response = await client.get("/api/healthz")
    assert response.status_code == 200 and "models" in response.json()
    ready = await client.get("/api/healthz/ready")
    assert ready.status_code == 200 and ready.json() == {"status": "ready"}
    assert ready.headers["cache-control"] == "no-store"
    detail = await client.get("/api/admin/readiness")
    checks = detail.json()["checks"]
    assert checks["database"]["status"] == checks["schema"]["status"] == "ok"
    assert checks["migrations"]["code"] == "migration_tracking_missing"
    assert checks["storage"]["permission_check_only"]


async def test_production_requires_expected_migration_head_and_actual_schema(client, monkeypatch):
    from app.database import engine
    from alembic.script import ScriptDirectory
    from pathlib import Path

    monkeypatch.setenv("PRODUCTION", "1")
    assert (await client.get("/api/healthz/ready")).status_code == 503
    expected = ScriptDirectory(str(Path(__file__).resolve().parents[1] / "alembic")).get_current_head()
    async with engine.begin() as connection:
        await connection.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"))
        await connection.execute(text("INSERT INTO alembic_version VALUES (:head)"), {"head": expected})
    assert (await client.get("/api/healthz/ready")).status_code == 200
    async with engine.begin() as connection:
        await connection.execute(text("UPDATE alembic_version SET version_num='older_synthetic_revision'"))
    report = (await client.get("/api/admin/readiness")).json()
    assert not report["deploy_ready"] and report["checks"]["migrations"]["code"] == "migration_head_mismatch"
    async with engine.begin() as connection:
        await connection.execute(text("UPDATE alembic_version SET version_num=:head"), {"head": expected})
        await connection.execute(text("DROP TABLE review_jobs"))
    assert (await client.get("/api/admin/readiness")).json()["checks"]["schema"]["missing_table_count"] == 1
    assert (await client.get("/api/healthz/ready")).status_code == 503
    assert (await client.get("/api/healthz")).status_code == 200


async def test_probe_does_not_create_a_missing_database_or_expose_its_path(client, tmp_path):
    from sqlalchemy.ext.asyncio import create_async_engine
    from app.services.operational_readiness import readiness_report

    filename = tmp_path / "sensitive-never-created.sqlite"
    candidate = create_async_engine(f"sqlite+aiosqlite:///{filename}")
    try:
        report = await readiness_report(db_engine=candidate)
    finally:
        await candidate.dispose()
    assert not filename.exists()
    assert report["checks"]["database"] == {"status": "error", "code": "database_unavailable"}
    assert str(tmp_path) not in json.dumps(report) and filename.name not in json.dumps(report)


async def test_expired_leases_and_overdue_jobs_warn_without_mutating_or_blocking_deployment(client):
    from app.database import async_session
    from app.models import Deal, ReviewJob

    now = datetime.utcnow()
    async with async_session() as db:
        for index in range(4):
            deal = Deal(project_name=f"Synthetic job {index}", deleted_at=now if index == 3 else None)
            db.add(deal)
            await db.flush()
            db.add(ReviewJob(deal_id=deal.id, status="queued" if index in {0, 3} else "running",
                             mode="read", next_attempt_at=now - timedelta(hours=1), updated_at=now,
                             lease_until=now + timedelta(minutes=2) if index == 2 else now - timedelta(minutes=1),
                             error="Never expose private worker context."))
        await db.commit()
        before = (await db.execute(select(Deal.id, Deal.revision))).all()
    response = await client.get("/api/admin/readiness")
    assert response.status_code == 200
    report = response.json()
    jobs = report["checks"]["review_jobs"]
    assert jobs["status"] == "warning" and jobs["queued_count"] == 1 and jobs["running_count"] == 2
    assert jobs["expired_lease_count"] == 1 and jobs["oldest_due_queue_age_seconds"] >= 3600
    assert "Never expose" not in json.dumps(report) and "Synthetic job" not in json.dumps(report)
    assert (await client.get("/api/healthz/ready")).status_code == 200
    async with async_session() as db:
        assert (await db.execute(select(Deal.id, Deal.revision))).all() == before


async def test_critical_storage_space_blocks_readiness_without_a_write_probe(client, monkeypatch):
    from app.services import operational_readiness

    monkeypatch.setattr(operational_readiness.shutil, "disk_usage", lambda path: SimpleNamespace(total=100, free=0))
    assert (await client.get("/api/healthz/ready")).status_code == 503
    report = (await client.get("/api/admin/readiness")).json()
    assert report["checks"]["storage"]["status"] == "error"
    assert all(row["code"] == "storage_space_critical" for row in report["checks"]["storage"]["checks"])


async def test_detailed_readiness_requires_admin_but_minimal_probe_is_public(client, monkeypatch):
    from app.auth import hash_password

    monkeypatch.setenv("AUTH_DISABLED", "0")
    monkeypatch.setenv("AUTH_USERNAME", "synthetic-admin")
    monkeypatch.setenv("AUTH_PASSWORD_HASH", hash_password("synthetic-admin-password"))
    monkeypatch.setenv("VIEWER_USERNAME", "synthetic-viewer")
    monkeypatch.setenv("VIEWER_PASSWORD_HASH", hash_password("synthetic-viewer-password"))
    assert (await client.get("/api/healthz/ready")).status_code == 200
    assert (await client.get("/api/admin/readiness")).status_code == 401
    assert (await client.post("/api/auth/login", json={"username": "synthetic-viewer", "password": "synthetic-viewer-password"})).status_code == 200
    assert (await client.get("/api/admin/readiness")).status_code == 403
    await client.post("/api/auth/logout")
    assert (await client.post("/api/auth/login", json={"username": "synthetic-admin", "password": "synthetic-admin-password"})).status_code == 200
    assert (await client.get("/api/admin/readiness")).status_code == 200

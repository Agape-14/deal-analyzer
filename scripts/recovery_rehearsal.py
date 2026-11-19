"""Rehearse a bounded, local restore without modifying the source or using APIs.

Call from an authorized on-service task with ``await asyncio.to_thread(...)``.
The private copy and detailed replay remain in a TemporaryDirectory and are
removed before returning. This is not proof of provider backup retention.
"""
from __future__ import annotations

from contextlib import closing
from pathlib import Path
import shutil
import sqlite3
import tempfile
import time

from scripts.staging_snapshot import create_snapshot, sha256

DEFAULT_MAX_COPY_BYTES = 256 * 1024 * 1024
DEFAULT_MAX_DOCUMENTS = 1000
DEFAULT_MAX_DEALS = 500
RESERVE_BYTES = 64 * 1024 * 1024


class RecoveryRehearsalBlocked(ValueError):
    """Stable, non-sensitive failure code; no source path or exception text."""


def _readonly(database):
    connection = sqlite3.connect(Path(database).as_uri() + "?mode=ro", uri=True, timeout=5)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    return connection


def _inventory(database, uploads, max_documents, max_deals):
    if not database.is_file() or not uploads.is_dir():
        raise RecoveryRehearsalBlocked("source_unavailable")
    with closing(_readonly(database)) as connection:
        rows = connection.execute("SELECT file_path FROM deal_documents").fetchmany(max_documents + 1)
        active_deals = connection.execute("SELECT count(*) FROM deals WHERE deleted_at IS NULL").fetchone()[0]
    if len(rows) > max_documents or active_deals > max_deals:
        raise RecoveryRehearsalBlocked("rehearsal_record_limit")
    database_bytes = database.stat().st_size
    wal = Path(str(database) + "-wal")
    if wal.is_file():
        database_bytes += wal.stat().st_size
    estimated_bytes = database_bytes * 2
    for row in rows:
        path = Path(row["file_path"]).resolve()
        if not path.is_relative_to(uploads) or not path.is_file():
            raise RecoveryRehearsalBlocked("source_document_unavailable")
        estimated_bytes += path.stat().st_size
    return {"document_count": len(rows), "active_deal_count": active_deals, "estimated_copy_bytes": estimated_bytes}


def _copy_integrity(snapshot):
    """Verify recovery structure and retained business rows, privately."""
    original, working = snapshot / "original.db", snapshot / "deal_analyzer.db"
    with closing(_readonly(original)) as before, closing(_readonly(working)) as after:
        if before.execute("PRAGMA integrity_check").fetchone()[0] != "ok" or after.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise RecoveryRehearsalBlocked("restored_database_integrity_failed")
        if after.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise RecoveryRehearsalBlocked("restored_foreign_keys_failed")
        tables = sorted(row[0] for row in before.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"))
        for table in tables:
            # Identifiers come only from SQLite metadata and are quoted safely.
            quoted = '"' + table.replace('"', '""') + '"'
            if before.execute(f"SELECT count(*) FROM {quoted}").fetchone()[0] != after.execute(f"SELECT count(*) FROM {quoted}").fetchone()[0]:
                raise RecoveryRehearsalBlocked("restored_row_counts_changed")
            if table in {"deals", "analysis_snapshots", "investments", "distributions", "developers", "deal_chats"}:
                if any(left != right for left, right in zip(before.execute(f"SELECT * FROM {quoted} ORDER BY rowid"),
                                                           after.execute(f"SELECT * FROM {quoted} ORDER BY rowid"))):
                    raise RecoveryRehearsalBlocked("restored_business_records_changed")
    return len(tables)


def rehearse_recovery(database, uploads, *, max_copy_bytes=DEFAULT_MAX_COPY_BYTES,
                      max_documents=DEFAULT_MAX_DOCUMENTS, max_deals=DEFAULT_MAX_DEALS):
    """Return only booleans/counts; callers must not print caught exceptions.

    No credentials are read and no providers, migrations, workers, or HTTP
    endpoints are invoked. SQLite's backup API reads the live source, while
    only the temporary working database has document paths/jobs adjusted.
    """
    started = time.monotonic()
    database, uploads = Path(database).resolve(), Path(uploads).resolve()
    try:
        if max_copy_bytes <= 0 or max_documents <= 0 or max_deals <= 0:
            raise RecoveryRehearsalBlocked("invalid_rehearsal_limits")
        if not database.is_file() or not uploads.is_dir():
            raise RecoveryRehearsalBlocked("source_unavailable")
        with tempfile.TemporaryDirectory(prefix="kenyon-recovery-") as temporary:
            root = Path(temporary)
            # Freeze the database first, so concurrent uploads cannot expand
            # the document inventory after the byte/document limit checks.
            frozen = root / "source.db"
            with closing(_readonly(database)) as source:
                page_size = source.execute("PRAGMA page_size").fetchone()[0]

                def progress(status, remaining, total):
                    if total * page_size * 3 > max_copy_bytes:
                        raise RecoveryRehearsalBlocked("rehearsal_size_limit")
                    if time.monotonic() - started > 90:
                        raise RecoveryRehearsalBlocked("rehearsal_time_limit")

                source_bytes = source.execute("PRAGMA page_count").fetchone()[0] * page_size
                if source_bytes * 3 > max_copy_bytes:
                    raise RecoveryRehearsalBlocked("rehearsal_size_limit")
                if shutil.disk_usage(root).free < source_bytes * 3 + RESERVE_BYTES:
                    raise RecoveryRehearsalBlocked("rehearsal_space_unavailable")
                with closing(sqlite3.connect(frozen)) as target:
                    source.backup(target, pages=256, progress=progress)
            inventory = _inventory(frozen, uploads, max_documents, max_deals)
            inventory["estimated_copy_bytes"] += frozen.stat().st_size
            if inventory["estimated_copy_bytes"] > max_copy_bytes:
                raise RecoveryRehearsalBlocked("rehearsal_size_limit")
            if shutil.disk_usage(root).free < inventory["estimated_copy_bytes"] + RESERVE_BYTES:
                raise RecoveryRehearsalBlocked("rehearsal_space_unavailable")
            snapshot = root / "snapshot"
            manifest = create_snapshot(frozen, uploads, snapshot)
            if len(manifest["documents"]) > max_documents:
                raise RecoveryRehearsalBlocked("rehearsal_record_limit")
            actual_bytes = sum(path.stat().st_size for path in root.rglob("*") if path.is_file())
            if actual_bytes > max_copy_bytes:
                raise RecoveryRehearsalBlocked("rehearsal_size_limit")
            table_count = _copy_integrity(snapshot)
            working_hash = sha256(snapshot / "deal_analyzer.db")
            from scripts.replay_staging import replay
            report = replay(snapshot)
            if report["deal_count"] > max_deals:
                raise RecoveryRehearsalBlocked("rehearsal_record_limit")
            if report["provider_calls"] or report["database_writes"] or sha256(snapshot / "deal_analyzer.db") != working_hash:
                raise RecoveryRehearsalBlocked("replay_not_read_only")
            result = {"passed": True, "source_opened_read_only": True, "source_database_writes": 0,
                      "provider_calls": 0, "database_integrity_verified": True, "foreign_keys_verified": True,
                      "original_document_hashes_verified": True, "business_rows_preserved": True,
                      "replay_read_only": True, "table_count": table_count, "deal_count": report["deal_count"],
                      "document_count": len(manifest["documents"]), "copy_bytes": actual_bytes,
                      "provider_backup_schedule_verified": False, "source_content_accuracy_verified": False}
        result["temporary_copy_removed"] = not root.exists()
        result["elapsed_seconds"] = round(time.monotonic() - started, 3)
        return result
    except RecoveryRehearsalBlocked:
        raise
    except Exception:
        # SQLite/validation failures can include private data and paths.
        raise RecoveryRehearsalBlocked("recovery_rehearsal_failed") from None

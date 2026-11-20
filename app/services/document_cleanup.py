"""Clean up live originals after the corresponding database changes commit."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import delete, select, update

from app.database import async_session
from app.models import DealDocument, DocumentFileCleanup

log = logging.getLogger("kenyon.document_cleanup")


def _relative_upload(path: str, root: Path) -> str | None:
    if not path:
        return None
    try:
        relative = Path(path).resolve().relative_to(root).as_posix()
    except (OSError, RuntimeError, ValueError):
        return None
    return relative if relative != "." and len(relative) <= 1024 else None


async def queue_document_files(db, upload_dir, documents) -> list[str]:
    root = Path(upload_dir).resolve()
    paths = sorted({relative for doc in documents if (relative := _relative_upload(doc.file_path, root))})
    now = datetime.now(timezone.utc)
    for path in paths:
        if await db.get(DocumentFileCleanup, path) is None:
            db.add(DocumentFileCleanup(relative_path=path, next_attempt_at=now))
    return paths


async def drain_document_cleanup(upload_dir, paths: list[str] | None = None) -> bool:
    """Attempt due cleanup or specific committed intents. Return whether all selected paths cleared."""
    if paths == []:
        return True
    root = Path(upload_dir).resolve()
    now = datetime.now(timezone.utc)
    async with async_session() as db:
        query = select(DocumentFileCleanup.relative_path)
        if paths is None:
            query = query.where(DocumentFileCleanup.next_attempt_at <= now).order_by(
                DocumentFileCleanup.next_attempt_at, DocumentFileCleanup.relative_path,
            ).limit(64)
        else:
            query = query.where(DocumentFileCleanup.relative_path.in_(paths))
        queued = (await db.scalars(query)).all()
        if not queued:
            return True
        active = {
            _relative_upload(path, root)
            for path in (await db.scalars(select(DealDocument.file_path))).all()
        }
        pending = False
        for path in queued:
            try:
                if path not in active:
                    target = root / path
                    if _relative_upload(str(target), root) != path:
                        raise OSError("Upload path changed after deletion was recorded")
                    target.unlink(missing_ok=True)
                await db.execute(delete(DocumentFileCleanup).where(DocumentFileCleanup.relative_path == path))
            except OSError:
                pending = True
                # Give later entries a turn even if this path requires intervention.
                await db.execute(update(DocumentFileCleanup).where(DocumentFileCleanup.relative_path == path).values(
                    next_attempt_at=now + timedelta(minutes=5),
                ))
                log.warning("An original document file is awaiting cleanup")
        await db.commit()
        return not pending


async def document_cleanup_worker(upload_dir):
    while True:
        try:
            await drain_document_cleanup(upload_dir)
        except Exception:
            log.exception("Document cleanup could not finish and will retry")
        await asyncio.sleep(60)

"""
Notifications service — thin helper so route handlers can emit events
without boilerplate. Writes directly to the `notifications` table.

Design: single-user app, so no targeting. Keep the unread set trimmed
by marking anything older than 60 days read on read, and the list
endpoint caps at 50 for UI purposes.
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Notification


async def emit(
    db: AsyncSession,
    kind: str,
    title: str,
    *,
    body: str = "",
    href: str = "",
    payload: dict[str, Any] | None = None,
) -> int:
    """Insert a notification row. Returns the new id.

    Callers decide whether to `await db.commit()` themselves (usually
    they're in the middle of a larger transaction and a double-commit
    would be wrong). This function only flushes so the id is available.
    """
    n = Notification(
        kind=kind,
        title=title[:255],
        body=body or "",
        href=href or "",
        payload=payload or {},
    )
    db.add(n)
    await db.flush()
    return n.id


async def list_recent(db: AsyncSession, limit: int = 50, unread_only: bool = False) -> list[Notification]:
    q = select(Notification).order_by(Notification.created_at.desc()).limit(limit)
    if unread_only:
        q = q.where(Notification.read_at.is_(None))
    r = await db.execute(q)
    return list(r.scalars().all())


async def unread_count(db: AsyncSession) -> int:
    r = await db.execute(
        select(Notification).where(Notification.read_at.is_(None))
    )
    return len(list(r.scalars().all()))


async def mark_all_read(db: AsyncSession) -> int:
    now = datetime.now(timezone.utc)
    r = await db.execute(
        update(Notification)
        .where(Notification.read_at.is_(None))
        .values(read_at=now)
    )
    return r.rowcount or 0


async def mark_read(db: AsyncSession, notif_id: int) -> bool:
    r = await db.execute(
        select(Notification).where(Notification.id == notif_id)
    )
    n = r.scalar_one_or_none()
    if not n:
        return False
    if n.read_at is None:
        n.read_at = datetime.now(timezone.utc)
    return True


async def prune(db: AsyncSession, *, older_than_days: int = 60) -> int:
    """Hard-delete notifications older than N days so the table stays lean."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=older_than_days)
    r = await db.execute(
        select(Notification).where(Notification.created_at < cutoff)
    )
    rows = list(r.scalars().all())
    for n in rows:
        await db.delete(n)
    return len(rows)


def serialize(n: Notification) -> dict:
    return {
        "id": n.id,
        "kind": n.kind,
        "title": n.title,
        "body": n.body,
        "href": n.href,
        "payload": n.payload or {},
        "read_at": n.read_at.isoformat() if n.read_at else None,
        "created_at": n.created_at.isoformat() if n.created_at else None,
    }

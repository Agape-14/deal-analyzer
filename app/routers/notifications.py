"""Notifications endpoints. All behind auth (via global middleware)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.services import notifications as notif_svc

router = APIRouter()


@router.get("")
async def list_notifications(
    unread: bool = False,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
):
    rows = await notif_svc.list_recent(db, limit=max(1, min(200, limit)), unread_only=unread)
    return {
        "items": [notif_svc.serialize(n) for n in rows],
        "unread": await notif_svc.unread_count(db),
    }


@router.get("/unread-count")
async def unread_count(response: Response, db: AsyncSession = Depends(get_db)):
    """Lightweight poll endpoint for the header bell indicator.

    Cached for 15s so the 45-second client poll plus any simultaneous
    dashboard loads don't all hit the DB. Fresh enough that a just-
    triggered notification shows up within one polling window.
    """
    response.headers["Cache-Control"] = "private, max-age=15"
    return {"unread": await notif_svc.unread_count(db)}


@router.post("/mark-read")
async def mark_all(db: AsyncSession = Depends(get_db)):
    n = await notif_svc.mark_all_read(db)
    await db.commit()
    return {"marked": n}


@router.post("/{notif_id}/mark-read")
async def mark_one(notif_id: int, db: AsyncSession = Depends(get_db)):
    ok = await notif_svc.mark_read(db, notif_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Notification not found")
    await db.commit()
    return {"ok": True}

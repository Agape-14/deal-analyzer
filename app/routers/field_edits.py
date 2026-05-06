from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.database import get_db
from app.models import Deal
from app.services.data_integrity import mark_manual_edit, set_lock
from app.services.deal_scorer import score_deal
from app.services.deal_validator import validate_deal_metrics
from app.services.math_checker import run_math_checks

router = APIRouter()


class FieldEditIn(BaseModel):
    path: str
    value: Optional[float | str | int | bool] = None
    lock: Optional[bool] = True


class FieldLockIn(BaseModel):
    path: str
    locked: bool


class ConflictResolveIn(BaseModel):
    path: str
    value: Optional[float | str | int | bool] = None


def _refresh_integrity(deal: Deal, metrics: dict) -> None:
    """Rebuild every derived integrity artifact after a user correction."""
    math_checks = run_math_checks(metrics)
    metrics["validation_flags"] = validate_deal_metrics(metrics, deal.property_type)
    deal.metrics = metrics
    deal.scores = score_deal(metrics, math_checks=math_checks)
    flag_modified(deal, "metrics")
    flag_modified(deal, "scores")


@router.post("/{deal_id}/fields/edit")
async def edit_field(deal_id: int, data: FieldEditIn, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Deal).where(Deal.id == deal_id))
    deal = result.scalar_one_or_none()
    if not deal:
        raise HTTPException(status_code=404, detail="Deal not found")

    metrics = dict(deal.metrics or {})
    metrics = mark_manual_edit(metrics, data.path, data.value, lock=bool(data.lock))
    _refresh_integrity(deal, metrics)
    await db.commit()
    return {"message": "Field updated", "path": data.path, "locked": bool(data.lock)}


@router.post("/{deal_id}/fields/lock")
async def lock_field(deal_id: int, data: FieldLockIn, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Deal).where(Deal.id == deal_id))
    deal = result.scalar_one_or_none()
    if not deal:
        raise HTTPException(status_code=404, detail="Deal not found")

    metrics = dict(deal.metrics or {})
    metrics = set_lock(metrics, data.path, bool(data.locked))
    deal.metrics = metrics
    flag_modified(deal, "metrics")
    await db.commit()
    return {"message": "Lock updated", "path": data.path, "locked": bool(data.locked)}


@router.post("/{deal_id}/fields/resolve-conflict")
async def resolve_conflict(deal_id: int, data: ConflictResolveIn, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Deal).where(Deal.id == deal_id))
    deal = result.scalar_one_or_none()
    if not deal:
        raise HTTPException(status_code=404, detail="Deal not found")

    metrics = dict(deal.metrics or {})
    metrics = mark_manual_edit(metrics, data.path, data.value, lock=True)

    prov = dict(metrics.get("_provenance") or {})
    if data.path in prov and isinstance(prov[data.path], dict):
        prov[data.path].pop("conflict", None)
        metrics["_provenance"] = prov

    _refresh_integrity(deal, metrics)
    await db.commit()
    return {"message": "Conflict resolved", "path": data.path}

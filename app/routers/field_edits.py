import copy
import math
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.database import get_db
from app.models import Deal
from app.services.data_integrity import mark_manual_edit, set_lock
from app.services.deal_validator import validate_deal_metrics
from app.services.math_checker import run_math_checks

router = APIRouter()


class FieldEditIn(BaseModel):
    path: str
    value: Optional[float | str | int | bool] = None
    lock: Optional[bool] = True


class BatchFieldEditIn(BaseModel):
    edits: list[FieldEditIn] = Field(..., min_length=1, max_length=25)


class FieldLockIn(BaseModel):
    path: str
    locked: bool


class ConflictResolveIn(BaseModel):
    path: str
    value: Optional[float | str | int | bool] = None


def _json_safe(value):
    """Return a JSON-column-safe copy of nested metrics data."""
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_safe(v) for v in value]
    if isinstance(value, tuple):
        return [_json_safe(v) for v in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _refresh_integrity(deal: Deal, metrics: dict) -> None:
    """Refresh validation after a user correction without blocking the save.

    Scoring is intentionally handled by /score after the save succeeds. That
    keeps a scoring/API failure from making a valid field correction look like
    it failed to save.
    """
    try:
        run_math_checks(metrics)
    except Exception as e:
        metrics["_manual_edit_warning"] = f"Math checks did not rerun: {type(e).__name__}: {e}"
    metrics["validation_flags"] = validate_deal_metrics(metrics, deal.property_type)
    deal.metrics = _json_safe(jsonable_encoder(metrics))
    flag_modified(deal, "metrics")


@router.post("/{deal_id}/fields/edit")
async def edit_field(deal_id: int, data: FieldEditIn, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Deal).where(Deal.id == deal_id))
    deal = result.scalar_one_or_none()
    if not deal:
        raise HTTPException(status_code=404, detail="Deal not found")

    try:
        metrics = copy.deepcopy(deal.metrics or {})
        metrics = mark_manual_edit(metrics, data.path, data.value, lock=bool(data.lock))
        _refresh_integrity(deal, metrics)
        await db.commit()
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Could not save {data.path}: {type(e).__name__}: {e}",
        )
    return {"message": "Field updated", "path": data.path, "locked": bool(data.lock)}


@router.post("/{deal_id}/fields/batch-edit")
async def batch_edit_fields(deal_id: int, data: BatchFieldEditIn, db: AsyncSession = Depends(get_db)):
    """Apply several user corrections, then rerun math/validation/scoring once."""
    result = await db.execute(select(Deal).where(Deal.id == deal_id))
    deal = result.scalar_one_or_none()
    if not deal:
        raise HTTPException(status_code=404, detail="Deal not found")

    try:
        metrics = copy.deepcopy(deal.metrics or {})
        changed: list[str] = []
        seen: set[str] = set()
        for edit in data.edits:
            if edit.path in seen:
                raise HTTPException(status_code=400, detail=f"Duplicate edit path: {edit.path}")
            seen.add(edit.path)
            metrics = mark_manual_edit(metrics, edit.path, edit.value, lock=bool(edit.lock))
            changed.append(edit.path)

        _refresh_integrity(deal, metrics)
        await db.commit()
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Could not save inputs: {type(e).__name__}: {e}",
        )
    return {"message": "Fields updated", "paths": changed, "locked": True}


@router.post("/{deal_id}/fields/lock")
async def lock_field(deal_id: int, data: FieldLockIn, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Deal).where(Deal.id == deal_id))
    deal = result.scalar_one_or_none()
    if not deal:
        raise HTTPException(status_code=404, detail="Deal not found")

    metrics = copy.deepcopy(deal.metrics or {})
    metrics = set_lock(metrics, data.path, bool(data.locked))
    deal.metrics = _json_safe(jsonable_encoder(metrics))
    flag_modified(deal, "metrics")
    await db.commit()
    return {"message": "Lock updated", "path": data.path, "locked": bool(data.locked)}


@router.post("/{deal_id}/fields/resolve-conflict")
async def resolve_conflict(deal_id: int, data: ConflictResolveIn, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Deal).where(Deal.id == deal_id))
    deal = result.scalar_one_or_none()
    if not deal:
        raise HTTPException(status_code=404, detail="Deal not found")

    metrics = copy.deepcopy(deal.metrics or {})
    metrics = mark_manual_edit(metrics, data.path, data.value, lock=True)

    prov = dict(metrics.get("_provenance") or {})
    if data.path in prov and isinstance(prov[data.path], dict):
        prov[data.path].pop("conflict", None)
        metrics["_provenance"] = prov

    _refresh_integrity(deal, metrics)
    await db.commit()
    return {"message": "Conflict resolved", "path": data.path}

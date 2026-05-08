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
from app.services.confidence import assess_data_quality, summarize_math_checks
from app.services.data_integrity import mark_manual_edit, now_iso, set_lock
from app.services.deal_scorer import score_deal
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

    These checks are deterministic, so they can run in the same request that
    stores the correction. Any refresh failure is recorded on the deal instead
    of making a valid manual edit look like it failed to save.
    """
    math_checks = None
    try:
        math_checks = run_math_checks(metrics)
    except Exception as e:
        metrics["_manual_edit_warning"] = f"Math checks did not rerun: {type(e).__name__}: {e}"
    else:
        metrics["_math_checks"] = {
            "checked_at": now_iso(),
            "summary": summarize_math_checks(math_checks, metrics),
            "results": math_checks,
        }
    try:
        metrics["validation_flags"] = validate_deal_metrics(metrics, deal.property_type)
    except Exception as e:
        metrics.setdefault("validation_flags", [])
        metrics["_manual_edit_warning"] = f"Validation did not rerun: {type(e).__name__}: {e}"
    try:
        scores = score_deal(metrics, math_checks=math_checks)
    except Exception as e:
        metrics["_manual_edit_warning"] = f"Score did not refresh: {type(e).__name__}: {e}"
        try:
            data_quality = assess_data_quality(metrics, math_checks=math_checks)
        except Exception as quality_error:
            data_quality = {
                "stage": "refresh_failed",
                "can_score": False,
                "confidence_score": 0,
                "verified_at": (metrics.get("_verification") or {}).get("verified_at"),
                "critical_fields": [],
                "critical_summary": {
                    "total": 0,
                    "missing": 0,
                    "unverified": 0,
                    "conflicted": 0,
                    "bad": 0,
                    "review_only": 0,
                    "verified": 0,
                },
                "math_summary": summarize_math_checks(math_checks or [], metrics),
                "confidence_breakdown": {
                    "critical_field_score": 0,
                    "broad_verification_score": 0,
                    "math_failures": 0,
                    "math_warnings": 0,
                },
                "refresh_error": f"{type(quality_error).__name__}: {quality_error}",
            }
        scores = {
            "overall": None,
            "provisional_overall": None,
            "data_quality": data_quality,
            "refresh_error": f"{type(e).__name__}: {e}",
        }
    data_quality = scores.get("data_quality") if isinstance(scores, dict) else None
    if data_quality:
        metrics["_data_quality"] = data_quality
    deal.metrics = _json_safe(jsonable_encoder(metrics))
    deal.scores = _json_safe(jsonable_encoder(scores))
    flag_modified(deal, "metrics")
    flag_modified(deal, "scores")


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

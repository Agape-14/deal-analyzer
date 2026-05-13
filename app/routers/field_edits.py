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
from app.services.canonical_metrics import annotate_canonical_metrics
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
    review_key: Optional[str] = Field(None, min_length=1, max_length=300)
    review_action: str = Field("inputs_saved", max_length=40)
    review_note: Optional[str] = Field(None, max_length=1000)


class FieldLockIn(BaseModel):
    path: str
    locked: bool


class ConflictResolveIn(BaseModel):
    path: str
    value: Optional[float | str | int | bool] = None


class ReviewResolveIn(BaseModel):
    key: str = Field(..., min_length=1, max_length=300)
    action: str = Field("confirmed", max_length=40)
    note: Optional[str] = Field(None, max_length=1000)


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


def _get_metric_value(metrics: dict, path: str):
    cur = metrics
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def _append_field_history(metrics: dict, path: str, old_value, new_value, action: str) -> None:
    history = list(metrics.get("_field_history") or [])
    history.append(
        {
            "path": path,
            "old_value": old_value,
            "new_value": new_value,
            "action": action,
            "locked": True,
            "at": now_iso(),
            "user": "admin",
        }
    )
    metrics["_field_history"] = history[-200:]


def _mark_review_resolved(metrics: dict, key: str, action: str, note: Optional[str] = None) -> bool:
    resolutions = dict(metrics.get("_review_resolutions") or {})
    if key in resolutions and isinstance(resolutions[key], dict) and resolutions[key].get("resolved") is True:
        return False
    old_value = resolutions.get(key)
    new_value = {
        "resolved": True,
        "action": action,
        "note": note,
        "at": now_iso(),
        "user": "admin",
    }
    resolutions[key] = new_value
    metrics["_review_resolutions"] = resolutions
    _append_field_history(metrics, f"_review_resolutions.{key}", old_value, new_value, "resolve_review_item")
    return True


def _candidate_review_keys_for_paths(metrics: dict, scores: dict | None, paths: list[str]) -> list[str]:
    """Infer visible review rows that should clear when their inputs are saved."""
    affected = set(paths)
    keys: set[str] = {f"source:{path}" for path in affected}

    for flag in metrics.get("validation_flags") or []:
        if not isinstance(flag, dict):
            continue
        message = str(flag.get("message") or "")
        category = str(flag.get("category") or "")
        found_paths = set(_paths_in_message(message))
        if affected & found_paths:
            path = _best_path_from_message(message)
            keys.add(f"flag:{category}:{path or message}")

    for check in _blocking_math_checks(metrics, scores):
        check_name = str(check.get("check") or "")
        if check_name and _math_check_touches_paths(check_name, affected):
            keys.add(f"math:{check_name}")

    return sorted(keys)


def _blocking_math_checks(metrics: dict, scores: dict | None) -> list[dict]:
    data_quality = {}
    if isinstance(scores, dict):
        data_quality = scores.get("data_quality") or {}
    if not data_quality:
        data_quality = metrics.get("_data_quality") or {}
    math_summary = data_quality.get("math_summary") if isinstance(data_quality, dict) else {}
    blocking = math_summary.get("blocking") if isinstance(math_summary, dict) else None
    if isinstance(blocking, list):
        return [item for item in blocking if isinstance(item, dict)]
    math_checks = metrics.get("_math_checks") or {}
    summary = math_checks.get("summary") if isinstance(math_checks, dict) else {}
    blocking = summary.get("blocking") if isinstance(summary, dict) else None
    return [item for item in blocking if isinstance(item, dict)] if isinstance(blocking, list) else []


def _paths_in_message(message: str) -> list[str]:
    import re

    return re.findall(r"[a-z_]+\.[a-z_]+", message)


def _best_path_from_message(message: str) -> Optional[str]:
    matches = _paths_in_message(message)
    for token in ("target_", "net_"):
        for path in matches:
            if token in path:
                return path
    return matches[0] if matches else None


def _math_check_touches_paths(check_name: str, affected: set[str]) -> bool:
    name = " ".join(check_name.lower().split())
    groups = [
        (
            ("dscr", "debt service"),
            {
                "underwriting_checks.dscr",
                "financial_projections.stabilized_noi",
                "deal_structure.debt_amount",
                "deal_structure.interest_rate",
            },
        ),
        (
            ("ltv",),
            {"deal_structure.ltv", "deal_structure.debt_amount", "deal_structure.total_project_cost"},
        ),
        (
            ("total project cost", "equity"),
            {
                "deal_structure.total_project_cost",
                "deal_structure.total_equity_required",
                "deal_structure.preferred_equity_amount",
                "deal_structure.debt_amount",
            },
        ),
        (
            ("hard", "soft", "land"),
            {
                "construction_costs.hard_costs",
                "construction_costs.hard_costs_total",
                "construction_costs.soft_costs",
                "construction_costs.soft_costs_total",
                "construction_costs.land_cost",
                "construction_costs.land_cost_total",
                "construction_costs.contingency",
                "construction_costs.contingency_total",
                "deal_structure.total_project_cost",
            },
        ),
        (
            ("cost components",),
            {
                "construction_costs.hard_costs",
                "construction_costs.hard_costs_total",
                "construction_costs.soft_costs",
                "construction_costs.soft_costs_total",
                "construction_costs.land_cost",
                "construction_costs.land_cost_total",
                "construction_costs.contingency",
                "construction_costs.contingency_total",
                "deal_structure.total_project_cost",
            },
        ),
        (
            ("irr",),
            {
                "target_returns.target_irr",
                "target_returns.net_irr",
                "target_returns.target_cash_on_cash",
                "target_returns.distribution_yield",
            },
        ),
        (
            ("multiple",),
            {"target_returns.target_equity_multiple", "target_returns.net_equity_multiple"},
        ),
    ]
    for tokens, paths in groups:
        if all(token in name for token in tokens) and affected & paths:
            return True
    return False


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
    metrics = annotate_canonical_metrics(metrics)
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
        auto_review_keys = _candidate_review_keys_for_paths(metrics, deal.scores or {}, [data.path])
        old_value = _get_metric_value(metrics, data.path)
        metrics = mark_manual_edit(metrics, data.path, data.value, lock=bool(data.lock))
        _append_field_history(metrics, data.path, old_value, data.value, "manual_edit")
        resolved_count = 0
        for key in auto_review_keys:
            if _mark_review_resolved(
                metrics,
                key,
                "input_saved",
                f"{data.path} was saved from the Needs review workflow.",
            ):
                resolved_count += 1
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
    return {"message": "Field updated", "path": data.path, "locked": bool(data.lock), "review_resolved_count": resolved_count}


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
        auto_review_keys = _candidate_review_keys_for_paths(metrics, deal.scores or {}, [edit.path for edit in data.edits])
        for edit in data.edits:
            if edit.path in seen:
                raise HTTPException(status_code=400, detail=f"Duplicate edit path: {edit.path}")
            seen.add(edit.path)
            old_value = _get_metric_value(metrics, edit.path)
            metrics = mark_manual_edit(metrics, edit.path, edit.value, lock=bool(edit.lock))
            _append_field_history(metrics, edit.path, old_value, edit.value, "batch_manual_edit")
            changed.append(edit.path)

        review_keys = set(auto_review_keys)
        if data.review_key:
            review_keys.add(data.review_key)
        resolved_count = 0
        for key in sorted(review_keys):
            if _mark_review_resolved(
                metrics,
                key,
                data.review_action or "inputs_saved",
                data.review_note or f"{len(changed)} field{'s' if len(changed) != 1 else ''} saved from the Needs review workflow.",
            ):
                resolved_count += 1

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
    return {"message": "Fields updated", "paths": changed, "locked": True, "review_resolved": resolved_count > 0, "review_resolved_count": resolved_count}


@router.post("/{deal_id}/reviews/resolve")
async def resolve_review_item(deal_id: int, data: ReviewResolveIn, db: AsyncSession = Depends(get_db)):
    """Mark one review-queue item resolved without pretending it is a metric."""
    result = await db.execute(select(Deal).where(Deal.id == deal_id))
    deal = result.scalar_one_or_none()
    if not deal:
        raise HTTPException(status_code=404, detail="Deal not found")

    try:
        metrics = copy.deepcopy(deal.metrics or {})
        _mark_review_resolved(metrics, data.key, data.action or "confirmed", data.note)
        _refresh_integrity(deal, metrics)
        await db.commit()
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Could not resolve review item: {type(e).__name__}: {e}",
        )
    return {"message": "Review item resolved", "key": data.key, "resolved": True}


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
    old_value = _get_metric_value(metrics, data.path)
    metrics = mark_manual_edit(metrics, data.path, data.value, lock=True)
    _append_field_history(metrics, data.path, old_value, data.value, "resolve_conflict")

    prov = dict(metrics.get("_provenance") or {})
    if data.path in prov and isinstance(prov[data.path], dict):
        prov[data.path].pop("conflict", None)
        metrics["_provenance"] = prov

    _refresh_integrity(deal, metrics)
    await db.commit()
    return {"message": "Conflict resolved", "path": data.path}

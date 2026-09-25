"""Snapshot history and one atomic, revision-checked question resolution."""
import copy
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import AnalysisSnapshot, Deal
from app.services.analysis import REGISTRY, analysis_for_deal, number
from app.services.data_integrity import mark_manual_edit, now_iso
from app.routers.field_edits import _append_field_history, _refresh_integrity

router = APIRouter()


async def get_deal(deal_id, db):
    deal = await db.get(Deal, deal_id)
    if not deal or deal.deleted_at is not None:
        raise HTTPException(404, "Deal not found")
    return deal


@router.get("/{deal_id}/analysis/history")
async def history(deal_id: int, db: AsyncSession = Depends(get_db)):
    await get_deal(deal_id, db)
    records = (await db.execute(select(AnalysisSnapshot).where(AnalysisSnapshot.deal_id == deal_id).order_by(AnalysisSnapshot.version.desc()).limit(50))).scalars().all()
    return [{"version": s.version, "input_hash": s.input_hash, "created_at": s.created_at.isoformat(), "status": s.payload["status"], "changes": s.payload.get("changes", [])} for s in records]


@router.get("/{deal_id}/analysis/{version}")
async def snapshot(deal_id: int, version: int, db: AsyncSession = Depends(get_db)):
    await get_deal(deal_id, db)
    row = (await db.execute(select(AnalysisSnapshot).where(AnalysisSnapshot.deal_id == deal_id, AnalysisSnapshot.version == version))).scalar_one_or_none()
    if not row:
        raise HTTPException(404, "Analysis revision not found")
    return row.payload


class ResolutionField(BaseModel):
    path: str = Field(min_length=1, max_length=200)
    value: Any


class Resolution(BaseModel):
    expected_revision: int = Field(ge=1)
    reason: str = Field(min_length=3, max_length=1000)
    fields: list[ResolutionField] = Field(min_length=1, max_length=30)


@router.post("/{deal_id}/analysis/resolve")
async def resolve(deal_id: int, data: Resolution, db: AsyncSession = Depends(get_db)):
    deal = await get_deal(deal_id, db)
    if deal.revision != data.expected_revision:
        raise HTTPException(409, "The deal changed while you were reviewing it. Reload before saving.")
    metrics = copy.deepcopy(deal.metrics or {})
    current = analysis_for_deal(deal)
    paths = set()
    for edit in data.fields:
        if edit.path in paths:
            raise HTTPException(422, "Each fact may be resolved only once per request.")
        paths.add(edit.path)
        if edit.path == "_analysis_context.investor_class":
            if not isinstance(edit.value, str) or not edit.value.strip() or len(edit.value) > 100:
                raise HTTPException(422, "Choose a valid investor class.")
            metrics.setdefault("_analysis_context", {})["investor_class"] = edit.value.strip()
            continue
        spec = REGISTRY.get(edit.path)
        if not spec:
            raise HTTPException(422, "This field has no defined metric and unit.")
        value = edit.value
        if spec[0] != "text":
            value = number(value, spec[0])
            if value is None:
                raise HTTPException(422, f"{spec[1]} needs a finite {spec[0]} value.")
        elif not isinstance(value, str) or not value.strip():
            raise HTTPException(422, f"{spec[1]} needs a text value.")
        if edit.path == "target_returns.primary_strategy" and value not in {"hold", "sale", "hold_with_sale_option"}:
            raise HTTPException(422, "Strategy must be hold, sale, or hold_with_sale_option.")
        old = (current["facts"].get(edit.path) or {}).get("value")
        metrics = mark_manual_edit(metrics, edit.path, value, lock=True)
        metrics["_provenance"][edit.path]["verification_note"] = data.reason
        _append_field_history(metrics, edit.path, old, value, "question_resolved")
    metrics["_analysis_resolution"] = {"at": now_iso(), "reason": data.reason, "paths": sorted(paths), "based_on_version": current["version"]}
    _refresh_integrity(deal, metrics)
    await db.commit()
    await db.refresh(deal)
    return {"revision": deal.revision, "analysis": analysis_for_deal(deal)}

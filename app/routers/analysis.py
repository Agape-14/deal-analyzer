"""Snapshot history and one atomic, revision-checked question resolution."""
import copy
import re
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.database import get_db
from app.models import AnalysisSnapshot, Deal, DealDocument
from app.permissions import require_analyst
from app.services.analysis import (
    REGISTRY, RETURN_CONTEXT_FIELDS, RETURN_REVIEWS_KEY, analysis_for_deal,
    build_analysis, identity, return_review_binding, valid_number, valid_tiers,
)
from app.services.analysis_store import document_manifest
from app.services.data_integrity import mark_manual_edit, now_iso
from app.services.document_versions import review_documents
from app.services.financial_presentation import RETURN_LABELS
from app.services.return_schedules import active_sources_fingerprint
from app.services.source_evidence import fresh_audit_evidence, numeric_quote_error
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
    return [{"version": s.version, "input_hash": s.input_hash, "created_at": s.created_at.isoformat(), "status": s.payload["status"], "changes": s.payload.get("changes", []), "can_restore": s.input_metrics is not None} for s in records]


@router.get("/{deal_id}/analysis/preview", dependencies=[Depends(require_analyst)])
async def preview(deal_id: int, db: AsyncSession = Depends(get_db)):
    deal = await get_deal(deal_id, db)
    docs = (await db.execute(select(DealDocument).where(DealDocument.deal_id == deal_id))).scalars().all()
    candidate = build_analysis(deal.metrics, document_manifest(docs), deal.property_type)
    return {"expected_revision": deal.revision, "current": analysis_for_deal(deal), "candidate": candidate}


class Adoption(BaseModel):
    expected_revision: int = Field(ge=1)
    input_hash: str = Field(min_length=64, max_length=64)


@router.post("/{deal_id}/analysis/adopt")
async def adopt(deal_id: int, data: Adoption, db: AsyncSession = Depends(get_db)):
    deal = await get_deal(deal_id, db)
    candidate = await preview(deal_id, db)
    if deal.revision != data.expected_revision or candidate["candidate"]["input_hash"] != data.input_hash:
        raise HTTPException(409, "The inputs changed. Preview the current documents before saving.")
    flag_modified(deal, "metrics")
    await db.commit()
    await db.refresh(deal)
    return {"revision": deal.revision, "analysis": analysis_for_deal(deal)}


class Restoration(BaseModel):
    expected_revision: int = Field(ge=1)
    reason: str = Field(min_length=3, max_length=1000)


@router.post("/{deal_id}/analysis/{version}/restore")
async def restore(deal_id: int, version: int, data: Restoration, db: AsyncSession = Depends(get_db)):
    deal = await get_deal(deal_id, db)
    if deal.review_job and deal.review_job.status in {"queued", "running"}:
        raise HTTPException(409, "Document review is active. Wait for it to finish before restoring inputs.")
    if deal.revision != data.expected_revision:
        raise HTTPException(409, "The deal changed. Reload before restoring inputs.")
    row = (await db.execute(select(AnalysisSnapshot).where(AnalysisSnapshot.deal_id == deal_id, AnalysisSnapshot.version == version))).scalar_one_or_none()
    if not row or row.input_metrics is None:
        raise HTTPException(409, "This revision predates restorable input history.")
    metrics = copy.deepcopy(row.input_metrics)
    metrics["_analysis_restore"] = {"version": version, "reason": data.reason, "at": now_iso()}
    metrics["_pipeline"] = {"status": "complete", "message": "Prior inputs restored; source acceptance was rechecked against the current documents."}
    _refresh_integrity(deal, metrics)
    await db.commit()
    await db.refresh(deal)
    return {"revision": deal.revision, "analysis": analysis_for_deal(deal)}


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
        if spec[0] == "waterfall_tiers":
            value = valid_tiers(value)
            if value is None:
                raise HTTPException(422, "Tiers need ordered thresholds and LP/GP percentages totaling 100.")
        elif spec[0] != "text":
            value = valid_number(edit.path, value, spec[0])
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


class ReturnReview(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)

    expected_revision: int = Field(ge=1)
    path: str = Field(min_length=1, max_length=200)


class ScopedReturn(ReturnReview):
    action: Literal["scope"]
    scenario: Literal["hold", "sale", "unspecified"] = "unspecified"
    investor_class: str = Field(default="", max_length=100)
    basis: str = Field(default="", max_length=100)
    period: str = Field(default="", max_length=100)
    source_doc_id: int = Field(ge=1)
    source_page: int | None = Field(default=None, ge=1)
    source_sheet: str | None = Field(default=None, min_length=1, max_length=200)
    source_cell: str | None = Field(default=None, pattern=r"^[A-Za-z]{1,3}[1-9]\d{0,6}$")
    source_excerpt: str = Field(min_length=8, max_length=1500)

    @model_validator(mode="after")
    def check_location(self):
        if self.source_page is not None:
            if self.source_sheet or self.source_cell:
                raise ValueError("Provide a PDF page or a workbook sheet and value cell.")
        elif not (self.source_sheet and self.source_cell):
            raise ValueError("Provide a PDF page or a workbook sheet and value cell.")
        return self


class WithheldReturn(ReturnReview):
    action: Literal["withhold"]
    reason: str = Field(min_length=3, max_length=1000)


def cited_return_value(data: ScopedReturn, fact):
    quote = data.source_excerpt.replace("−", "-")
    if data.source_cell:
        cell = re.escape(data.source_cell)
        match = re.search(rf"(?<![A-Za-z0-9]){cell}\s*=([^|\r\n]*)", quote, re.I)
        quote = match[1] if match else ""
    elif fact["identity"]["unit"] == "percent":
        # Unmarked numbers in a PDF may be dates, periods, or invested amounts.
        quote = " ".join(re.findall(r"(?<![\w.])-?\d[\d,]*(?:\.\d+)?\s*(?:%|percent\b)", quote, re.I))
    if fact["identity"]["unit"] == "multiple":
        quote = re.sub(r"(?<=\d)\s*[x×](?!\w)", "", quote, flags=re.I)
    return numeric_quote_error(fact["value"], {"source_excerpt": quote, "source_sheet": data.source_sheet},
                               allow_workbook_ratio=fact["identity"]["unit"] == "percent")


@router.put("/{deal_id}/analysis/return-context")
async def review_return(
    deal_id: int,
    data: Annotated[ScopedReturn | WithheldReturn, Body(discriminator="action")],
    db: AsyncSession = Depends(get_db),
):
    deal = await get_deal(deal_id, db)
    if deal.revision != data.expected_revision:
        raise HTTPException(409, "The deal changed. Reload before reviewing this return.")
    if deal.review_job and deal.review_job.status in {"queued", "running"}:
        raise HTTPException(409, "Wait for the document review to finish before reviewing this return.")

    current = analysis_for_deal(deal)
    published_paths = {current["returns"].get(f"{key}_path") for key, _ in RETURN_LABELS
                       if current["returns"].get(key) is not None}
    fact = current["facts"].get(data.path)
    if data.path not in published_paths or not fact:
        raise HTTPException(422, "Choose an accepted return currently shown in Summary.")
    metrics = copy.deepcopy(deal.metrics or {})
    record = {"action": data.action, "binding": return_review_binding(metrics, data.path, fact["value"])}
    if isinstance(data, WithheldReturn):
        record["reason"] = data.reason
    else:
        context = {key: getattr(data, key) for key in RETURN_CONTEXT_FIELDS
                   if getattr(data, key) not in {"", "unspecified"}}
        if not context:
            raise HTTPException(422, "Record at least one return context field supported by the source.")
        resolved = identity(data.path, fact["identity"]["unit"], context)
        if any(getattr(resolved, key) != value for key, value in context.items()):
            raise HTTPException(422, "The proposed context disagrees with this return's definition.")
        docs = (await db.execute(select(DealDocument).where(DealDocument.deal_id == deal.id))).scalars().all()
        manifest = document_manifest(docs)
        citation, error = fresh_audit_evidence(data.model_dump(), review_documents(docs), manifest)
        error = error or cited_return_value(data, fact)
        if error:
            raise HTTPException(422, error)
        record.update(context=context, citation=citation, document_set=active_sources_fingerprint(manifest))

    metrics.setdefault(RETURN_REVIEWS_KEY, {})[data.path] = record
    _refresh_integrity(deal, metrics)
    await db.commit()
    await db.refresh(deal)
    return {"revision": deal.revision, "analysis": analysis_for_deal(deal)}

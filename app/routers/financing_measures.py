"""Edit cited construction financing measures as an analyst."""

import re

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.routers.analysis import get_deal
from app.routers.field_edits import _refresh_integrity
from app.services.analysis import build_analysis
from app.services.analysis_store import document_manifest
from app.services.document_versions import review_documents
from app.services.financing_measures import (
    FINANCING_KEY,
    FINANCING_LABELS,
    FinancingKind,
    financing_document_set,
    matching_debt_amount,
)
from app.services.review_drafts import load_documents
from app.services.source_evidence import fresh_audit_evidence, numeric_quote_error


router = APIRouter()

MEASURE_TERMS = {
    "draw": r"\b(?:draws?|drawdowns?|advances?)\b",
    "peak_balance": r"\b(?:peak|max(?:imum)?)\s+(?:construction\s+)?(?:loan|balance|debt)\b",
    "modeled_payoff": r"\b(?:pay[ -]?off|balance\s+at\s+(?:exit|sale|completion))\b",
    "lender_commitment": r"\b(?:commitment|committed\s+(?:amount|loan|facility))\b",
}
PDF_AMOUNT = re.compile(r"(?<![\w.])-?\d[\d,]*(?:\.\d+)?")


class MeasureInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)

    kind: FinancingKind
    amount: float = Field(ge=0, le=10**15, allow_inf_nan=False)
    source_doc_id: int = Field(gt=0)
    source_page: int | None = Field(default=None, gt=0)
    source_sheet: str | None = Field(default=None, min_length=1, max_length=200)
    source_cell: str | None = Field(default=None, pattern=r"^[A-Za-z]{1,3}[1-9]\d{0,6}$")
    source_excerpt: str = Field(min_length=8, max_length=1000)
    note: str = Field(default="", max_length=500)

    @model_validator(mode="after")
    def require_source_location(self):
        if self.source_page is not None:
            if self.source_sheet is not None or self.source_cell is not None:
                raise ValueError("Provide one PDF page or a sheet and cell.")
        elif not (self.source_sheet and self.source_cell):
            raise ValueError("Provide one PDF page or a sheet and cell.")
        return self


class FinancingUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    expected_revision: int = Field(ge=1)
    debt_amount_kind: FinancingKind | None = None
    measures: list[MeasureInput] = Field(max_length=len(FINANCING_LABELS))

    @model_validator(mode="after")
    def each_measure_once(self):
        kinds = {row.kind for row in self.measures}
        if len(kinds) != len(self.measures):
            raise ValueError("Save each financing measure only once.")
        if self.debt_amount_kind is not None and self.debt_amount_kind not in kinds:
            raise ValueError("Choose a listed measure for the accepted debt amount.")
        return self


def _verified_measure(row, docs, manifest):
    label = FINANCING_LABELS[row.kind]
    citation, error = fresh_audit_evidence(row.model_dump(), docs, manifest)
    if error:
        raise HTTPException(422, f"{label}. {error}")

    quote = row.source_excerpt
    if not re.search(MEASURE_TERMS[row.kind], quote, re.I):
        raise HTTPException(422, f"{label}. Include source wording that identifies this measure in the supporting quote.")
    if row.source_cell:
        # Check the actual cited amount cell, not other amounts on the same row.
        cell = re.escape(row.source_cell)
        match = re.search(rf"(?<![A-Za-z0-9]){cell}\s*=([^|\r\n]*)", quote, re.I)
        quote = match[1] if match else ""
    quote = re.sub(r"-?\d[\d,]*(?:\.\d+)?\s*%", "", quote)
    if row.source_page is not None:
        competing_measure = any(
            kind != row.kind and re.search(pattern, quote, re.I)
            for kind, pattern in MEASURE_TERMS.items()
        )
        if competing_measure or len(PDF_AMOUNT.findall(quote)) > 1:
            raise HTTPException(422, f"{label}. Quote only this financing measure and its amount.")
    error = numeric_quote_error(row.amount, {"source_excerpt": quote}, allow_workbook_ratio=False)
    if error:
        raise HTTPException(422, f"{label}. {error}")
    return {"kind": row.kind, "amount": row.amount, "note": row.note, "citation": citation}


@router.put("/{deal_id}/analysis/financing-measures")
async def save_financing_measures(
    deal_id: int,
    data: FinancingUpdate,
    db: AsyncSession = Depends(get_db),
):
    deal = await get_deal(deal_id, db)
    if deal.revision != data.expected_revision:
        raise HTTPException(409, "The deal changed. Reload before saving these financing measures.")
    if deal.review_job and deal.review_job.status in {"queued", "running"}:
        raise HTTPException(409, "Wait for the document review to finish before saving financing measures.")

    documents = await load_documents(db, deal.id)
    manifest = document_manifest(documents)
    active = review_documents(documents)
    measures = [_verified_measure(row, active, manifest) for row in data.measures]
    metrics = {**(deal.metrics or {})}
    if data.debt_amount_kind is not None:
        analysis = build_analysis(metrics, manifest, deal.property_type)
        debt = (analysis["accepted_metrics"].get("deal_structure") or {}).get("debt_amount")
        selected = next(row for row in data.measures if row.kind == data.debt_amount_kind)
        if not matching_debt_amount(metrics, debt, selected.amount):
            raise HTTPException(422, "The label must match the accepted debt amount and its construction financing context.")

    if measures:
        metrics[FINANCING_KEY] = {
            "version": 1,
            "debt_amount_kind": data.debt_amount_kind,
            "document_set": financing_document_set(manifest),
            "measures": measures,
        }
    else:
        metrics.pop(FINANCING_KEY, None)
    _refresh_integrity(deal, metrics)
    await db.commit()
    await db.refresh(deal)
    return {"revision": deal.revision}

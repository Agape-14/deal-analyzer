import os
import io
from collections import defaultdict
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import StreamingResponse
from app.rate_limit import limit
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload
from pydantic import BaseModel, Field, field_validator
from typing import Optional
from app.database import get_db
from app.models import Deal, DealDocument, Developer
from app.services.deal_validator import validate_deal_metrics
from app.services.math_checker import run_math_checks
from app.services.market_data import fetch_market_data
from app.services.cashflow_projector import project_cash_flows
from app.services.waterfall_calculator import waterfall_from_deal
from app.services.canonical_metrics import canonical_return_summary
from app.services.analysis import analysis_for_deal, effective_scores
from app.services.financial_presentation import (
    RETURN_LABELS, accepted_return_fact, operating_fact_context, optional_sale_returns, return_context, return_evidence,
    cash_flow_check_context,
    schedule_context, schedule_source, source_reference,
)
from app.services.document_versions import document_payloads
from app.services.data_integrity import ANALYST_REVIEW_RECORD_KEYS, quality_summary
from app.services.location_intelligence import build_location_bundle

router = APIRouter()


# Allowed status values for a Deal - closes the "any string accepted" hole.
# Keeps the legacy "reviewing/interested/passed/committed/closed" taxonomy.
DEAL_STATUSES = {"reviewing", "interested", "passed", "committed", "closed"}
PROPERTY_TYPES = {
    "multifamily", "office", "retail", "industrial", "hospitality",
    "mixed-use", "development", "land", "other",
}


class DealCreate(BaseModel):
    developer_id: Optional[int] = Field(None, ge=1)
    project_name: str = Field(..., min_length=1, max_length=255)
    location: Optional[str] = Field("", max_length=500)
    city: Optional[str] = Field("", max_length=120)
    state: Optional[str] = Field("", max_length=64)
    property_type: Optional[str] = "multifamily"
    status: Optional[str] = "reviewing"
    notes: Optional[str] = Field("", max_length=10000)

    @field_validator("status")
    @classmethod
    def _status_valid(cls, v):
        if v is None or v == "":
            return "reviewing"
        if v not in DEAL_STATUSES:
            raise ValueError(f"status must be one of {sorted(DEAL_STATUSES)}")
        return v

    @field_validator("property_type")
    @classmethod
    def _ptype_valid(cls, v):
        if v is None or v == "":
            return "multifamily"
        # Allow unknown types but normalize to lowercase. Unknown types pass
        # through (e.g. "self-storage") so the system stays extensible.
        return v.strip().lower()


class DealUpdate(BaseModel):
    expected_revision: Optional[int] = Field(None, ge=1)
    developer_id: Optional[int] = Field(None, ge=1)
    project_name: Optional[str] = Field(None, min_length=1, max_length=255)
    location: Optional[str] = Field(None, max_length=500)
    city: Optional[str] = Field(None, max_length=120)
    state: Optional[str] = Field(None, max_length=64)
    property_type: Optional[str] = None
    status: Optional[str] = None
    metrics: Optional[dict] = None
    scores: Optional[dict] = None
    notes: Optional[str] = Field(None, max_length=10000)

    @field_validator("status")
    @classmethod
    def _status_valid(cls, v):
        if v is None:
            return v
        if v not in DEAL_STATUSES:
            raise ValueError(f"status must be one of {sorted(DEAL_STATUSES)}")
        return v


class CompareRequest(BaseModel):
    # Bound the compare set so the UI can't force the backend to fan out
    # to unbounded deals (and produce a 40-column Excel file).
    deal_ids: list[int] = Field(..., min_length=1, max_length=8)


def _deal_to_dict(deal: Deal, developer_name: str = None, *, accepted_only=False, reading_documents=None) -> dict:
    metrics = dict(deal.metrics or {})
    metrics.pop("_review_draft", None)
    metrics.pop("_credit_review_attempt", None)
    metrics.pop("_review_findings", None)
    metrics.pop("_return_crosscheck", None)
    analysis = analysis_for_deal(deal, reading_documents=reading_documents)
    if accepted_only:
        metrics = dict(analysis["accepted_metrics"])
    scores = effective_scores(deal)
    return_summary = analysis["returns"]
    metrics["_canonical_returns"] = return_summary
    from app.services.review_jobs import public_pipeline
    metrics["_pipeline"] = public_pipeline(deal)
    deal_structure = metrics.get("deal_structure", {}) or {}

    return {
        "id": deal.id,
        "revision": deal.revision,
        "analysis": analysis,
        "developer_id": deal.developer_id,
        "developer_name": developer_name or "",
        "project_name": deal.project_name,
        "location": deal.location,
        "city": deal.city,
        "state": deal.state,
        "property_type": deal.property_type,
        "status": deal.status,
        "metrics": metrics,
        "scores": scores,
        "overall_score": scores.get("overall", None),
        "target_irr": return_summary.get("target_irr"),
        "target_equity_multiple": return_summary.get("target_equity_multiple"),
        "target_cash_on_cash": return_summary.get("cash_on_cash"),
        "minimum_investment": (analysis["accepted_metrics"].get("deal_structure") or {}).get("minimum_investment"),
        "notes": deal.notes,
        "lat": deal.lat,
        "lng": deal.lng,
        "created_at": deal.created_at.isoformat() if deal.created_at else None,
    }


@router.get("")
async def list_deals(
    trash: bool = False,
    db: AsyncSession = Depends(get_db),
):
    """List deals. Trashed (soft-deleted) rows are excluded unless
    `?trash=true` is passed - handy for a future 'Trash' view."""
    visible = Deal.deleted_at.is_not(None) if trash else Deal.deleted_at.is_(None)
    q = select(Deal).options(selectinload(Deal.developer)).where(visible).order_by(Deal.created_at.desc())
    result = await db.execute(q)
    deals = result.scalars().all()
    if not deals:
        return []

    # Only project the flags used for reading diagnostics. The original text
    # is needed for source review and detail requests, which load it separately.
    text = func.coalesce(DealDocument.extracted_text, "")
    reading_rows = await db.execute(
        select(
            DealDocument.id, DealDocument.deal_id, DealDocument.filename, DealDocument.file_path,
            DealDocument.file_sha256, DealDocument.source_role, DealDocument.superseded_by_id,
            DealDocument.version_note, DealDocument.doc_type, DealDocument.page_count,
            DealDocument.upload_date, DealDocument.extraction_quality,
            (text != "").label("has_text"),
            text.contains("[formula has no cached value]").label("has_uncached_formulas"),
        )
        .join(Deal, Deal.id == DealDocument.deal_id)
        .where(visible)
        .order_by(DealDocument.id)
    )
    documents_by_deal = defaultdict(list)
    for document in reading_rows:
        documents_by_deal[document.deal_id].append(document)
    return [
        _deal_to_dict(d, d.developer.name if d.developer else "",
                      reading_documents=document_payloads(documents_by_deal.get(d.id, ())))
        for d in deals
    ]


@router.post("")
async def create_deal(data: DealCreate, db: AsyncSession = Depends(get_db)):
    deal = Deal(**data.model_dump())
    db.add(deal)
    await db.commit()
    await db.refresh(deal)
    return {"id": deal.id, "project_name": deal.project_name, "message": "Deal created"}


@router.get("/pipeline/summary")
async def pipeline_summary_endpoint(
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    """Dashboard widgets: total deals, velocity (6mo), win rate (12mo),
    aging deals, capital deployed, average analyst score. Derived from
    the live Deal table on every call - no materialized view yet.

    Cached for 30s. The numbers change only when a deal is created /
    scored / status-changed, which is infrequent on an operator tool.
    """
    from app.services.pipeline_analytics import pipeline_summary

    result = await db.execute(
        select(Deal).options(selectinload(Deal.developer)).where(Deal.deleted_at.is_(None))
    )
    response.headers["Cache-Control"] = "private, max-age=30"
    return pipeline_summary(result.scalars().all())


@router.get("/{deal_id}")
async def get_deal(deal_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Deal)
        .options(selectinload(Deal.developer), selectinload(Deal.documents))
        .where(Deal.id == deal_id)
    )
    deal = result.scalar_one_or_none()
    # Treat soft-deleted rows as gone for GETs; restore via POST /{id}/restore.
    if not deal or deal.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Deal not found")

    data = _deal_to_dict(deal, deal.developer.name if deal.developer else "")
    data["documents"] = document_payloads(deal.documents)
    # Quality summary of the metrics (counts of verified / extracted / conflicting / locked)
    if deal.metrics:
        data["quality"] = quality_summary(deal.metrics)
    return data


@router.put("/{deal_id}")
async def update_deal(deal_id: int, data: DealUpdate, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Deal).where(Deal.id == deal_id))
    deal = result.scalar_one_or_none()
    if not deal or deal.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Deal not found")
    if data.expected_revision is not None and data.expected_revision != deal.revision:
        raise HTTPException(409, "The deal changed. Reload before saving your edits.")

    update_data = data.model_dump(exclude_unset=True)
    update_data.pop("expected_revision", None)
    if update_data.get("metrics") is not None:
        metrics = update_data["metrics"]
        stored = deal.metrics or {}
        for key in ANALYST_REVIEW_RECORD_KEYS:
            metrics.pop(key, None)
            if key in stored:
                metrics[key] = stored[key]
    if "developer_id" in update_data and update_data["developer_id"] is not None:
        sponsor = await db.get(Developer, update_data["developer_id"])
        if not sponsor or sponsor.deleted_at is not None:
            raise HTTPException(422, "Choose an active sponsor")
    intake = dict((deal.metrics or {}).get("_intake") or {})
    if intake:
        automatic = dict(intake.get("auto_fields") or {})
        for key in update_data:
            automatic.pop("sponsor" if key == "developer_id" else key, None)
        intake["auto_fields"] = automatic
        if "project_name" in update_data:
            intake["name_origin"] = "manual"
        if "metrics" not in update_data:
            deal.metrics = {**(deal.metrics or {}), "_intake": intake}
    for key, value in update_data.items():
        if value is not None or key == "developer_id":
            setattr(deal, key, value)
    await db.commit()
    await db.refresh(deal)
    return {"message": "Deal updated", "id": deal.id}


@router.delete("/{deal_id}")
async def delete_deal(deal_id: int, db: AsyncSession = Depends(get_db)):
    """Soft-delete. The deal is hidden from list/get endpoints but
    remains in the DB. `POST /{id}/restore` reverses within the undo
    window; `DELETE /{id}/purge` hard-deletes immediately."""
    result = await db.execute(select(Deal).where(Deal.id == deal_id))
    deal = result.scalar_one_or_none()
    if not deal or deal.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Deal not found")
    deal.deleted_at = datetime.now(timezone.utc)
    await db.commit()
    return {"message": "Deal moved to trash", "id": deal_id}


@router.post("/{deal_id}/restore")
async def restore_deal(deal_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Deal).where(Deal.id == deal_id))
    deal = result.scalar_one_or_none()
    if not deal:
        raise HTTPException(status_code=404, detail="Deal not found")
    deal.deleted_at = None
    await db.commit()
    return {"message": "Restored", "id": deal_id}


@router.delete("/{deal_id}/purge")
async def purge_deal(deal_id: int, db: AsyncSession = Depends(get_db)):
    """Hard-delete a soft-deleted deal. Only allowed once the row is
    already in the trash - prevents accidental irreversible removal."""
    result = await db.execute(select(Deal).where(Deal.id == deal_id))
    deal = result.scalar_one_or_none()
    if not deal:
        raise HTTPException(status_code=404, detail="Deal not found")
    if deal.deleted_at is None:
        raise HTTPException(
            status_code=409,
            detail="Deal must be in the trash before it can be purged. Call DELETE first.",
        )
    await db.delete(deal)
    await db.commit()
    return {"message": "Purged"}


# ===== Documents =====

@router.get("/{deal_id}/documents")
async def list_documents(deal_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(DealDocument).where(DealDocument.deal_id == deal_id).order_by(DealDocument.upload_date.desc())
    )
    docs = result.scalars().all()
    out = []
    for doc in docs:
        q = doc.extraction_quality or {}
        out.append(
            {
                "id": doc.id,
                "filename": doc.filename,
                "doc_type": doc.doc_type,
                "page_count": doc.page_count,
                "upload_date": doc.upload_date.isoformat() if doc.upload_date else None,
                "has_text": bool(doc.extracted_text),
                "extraction_quality": {
                    "quality_score": q.get("quality_score"),
                    "ocr_pages": q.get("ocr_pages", 0),
                    "empty_pages": q.get("empty_pages", []),
                }
                if q
                else None,
            }
        )
    return out


@router.delete("/documents/{doc_id}")
async def delete_document(doc_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(DealDocument).where(DealDocument.id == doc_id))
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    # Delete file
    if os.path.exists(doc.file_path):
        os.remove(doc.file_path)

    await db.delete(doc)
    await db.commit()
    return {"message": "Document deleted"}


@router.get("/documents/{doc_id}/text")
async def get_document_text(doc_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(DealDocument).where(DealDocument.id == doc_id))
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return {"id": doc.id, "filename": doc.filename, "text": doc.extracted_text}


# ===== Validation and math =====

@router.get("/{deal_id}/validate")
async def validate_deal(deal_id: int, db: AsyncSession = Depends(get_db)):
    """Run validation checks on current metrics and return flags."""
    result = await db.execute(select(Deal).where(Deal.id == deal_id))
    deal = result.scalar_one_or_none()
    if not deal:
        raise HTTPException(status_code=404, detail="Deal not found")

    if not deal.metrics:
        raise HTTPException(status_code=400, detail="No metrics extracted yet. Run extraction first.")

    flags = validate_deal_metrics(deal.metrics, deal.property_type)

    # Also update stored flags
    metrics = deal.metrics.copy()
    metrics["validation_flags"] = flags
    deal.metrics = metrics
    await db.commit()

    return {"flags": flags, "summary": {
        "red": len([f for f in flags if f["severity"] == "red"]),
        "yellow": len([f for f in flags if f["severity"] == "yellow"]),
        "green": len([f for f in flags if f["severity"] == "green"]),
    }}


@router.get("/{deal_id}/math-check")
async def math_check_deal(deal_id: int, db: AsyncSession = Depends(get_db)):
    """Run deterministic math verification - zero AI, pure arithmetic.
    
    Cross-checks all calculations, internal consistency, and benchmark ranges.
    """
    result = await db.execute(select(Deal).where(Deal.id == deal_id))
    deal = result.scalar_one_or_none()
    if not deal:
        raise HTTPException(status_code=404, detail="Deal not found")

    if not deal.metrics:
        raise HTTPException(status_code=400, detail="No metrics extracted yet.")

    checks = run_math_checks(deal.metrics)
    
    summary = {
        'pass': len([c for c in checks if c['status'] == 'pass']),
        'fail': len([c for c in checks if c['status'] == 'fail']),
        'warn': len([c for c in checks if c['status'] == 'warn']),
        'info': len([c for c in checks if c['status'] == 'info']),
        'total': len(checks),
    }

    return {"checks": checks, "summary": summary}


# ===== Location intelligence =====

@router.get("/{deal_id}/location")
async def get_deal_location(
    deal_id: int,
    radius_m: int = 1600,
    refresh: bool = False,
    db: AsyncSession = Depends(get_db),
):
    """Return cached or freshly-fetched location data for a deal.

    Payload shape (all sources free / unauthenticated by default):
      - lat, lng             - resolved via Nominatim or user-placed
      - display_name         - free-form, good enough for a map attribution
      - radius_m             - currently fetched radius
      - categories           - {apartments|restaurants|grocery|transit|schools|
                                healthcare|parks|employers: [POI...]}
      - fmr                  - HUD Fair Market Rent (if HUD_API_TOKEN set)
      - fetched_at           - unix timestamp, used for staleness UI

    Results are cached in `deal.location_data` for 7 days unless
    `refresh=true` is passed.
    """
    radius_m = max(500, min(8000, int(radius_m)))
    result = await db.execute(select(Deal).where(Deal.id == deal_id))
    deal = result.scalar_one_or_none()
    if not deal:
        raise HTTPException(status_code=404, detail="Deal not found")

    bundle = await build_location_bundle(deal, radius_m=radius_m, force_refresh=refresh)

    # Persist whatever we learned so the next page load is instant.
    if bundle.get("lat") is not None and bundle.get("lng") is not None:
        deal.lat = bundle["lat"]
        deal.lng = bundle["lng"]
    deal.location_data = bundle
    await db.commit()

    return bundle


class LocationManualIn(BaseModel):
    lat: float = Field(..., ge=-90, le=90)
    lng: float = Field(..., ge=-180, le=180)


@router.post("/{deal_id}/location/manual")
async def set_manual_location(
    deal_id: int,
    data: LocationManualIn,
    db: AsyncSession = Depends(get_db),
):
    """Pin the deal's map position by hand.

    Geocoding can miss when the address is a new development or when the
    city/state pair is ambiguous. This lets the user drop a marker
    precisely on the site; subsequent GETs use these coords and re-query
    Overpass from the new center.
    """
    result = await db.execute(select(Deal).where(Deal.id == deal_id))
    deal = result.scalar_one_or_none()
    if not deal:
        raise HTTPException(status_code=404, detail="Deal not found")
    deal.lat = float(data.lat)
    deal.lng = float(data.lng)
    # Invalidate any cached categories - they were centered on the old point.
    ld = deal.location_data or {}
    if isinstance(ld, dict):
        ld.pop("categories", None)
        ld.pop("fetched_at", None)
        deal.location_data = ld
    await db.commit()
    return {"message": "Location updated", "lat": deal.lat, "lng": deal.lng}


# ===== Market Research =====

@router.post("/{deal_id}/market-research", dependencies=[Depends(limit("ai"))])
async def market_research(deal_id: int, db: AsyncSession = Depends(get_db)):
    """Refresh structured public area context for this asset type, without AI-generated statistics."""
    result = await db.execute(select(Deal).where(Deal.id == deal_id))
    deal = result.scalar_one_or_none()
    if not deal:
        raise HTTPException(status_code=404, detail="Deal not found")

    city = deal.city or (deal.metrics or {}).get("market_location", {}).get("city", "")
    state = deal.state or (deal.metrics or {}).get("market_location", {}).get("state", "")

    if not city or not state:
        raise HTTPException(status_code=400, detail="City and state are required. Update the deal first.")

    try:
        market_data = await fetch_market_data(city, state, deal.property_type)
    except Exception as e:
        msg = str(e)
        status = 503 if ("ANTHROPIC_API_KEY" in msg or "BRAVE_API_KEY" in msg) else 500
        raise HTTPException(status_code=status, detail=f"Market research failed: {msg}")

    # Save to deal metrics
    metrics = deal.metrics.copy() if deal.metrics else {}
    metrics["_public_context"] = market_data
    deal.metrics = metrics
    await db.commit()

    return {"message": "Market research complete", "market_research": market_data}


@router.get("/{deal_id}/public-context")
async def public_market_context(deal_id: int, db: AsyncSession = Depends(get_db)):
    deal = (await db.execute(select(Deal).where(Deal.id == deal_id, Deal.deleted_at.is_(None)))).scalar_one_or_none()
    if not deal:
        raise HTTPException(404, "Deal not found")
    return await fetch_market_data(deal.city, deal.state, deal.property_type)


# ===== Cash Flow Projection =====

@router.get("/{deal_id}/cashflow")
async def cashflow_projection(deal_id: int, investment: Optional[float] = None, db: AsyncSession = Depends(get_db)):
    """Generate year-by-year cash flow projections."""
    result = await db.execute(select(Deal).where(Deal.id == deal_id))
    deal = result.scalar_one_or_none()
    if not deal:
        raise HTTPException(status_code=404, detail="Deal not found")

    if not deal.metrics:
        raise HTTPException(status_code=400, detail="No metrics extracted yet.")

    cashflow = project_cash_flows(analysis_for_deal(deal)["accepted_metrics"], investment_amount=investment)
    return cashflow


# ===== Waterfall Calculator =====

@router.get("/{deal_id}/waterfall")
async def waterfall_calculation(deal_id: int, investment: Optional[float] = None, db: AsyncSession = Depends(get_db)):
    """Calculate waterfall distribution from deal metrics."""
    result = await db.execute(select(Deal).where(Deal.id == deal_id))
    deal = result.scalar_one_or_none()
    if not deal:
        raise HTTPException(status_code=404, detail="Deal not found")

    if not deal.metrics:
        raise HTTPException(status_code=400, detail="No metrics extracted yet.")

    waterfall = waterfall_from_deal(analysis_for_deal(deal)["accepted_metrics"], investment_amount=investment)
    return waterfall


# ===== Comparison =====

async def _comparison_deals(data: CompareRequest, db: AsyncSession):
    if len(set(data.deal_ids)) != len(data.deal_ids) or len(data.deal_ids) < 2:
        raise HTTPException(status_code=400, detail="Select at least 2 different deals to compare")
    result = await db.execute(
        select(Deal).options(selectinload(Deal.developer), selectinload(Deal.documents))
        .where(Deal.id.in_(data.deal_ids), Deal.deleted_at.is_(None))
    )
    by_id = {deal.id: deal for deal in result.scalars().all()}
    if len(by_id) != len(data.deal_ids):
        raise HTTPException(status_code=404, detail="One or more selected deals are unavailable. Refresh the deal list.")
    return [by_id[deal_id] for deal_id in data.deal_ids]

@router.post("/compare")
async def compare_deals(data: CompareRequest, db: AsyncSession = Depends(get_db)):
    """Compare multiple deals side-by-side."""
    deals = await _comparison_deals(data, db)

    comparison = []
    for deal in deals:
        comparison.append(_deal_to_dict(deal, deal.developer.name if deal.developer else "", accepted_only=True))

    return {"deals": comparison}


def _write_comparison_sheet(sheet, headers, rows, widths):
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    sheet.append(headers)
    for cell in sheet[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill(start_color="1a1a2e", end_color="1a1a2e", fill_type="solid")
    for index, width in enumerate(widths, 1):
        sheet.column_dimensions[get_column_letter(index)].width = width
    for row_number, values in enumerate(rows, 2):
        for column, value in enumerate(values, 1):
            cell = sheet.cell(row_number, column, value)
            if isinstance(value, str):
                cell.data_type = "s"
                cell.alignment = Alignment(vertical="top", wrap_text=True)
    sheet.freeze_panes = "C2"
    sheet.auto_filter.ref = sheet.dimensions


@router.post("/compare/export")
async def export_comparison(data: CompareRequest, db: AsyncSession = Depends(get_db)):
    """Export deal comparison as Excel."""
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

    deals = await _comparison_deals(data, db)

    analyses = {deal.id: analysis_for_deal(deal) for deal in deals}
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Deal Comparison"

    # Styles
    header_font = Font(bold=True, color="FFFFFF", size=11)
    header_fill = PatternFill(start_color="1a1a2e", end_color="1a1a2e", fill_type="solid")
    section_font = Font(bold=True, size=11, color="4361ee")
    thin_border = Border(
        left=Side(style="thin"), right=Side(style="thin"),
        top=Side(style="thin"), bottom=Side(style="thin")
    )

    # Header row
    ws.cell(row=1, column=1, value="Metric").font = header_font
    ws["A1"].fill = header_fill
    ws["A1"].border = thin_border
    ws.column_dimensions["A"].width = 30

    for col_idx, deal in enumerate(deals, 2):
        cell = ws.cell(row=1, column=col_idx, value=deal.project_name)
        cell.data_type = "s"
        cell.font = header_font
        cell.fill = header_fill
        cell.border = thin_border
        cell.alignment = Alignment(horizontal="center")
        ws.column_dimensions[openpyxl.utils.get_column_letter(col_idx)].width = 36

    scores_by_deal = {deal.id: effective_scores(deal) for deal in deals}
    score_rows = {
        "Overall Score": "overall", "Returns Score": "returns", "Market Score": "market",
        "Structure Score": "structure", "Risk Score": "risk", "Financials Score": "financials",
        "Underwriting Score": "underwriting", "Sponsor Score": "sponsor",
    }

    def score_value(deal, category):
        scores = scores_by_deal[deal.id]
        return scores.get("overall") if category == "overall" else (scores.get(category) or {}).get("score")

    def score_basis(deal, category):
        basis = (scores_by_deal[deal.id]["comparison_basis"].get(category) or {}).get("inputs") or []
        return ", ".join(basis) or None

    # Define metric rows by section
    sections = [
        ("SCORES", [
            entry for label, category in score_rows.items() for entry in (
                (label, lambda d, category=category: score_value(d, category)),
                (f"{label} basis", lambda d, category=category: score_basis(d, category)),
            )
        ]),
        ("DEAL STRUCTURE", [
            ("Investment Class", lambda d: (analyses[d.id]["accepted_metrics"].get("deal_structure") or {}).get("investment_class")),
            ("Minimum Investment", lambda d: (analyses[d.id]["accepted_metrics"].get("deal_structure") or {}).get("minimum_investment")),
            ("Total Project Cost", lambda d: (analyses[d.id]["accepted_metrics"].get("deal_structure") or {}).get("total_project_cost")),
            ("Total Equity", lambda d: (analyses[d.id]["accepted_metrics"].get("deal_structure") or {}).get("total_equity_required")),
            ("Debt Amount", lambda d: (analyses[d.id]["accepted_metrics"].get("deal_structure") or {}).get("debt_amount")),
            ("Debt Basis", lambda d: (analyses[d.id].get("financing") or {}).get("debt_amount_label") if
             (analyses[d.id]["accepted_metrics"].get("deal_structure") or {}).get("debt_amount") is not None else None),
            ("LTV", lambda d: (analyses[d.id]["accepted_metrics"].get("deal_structure") or {}).get("ltv")),
            ("LTV Context", lambda d: operating_fact_context(analyses[d.id]["facts"].get("deal_structure.ltv")) or None),
            ("Loan-to-cost", lambda d: (analyses[d.id]["accepted_metrics"].get("deal_structure") or {}).get("loan_to_cost")),
            ("Loan-to-cost Context", lambda d: operating_fact_context(analyses[d.id]["facts"].get("deal_structure.loan_to_cost")) or None),
            ("Interest Rate", lambda d: (analyses[d.id]["accepted_metrics"].get("deal_structure") or {}).get("interest_rate")),
            ("Hold Period (yrs)", lambda d: (analyses[d.id]["accepted_metrics"].get("deal_structure") or {}).get("hold_period_years")),
            ("Preferred Return", lambda d: (analyses[d.id]["accepted_metrics"].get("deal_structure") or {}).get("preferred_return")),
            ("Preferred Return Context", lambda d: return_context(analyses[d.id]["facts"].get("deal_structure.preferred_return"))
             if (analyses[d.id]["accepted_metrics"].get("deal_structure") or {}).get("preferred_return") is not None else None),
            ("GP Co-Invest", lambda d: (analyses[d.id]["accepted_metrics"].get("deal_structure") or {}).get("gp_coinvest")),
            ("Asset Mgmt Fee", lambda d: (analyses[d.id]["accepted_metrics"].get("deal_structure") or {}).get("fees_asset_mgmt")),
        ]),
        ("TARGET RETURNS", [
            row
            for key, label in RETURN_LABELS
            for row in (
                (label, lambda d, key=key: analyses[d.id]["returns"].get(key)),
                (f"{label} Context", lambda d, key=key: return_context(accepted_return_fact(analyses[d.id], key))
                 if analyses[d.id]["returns"].get(key) is not None else None),
                (f"{label} Evidence", lambda d, key=key: return_evidence(accepted_return_fact(analyses[d.id], key))),
            )
        ] + [
            ("Projected Profit", lambda d: (analyses[d.id]["accepted_metrics"].get("target_returns") or {}).get("projected_profit")),
        ]),
        ("PROJECT DETAILS", [
            ("Unit Count", lambda d: (analyses[d.id]["accepted_metrics"].get("project_details") or {}).get("unit_count")),
            ("Total SqFt", lambda d: (analyses[d.id]["accepted_metrics"].get("project_details") or {}).get("total_sqft")),
            ("Price/Unit", lambda d: (analyses[d.id]["accepted_metrics"].get("project_details") or {}).get("price_per_unit")),
            ("Price/SqFt", lambda d: (analyses[d.id]["accepted_metrics"].get("project_details") or {}).get("price_per_sqft")),
            ("Construction Type", lambda d: (analyses[d.id]["accepted_metrics"].get("project_details") or {}).get("construction_type")),
            ("Entitlement Status", lambda d: (analyses[d.id]["accepted_metrics"].get("project_details") or {}).get("entitlement_status")),
        ]),
        ("CONSTRUCTION COSTS", [
            ("Total Project Cost", lambda d: (analyses[d.id]["accepted_metrics"].get("construction_costs") or {}).get("total_project_cost")),
            ("Total Cost/Unit", lambda d: (analyses[d.id]["accepted_metrics"].get("construction_costs") or {}).get("total_project_cost_per_unit")),
            ("Hard Costs Total", lambda d: (analyses[d.id]["accepted_metrics"].get("construction_costs") or {}).get("hard_costs_total")),
            ("Hard Costs/Unit", lambda d: (analyses[d.id]["accepted_metrics"].get("construction_costs") or {}).get("hard_costs_per_unit")),
            ("Hard Costs/SqFt", lambda d: (analyses[d.id]["accepted_metrics"].get("construction_costs") or {}).get("hard_costs_per_sqft")),
            ("Land Cost", lambda d: (analyses[d.id]["accepted_metrics"].get("construction_costs") or {}).get("land_cost_total")),
            ("Land Cost/Unit", lambda d: (analyses[d.id]["accepted_metrics"].get("construction_costs") or {}).get("land_cost_per_unit")),
            ("Soft Costs", lambda d: (analyses[d.id]["accepted_metrics"].get("construction_costs") or {}).get("soft_costs_total")),
            ("Contingency", lambda d: (analyses[d.id]["accepted_metrics"].get("construction_costs") or {}).get("contingency_total")),
            ("Contingency %", lambda d: (analyses[d.id]["accepted_metrics"].get("construction_costs") or {}).get("contingency_pct")),
            ("Financing Costs", lambda d: (analyses[d.id]["accepted_metrics"].get("construction_costs") or {}).get("financing_costs")),
            ("Preconstruction Soft Costs", lambda d: (analyses[d.id]["accepted_metrics"].get("construction_costs") or {}).get("preconstruction_soft_costs")),
            ("City and Agency Fees", lambda d: (analyses[d.id]["accepted_metrics"].get("construction_costs") or {}).get("city_agency_fees")),
            ("Offsite Development", lambda d: (analyses[d.id]["accepted_metrics"].get("construction_costs") or {}).get("offsite_development_costs")),
            ("Onsite Construction", lambda d: (analyses[d.id]["accepted_metrics"].get("construction_costs") or {}).get("onsite_construction_costs")),
            ("Construction and Lease-up Soft Costs", lambda d: (analyses[d.id]["accepted_metrics"].get("construction_costs") or {}).get("construction_leaseup_soft_costs")),
            ("Developer Fee", lambda d: (analyses[d.id]["accepted_metrics"].get("construction_costs") or {}).get("developer_fee_total")),
        ]),
        ("FINANCIAL PROJECTIONS", [
            ("Stabilized NOI", lambda d: (analyses[d.id]["accepted_metrics"].get("financial_projections") or {}).get("stabilized_noi")),
            ("Stabilized NOI Context", lambda d: operating_fact_context(analyses[d.id]["facts"].get("financial_projections.stabilized_noi")) or None),
            ("Untrended NOI", lambda d: (analyses[d.id]["accepted_metrics"].get("financial_projections") or {}).get("untrended_noi")),
            ("Untrended NOI Context", lambda d: operating_fact_context(analyses[d.id]["facts"].get("financial_projections.untrended_noi")) or None),
            ("Entry Cap Rate", lambda d: (analyses[d.id]["accepted_metrics"].get("financial_projections") or {}).get("entry_cap_rate")),
            ("Exit Cap Rate", lambda d: (analyses[d.id]["accepted_metrics"].get("financial_projections") or {}).get("exit_cap_rate")),
            ("Avg Rent/Unit", lambda d: (analyses[d.id]["accepted_metrics"].get("financial_projections") or {}).get("avg_rent_per_unit")),
            ("Rent Growth", lambda d: (analyses[d.id]["accepted_metrics"].get("financial_projections") or {}).get("rent_growth_assumption")),
            ("Occupancy", lambda d: (analyses[d.id]["accepted_metrics"].get("financial_projections") or {}).get("occupancy_assumption")),
        ]),
    ]

    row = 2
    green_fill = PatternFill(start_color="ecfdf5", end_color="ecfdf5", fill_type="solid")
    red_fill = PatternFill(start_color="fef2f2", end_color="fef2f2", fill_type="solid")

    for section_name, metrics_list in sections:
        # Section header
        cell = ws.cell(row=row, column=1, value=section_name)
        cell.font = section_font
        row += 1

        for metric_name, getter in metrics_list:
            ws.cell(row=row, column=1, value=metric_name).border = thin_border
            values = []
            for col_idx, deal in enumerate(deals, 2):
                val = getter(deal)
                cell = ws.cell(row=row, column=col_idx, value=val)
                cell.border = thin_border
                if isinstance(val, str):
                    cell.data_type = "s"
                    cell.alignment = Alignment(vertical="top", wrap_text=True)
                else:
                    cell.alignment = Alignment(horizontal="center")
                if isinstance(val, (int, float)):
                    values.append((col_idx, val))

            if section_name == "SCORES" and metric_name in score_rows and len(values) >= 2:
                category = score_rows[metric_name]
                signatures = [(scores_by_deal[deals[col - 2].id]["comparison_basis"].get(category) or {}).get("signature")
                              for col, _ in values]
                if signatures[0] and len(set(signatures)) == 1:
                    highest, lowest = max(value for _, value in values), min(value for _, value in values)
                    if highest != lowest:
                        for col, value in values:
                            if value == highest or value == lowest:
                                ws.cell(row=row, column=col).fill = green_fill if value == highest else red_fill
            row += 1
        row += 1  # Space between sections

    projections = []
    debt_measures = []
    sale_returns = []
    cash_flow_checks = []
    for deal in deals:
        analysis = analyses[deal.id]
        for fact in optional_sale_returns(analysis):
            sale_returns.append((deal.project_name, fact["label"], fact["value"], fact["identity"]["unit"],
                                 return_context(fact), return_evidence(fact)))
        schedule = analysis.get("return_schedule")
        if schedule:
            for projection in schedule["rows"]:
                projections.append((
                    deal.project_name, projection["year"], projection["cash_on_cash_pct"],
                    schedule_context(schedule), projection.get("note"), schedule.get("assumptions"),
                    schedule_source(schedule, projection),
                ))
        check = analysis.get("return_crosscheck")
        if check:
            context = cash_flow_check_context(check)
            periods = check["rows"] if check["status"] == "current" else [{}]
            for period in periods:
                evidence = [*(period.get("evidence") or []), *(period.get("event_evidence") or [])]
                cash_flow_checks.append((
                    deal.project_name, "Checked" if check["status"] == "current" else "Source changed",
                    context, check["annual_irr_pct"], check["cash_flow_multiple"], period.get("label"),
                    period.get("amount"), period.get("flow_scope_label"), period.get("date_label"),
                    check["calculation_basis"], source_reference(evidence or check["evidence"]),
                ))
        for measure in (analysis.get("financing") or {}).get("measures", []):
            if measure.get("state") == "checked":
                debt_measures.append((
                    deal.project_name, measure["label"], measure["amount"], measure["currency"], measure.get("note"),
                    source_reference(measure.get("evidence")),
                ))
    if sale_returns:
        _write_comparison_sheet(wb.create_sheet("Optional Sale Scenarios"), (
            "Deal", "Metric", "Value", "Unit", "Context", "Source",
        ), sale_returns, (28, 28, 17, 12, 72, 52))
    if projections:
        _write_comparison_sheet(wb.create_sheet("Return Projections"), (
            "Deal", "Year", "Annual cash-on-cash (%)", "Context", "Year note", "Assumptions", "Source",
        ), projections, (28, 9, 26, 56, 38, 56, 38))
    if debt_measures:
        _write_comparison_sheet(wb.create_sheet("Construction Financing"), (
            "Deal", "Metric", "Amount", "Currency", "Note", "Source",
        ), debt_measures, (28, 36, 17, 12, 52, 38))
    if cash_flow_checks:
        _write_comparison_sheet(wb.create_sheet("PDF Cash Flow Checks"), (
            "Deal", "Status", "Context", "Annual-period IRR (%)", "Cash-flow multiple", "Period", "Cash flow",
            "Flow context", "Source date", "Calculation", "Evidence",
        ), cash_flow_checks, (28, 18, 56, 24, 19, 13, 18, 32, 22, 62, 40))

    # Save to bytes
    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)

    return StreamingResponse(
        buffer,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=deal_comparison.xlsx"},
    )

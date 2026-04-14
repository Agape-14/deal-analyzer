import os
import uuid
import io
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from pydantic import BaseModel
from typing import Optional
from app.database import get_db
from app.models import Deal, DealDocument, Developer
from app.services.pdf_extractor import extract_text_from_pdf, extract_pdf
from app.services.deal_extractor import extract_metrics_from_docs
from app.services.deal_scorer import score_deal
from app.services.deal_validator import validate_deal_metrics
from app.services.deal_verifier import verify_deal_metrics, apply_corrections
from app.services.math_checker import run_math_checks
from app.services.market_data import fetch_market_data
from app.services.cashflow_projector import project_cash_flows
from app.services.waterfall_calculator import waterfall_from_deal

router = APIRouter()

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)


class DealCreate(BaseModel):
    developer_id: Optional[int] = None
    project_name: str
    location: Optional[str] = ""
    city: Optional[str] = ""
    state: Optional[str] = ""
    property_type: Optional[str] = "multifamily"
    status: Optional[str] = "reviewing"
    notes: Optional[str] = ""


class DealUpdate(BaseModel):
    developer_id: Optional[int] = None
    project_name: Optional[str] = None
    location: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    property_type: Optional[str] = None
    status: Optional[str] = None
    metrics: Optional[dict] = None
    scores: Optional[dict] = None
    notes: Optional[str] = None


class CompareRequest(BaseModel):
    deal_ids: list[int]


def _deal_to_dict(deal: Deal, developer_name: str = None) -> dict:
    metrics = deal.metrics or {}
    scores = deal.scores or {}
    target_returns = metrics.get("target_returns", {}) or {}
    deal_structure = metrics.get("deal_structure", {}) or {}

    return {
        "id": deal.id,
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
        "target_irr": target_returns.get("target_irr"),
        "target_equity_multiple": target_returns.get("target_equity_multiple"),
        "minimum_investment": deal_structure.get("minimum_investment"),
        "notes": deal.notes,
        "created_at": deal.created_at.isoformat() if deal.created_at else None,
    }


@router.get("")
async def list_deals(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Deal).options(selectinload(Deal.developer)).order_by(Deal.created_at.desc())
    )
    deals = result.scalars().all()
    return [
        _deal_to_dict(d, d.developer.name if d.developer else "")
        for d in deals
    ]


@router.post("")
async def create_deal(data: DealCreate, db: AsyncSession = Depends(get_db)):
    deal = Deal(**data.model_dump())
    db.add(deal)
    await db.commit()
    await db.refresh(deal)
    return {"id": deal.id, "project_name": deal.project_name, "message": "Deal created"}


@router.get("/{deal_id}")
async def get_deal(deal_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Deal)
        .options(selectinload(Deal.developer), selectinload(Deal.documents))
        .where(Deal.id == deal_id)
    )
    deal = result.scalar_one_or_none()
    if not deal:
        raise HTTPException(status_code=404, detail="Deal not found")

    data = _deal_to_dict(deal, deal.developer.name if deal.developer else "")
    data["documents"] = [
        {
            "id": doc.id,
            "filename": doc.filename,
            "doc_type": doc.doc_type,
            "page_count": doc.page_count,
            "upload_date": doc.upload_date.isoformat() if doc.upload_date else None,
            "has_text": bool(doc.extracted_text),
        }
        for doc in deal.documents
    ]
    return data


@router.put("/{deal_id}")
async def update_deal(deal_id: int, data: DealUpdate, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Deal).where(Deal.id == deal_id))
    deal = result.scalar_one_or_none()
    if not deal:
        raise HTTPException(status_code=404, detail="Deal not found")

    update_data = data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        if value is not None:
            setattr(deal, key, value)
    await db.commit()
    await db.refresh(deal)
    return {"message": "Deal updated", "id": deal.id}


@router.delete("/{deal_id}")
async def delete_deal(deal_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Deal).where(Deal.id == deal_id))
    deal = result.scalar_one_or_none()
    if not deal:
        raise HTTPException(status_code=404, detail="Deal not found")
    await db.delete(deal)
    await db.commit()
    return {"message": "Deal deleted"}


# ===== Documents =====

@router.get("/{deal_id}/documents")
async def list_documents(deal_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(DealDocument).where(DealDocument.deal_id == deal_id).order_by(DealDocument.upload_date.desc())
    )
    docs = result.scalars().all()
    return [
        {
            "id": doc.id,
            "filename": doc.filename,
            "doc_type": doc.doc_type,
            "page_count": doc.page_count,
            "upload_date": doc.upload_date.isoformat() if doc.upload_date else None,
            "has_text": bool(doc.extracted_text),
        }
        for doc in docs
    ]


@router.post("/{deal_id}/documents/upload")
async def upload_document(
    deal_id: int,
    file: UploadFile = File(...),
    doc_type: str = Form("other"),
    db: AsyncSession = Depends(get_db),
):
    # Verify deal exists
    result = await db.execute(select(Deal).where(Deal.id == deal_id))
    deal = result.scalar_one_or_none()
    if not deal:
        raise HTTPException(status_code=404, detail="Deal not found")

    # Save file
    ext = os.path.splitext(file.filename)[1] if file.filename else ".pdf"
    unique_name = f"{uuid.uuid4().hex}{ext}"
    file_path = os.path.join(UPLOAD_DIR, unique_name)

    content = await file.read()
    with open(file_path, "wb") as f:
        f.write(content)

    # Extract text (+ OCR fallback + tables + images)
    extraction: dict = {}
    try:
        result_x = extract_pdf(file_path)
        extracted_text = result_x.text
        page_count = result_x.page_count
        extraction = {
            "ocr_pages": result_x.ocr_page_count,
            "tables": len(result_x.tables),
            "images": len(result_x.images),
        }
    except Exception as e:
        extracted_text = f"Error extracting text: {str(e)}"
        page_count = 0
        extraction = {"ocr_pages": 0, "tables": 0, "images": 0, "error": str(e)}

    doc = DealDocument(
        deal_id=deal_id,
        filename=file.filename or unique_name,
        file_path=file_path,
        doc_type=doc_type,
        extracted_text=extracted_text,
        page_count=page_count,
    )
    db.add(doc)
    await db.commit()
    await db.refresh(doc)

    return {
        "id": doc.id,
        "filename": doc.filename,
        "doc_type": doc.doc_type,
        "page_count": page_count,
        "text_length": len(extracted_text),
        "extraction": extraction,
        "message": "Document uploaded and text extracted",
    }


@router.post("/documents/{doc_id}/reprocess")
async def reprocess_document(doc_id: int, db: AsyncSession = Depends(get_db)):
    """Re-run text extraction on an existing document.

    Useful when the initial extraction produced poor results (e.g. scanned PDF
    that needed OCR but OCR wasn't installed yet) or when the extractor has
    been improved."""
    result = await db.execute(select(DealDocument).where(DealDocument.id == doc_id))
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    if not doc.file_path or not os.path.exists(doc.file_path):
        raise HTTPException(
            status_code=410,
            detail="Original file is no longer available on disk",
        )

    try:
        r = extract_pdf(doc.file_path)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Reprocess failed: {e}")

    old_len = len(doc.extracted_text or "")
    doc.extracted_text = r.text
    doc.page_count = r.page_count
    await db.commit()

    return {
        "id": doc.id,
        "filename": doc.filename,
        "page_count": r.page_count,
        "ocr_pages": r.ocr_page_count,
        "tables": len(r.tables),
        "images": len(r.images),
        "text_length_before": old_len,
        "text_length_after": len(r.text),
        "delta": len(r.text) - old_len,
        "message": "Document reprocessed",
    }


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


# ===== AI Features =====

@router.post("/{deal_id}/extract")
async def extract_deal_metrics(deal_id: int, db: AsyncSession = Depends(get_db)):
    """AI-extract metrics from all uploaded documents."""
    result = await db.execute(
        select(Deal).options(selectinload(Deal.documents)).where(Deal.id == deal_id)
    )
    deal = result.scalar_one_or_none()
    if not deal:
        raise HTTPException(status_code=404, detail="Deal not found")

    if not deal.documents:
        raise HTTPException(status_code=400, detail="No documents uploaded yet")

    doc_texts = [
        {
            "filename": doc.filename,
            "doc_type": doc.doc_type,
            "text": doc.extracted_text or "",
        }
        for doc in deal.documents
        if doc.extracted_text
    ]

    # Collect PDF file paths for vision-based extraction
    doc_paths = [
        doc.file_path
        for doc in deal.documents
        if doc.file_path and doc.file_path.endswith(".pdf")
    ]

    if not doc_texts and not doc_paths:
        raise HTTPException(status_code=400, detail="No extracted text or PDF files available")

    try:
        metrics = await extract_metrics_from_docs(doc_texts, doc_paths=doc_paths)
    except Exception as e:
        msg = str(e)
        status = 503 if "ANTHROPIC_API_KEY" in msg else 500
        raise HTTPException(status_code=status, detail=f"AI extraction failed: {msg}")

    # Run validation checks
    validation_flags = validate_deal_metrics(metrics)
    metrics["validation_flags"] = validation_flags

    deal.metrics = metrics

    # Auto-populate city/state from extracted data if empty
    ml = metrics.get("market_location", {}) or {}
    if not deal.city and ml.get("city"):
        deal.city = ml["city"]
    if not deal.state and ml.get("state"):
        deal.state = ml["state"]

    await db.commit()
    return {"message": "Metrics extracted", "metrics": metrics, "validation_flags": validation_flags}


@router.post("/{deal_id}/score")
async def score_deal_endpoint(deal_id: int, db: AsyncSession = Depends(get_db)):
    """Score the deal based on extracted metrics."""
    result = await db.execute(select(Deal).where(Deal.id == deal_id))
    deal = result.scalar_one_or_none()
    if not deal:
        raise HTTPException(status_code=404, detail="Deal not found")

    if not deal.metrics:
        raise HTTPException(status_code=400, detail="No metrics extracted yet. Run extraction first.")

    scores = score_deal(deal.metrics)
    deal.scores = scores
    await db.commit()
    return {"message": "Deal scored", "scores": scores}


@router.get("/{deal_id}/validate")
async def validate_deal(deal_id: int, db: AsyncSession = Depends(get_db)):
    """Run validation checks on current metrics and return flags."""
    result = await db.execute(select(Deal).where(Deal.id == deal_id))
    deal = result.scalar_one_or_none()
    if not deal:
        raise HTTPException(status_code=404, detail="Deal not found")

    if not deal.metrics:
        raise HTTPException(status_code=400, detail="No metrics extracted yet. Run extraction first.")

    flags = validate_deal_metrics(deal.metrics)

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


@router.post("/{deal_id}/verify")
async def verify_deal_endpoint(deal_id: int, auto_correct: bool = True, db: AsyncSession = Depends(get_db)):
    """Second-pass AI verification of extracted metrics against source documents.
    
    Sends extracted metrics + original PDF page images to AI for forensic audit.
    Checks every value, flags errors, finds missing data, verifies calculations.
    
    Args:
        auto_correct: If True, automatically applies corrections to metrics
    """
    result = await db.execute(
        select(Deal).options(selectinload(Deal.documents)).where(Deal.id == deal_id)
    )
    deal = result.scalar_one_or_none()
    if not deal:
        raise HTTPException(status_code=404, detail="Deal not found")

    if not deal.metrics:
        raise HTTPException(status_code=400, detail="No metrics extracted yet. Run extraction first.")

    try:
        verification = await verify_deal_metrics(deal, db)
    except Exception as e:
        msg = str(e)
        status = 503 if "ANTHROPIC_API_KEY" in msg else 500
        raise HTTPException(status_code=status, detail=f"Verification failed: {msg}")

    changes = []
    if auto_correct:
        metrics = deal.metrics.copy() if deal.metrics else {}
        metrics, changes = apply_corrections(metrics, verification)
        
        # Re-run validation after corrections
        from app.services.deal_validator import validate_deal_metrics as validate
        flags = validate(metrics)
        metrics["validation_flags"] = flags
        
        deal.metrics = metrics
        await db.commit()

    # Run math checks on the (possibly corrected) metrics
    math_results = run_math_checks(deal.metrics or {})
    math_summary = {
        'pass': len([c for c in math_results if c['status'] == 'pass']),
        'fail': len([c for c in math_results if c['status'] == 'fail']),
        'warn': len([c for c in math_results if c['status'] == 'warn']),
        'info': len([c for c in math_results if c['status'] == 'info']),
    }

    return {
        "message": "Verification complete",
        "verification": verification,
        "corrections_applied": changes,
        "auto_corrected": auto_correct,
        "math_checks": math_results,
        "math_summary": math_summary,
    }


@router.get("/{deal_id}/math-check")
async def math_check_deal(deal_id: int, db: AsyncSession = Depends(get_db)):
    """Run deterministic math verification — zero AI, pure arithmetic.
    
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


# ===== Market Research =====

@router.post("/{deal_id}/market-research")
async def market_research(deal_id: int, db: AsyncSession = Depends(get_db)):
    """Fetch real market data for the deal's city/state via Brave Search + Claude AI."""
    result = await db.execute(select(Deal).where(Deal.id == deal_id))
    deal = result.scalar_one_or_none()
    if not deal:
        raise HTTPException(status_code=404, detail="Deal not found")

    city = deal.city or (deal.metrics or {}).get("market_location", {}).get("city", "")
    state = deal.state or (deal.metrics or {}).get("market_location", {}).get("state", "")

    if not city or not state:
        raise HTTPException(status_code=400, detail="City and state are required. Update the deal first.")

    try:
        market_data = await fetch_market_data(city, state)
    except Exception as e:
        msg = str(e)
        status = 503 if ("ANTHROPIC_API_KEY" in msg or "BRAVE_API_KEY" in msg) else 500
        raise HTTPException(status_code=status, detail=f"Market research failed: {msg}")

    # Save to deal metrics
    metrics = deal.metrics.copy() if deal.metrics else {}
    metrics["market_research"] = market_data
    deal.metrics = metrics
    await db.commit()

    return {"message": "Market research complete", "market_research": market_data}


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

    cashflow = project_cash_flows(deal.metrics, investment_amount=investment)
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

    waterfall = waterfall_from_deal(deal.metrics, investment_amount=investment)
    return waterfall


# ===== Comparison =====

@router.post("/compare")
async def compare_deals(data: CompareRequest, db: AsyncSession = Depends(get_db)):
    """Compare multiple deals side-by-side."""
    if len(data.deal_ids) < 2:
        raise HTTPException(status_code=400, detail="Select at least 2 deals to compare")

    result = await db.execute(
        select(Deal)
        .options(selectinload(Deal.developer))
        .where(Deal.id.in_(data.deal_ids))
    )
    deals = result.scalars().all()

    comparison = []
    for deal in deals:
        comparison.append(_deal_to_dict(deal, deal.developer.name if deal.developer else ""))

    return {"deals": comparison}


@router.post("/compare/export")
async def export_comparison(data: CompareRequest, db: AsyncSession = Depends(get_db)):
    """Export deal comparison as Excel."""
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

    if len(data.deal_ids) < 2:
        raise HTTPException(status_code=400, detail="Select at least 2 deals to compare")

    result = await db.execute(
        select(Deal)
        .options(selectinload(Deal.developer))
        .where(Deal.id.in_(data.deal_ids))
    )
    deals = result.scalars().all()

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
        cell.font = header_font
        cell.fill = header_fill
        cell.border = thin_border
        cell.alignment = Alignment(horizontal="center")
        ws.column_dimensions[openpyxl.utils.get_column_letter(col_idx)].width = 22

    # Define metric rows by section
    sections = [
        ("SCORES", [
            ("Overall Score", lambda d: (d.scores or {}).get("overall")),
            ("Returns Score", lambda d: ((d.scores or {}).get("returns") or {}).get("score")),
            ("Market Score", lambda d: ((d.scores or {}).get("market") or {}).get("score")),
            ("Structure Score", lambda d: ((d.scores or {}).get("structure") or {}).get("score")),
            ("Risk Score", lambda d: ((d.scores or {}).get("risk") or {}).get("score")),
            ("Financials Score", lambda d: ((d.scores or {}).get("financials") or {}).get("score")),
        ]),
        ("DEAL STRUCTURE", [
            ("Investment Class", lambda d: ((d.metrics or {}).get("deal_structure") or {}).get("investment_class")),
            ("Minimum Investment", lambda d: ((d.metrics or {}).get("deal_structure") or {}).get("minimum_investment")),
            ("Total Project Cost", lambda d: ((d.metrics or {}).get("deal_structure") or {}).get("total_project_cost")),
            ("Total Equity", lambda d: ((d.metrics or {}).get("deal_structure") or {}).get("total_equity_required")),
            ("Debt Amount", lambda d: ((d.metrics or {}).get("deal_structure") or {}).get("debt_amount")),
            ("LTV", lambda d: ((d.metrics or {}).get("deal_structure") or {}).get("ltv")),
            ("Interest Rate", lambda d: ((d.metrics or {}).get("deal_structure") or {}).get("interest_rate")),
            ("Hold Period (yrs)", lambda d: ((d.metrics or {}).get("deal_structure") or {}).get("hold_period_years")),
            ("Preferred Return", lambda d: ((d.metrics or {}).get("deal_structure") or {}).get("preferred_return")),
            ("GP Co-Invest", lambda d: ((d.metrics or {}).get("deal_structure") or {}).get("gp_coinvest")),
            ("Asset Mgmt Fee", lambda d: ((d.metrics or {}).get("deal_structure") or {}).get("fees_asset_mgmt")),
        ]),
        ("TARGET RETURNS", [
            ("Target IRR", lambda d: ((d.metrics or {}).get("target_returns") or {}).get("target_irr")),
            ("Equity Multiple", lambda d: ((d.metrics or {}).get("target_returns") or {}).get("target_equity_multiple")),
            ("Cash-on-Cash", lambda d: ((d.metrics or {}).get("target_returns") or {}).get("target_cash_on_cash")),
            ("Avg Annual Return", lambda d: ((d.metrics or {}).get("target_returns") or {}).get("target_avg_annual_return")),
            ("Projected Profit", lambda d: ((d.metrics or {}).get("target_returns") or {}).get("projected_profit")),
        ]),
        ("PROJECT DETAILS", [
            ("Unit Count", lambda d: ((d.metrics or {}).get("project_details") or {}).get("unit_count")),
            ("Total SqFt", lambda d: ((d.metrics or {}).get("project_details") or {}).get("total_sqft")),
            ("Price/Unit", lambda d: ((d.metrics or {}).get("project_details") or {}).get("price_per_unit")),
            ("Price/SqFt", lambda d: ((d.metrics or {}).get("project_details") or {}).get("price_per_sqft")),
            ("Construction Type", lambda d: ((d.metrics or {}).get("project_details") or {}).get("construction_type")),
            ("Entitlement Status", lambda d: ((d.metrics or {}).get("project_details") or {}).get("entitlement_status")),
        ]),
        ("FINANCIAL PROJECTIONS", [
            ("Stabilized NOI", lambda d: ((d.metrics or {}).get("financial_projections") or {}).get("stabilized_noi")),
            ("Entry Cap Rate", lambda d: ((d.metrics or {}).get("financial_projections") or {}).get("entry_cap_rate")),
            ("Exit Cap Rate", lambda d: ((d.metrics or {}).get("financial_projections") or {}).get("exit_cap_rate")),
            ("Avg Rent/Unit", lambda d: ((d.metrics or {}).get("financial_projections") or {}).get("avg_rent_per_unit")),
            ("Rent Growth", lambda d: ((d.metrics or {}).get("financial_projections") or {}).get("rent_growth_assumption")),
            ("Occupancy", lambda d: ((d.metrics or {}).get("financial_projections") or {}).get("occupancy_assumption")),
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
                cell.alignment = Alignment(horizontal="center")
                if isinstance(val, (int, float)):
                    values.append((col_idx, val))

            # Highlight best/worst if numeric
            if len(values) >= 2:
                best_col = max(values, key=lambda x: x[1])[0]
                worst_col = min(values, key=lambda x: x[1])[0]
                if best_col != worst_col:
                    ws.cell(row=row, column=best_col).fill = green_fill
                    ws.cell(row=row, column=worst_col).fill = red_fill
            row += 1
        row += 1  # Space between sections

    # Save to bytes
    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)

    return StreamingResponse(
        buffer,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=deal_comparison.xlsx"},
    )

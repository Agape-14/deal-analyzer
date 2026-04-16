import os
import uuid
import io
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Response
from fastapi.responses import StreamingResponse
from app.rate_limit import limit
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from pydantic import BaseModel, Field, field_validator
from typing import Optional
from app.database import get_db
from app.models import Deal, DealDocument
from app.services.pdf_extractor import extract_pdf
from app.services.deal_extractor import extract_metrics_from_docs
from app.services.deal_scorer import score_deal
from app.services.deal_validator import validate_deal_metrics
from app.services.deal_verifier import verify_deal_metrics, apply_corrections
from app.services.math_checker import run_math_checks
from app.services.market_data import fetch_market_data
from app.services.cashflow_projector import project_cash_flows
from app.services.waterfall_calculator import waterfall_from_deal
from app.services.data_integrity import (
    smart_merge,
    detect_conflicts,
    conflicts_to_flags,
    staleness_flags,
    quality_summary,
    stamp_verification,
    set_lock,
    mark_manual_edit,
    now_iso,
)
from app.services.location_intelligence import (
    build_location_bundle,
    geocode as geocode_address,
)
from app.services import notifications as notif_svc

router = APIRouter()

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# UPLOADS_DIR override lets Railway mount a Volume at /data/uploads so files
# survive redeploys. Falls back to DB_DIR/uploads (same volume as SQLite when
# DB_DIR is set), else repo-root/uploads for local dev.
UPLOAD_DIR = os.environ.get(
    "UPLOADS_DIR",
    os.path.join(os.environ.get("DB_DIR", BASE_DIR), "uploads"),
)
os.makedirs(UPLOAD_DIR, exist_ok=True)


# Allowed status values for a Deal — closes the "any string accepted" hole.
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
    `?trash=true` is passed — handy for a future 'Trash' view."""
    q = select(Deal).options(selectinload(Deal.developer)).order_by(Deal.created_at.desc())
    if trash:
        q = q.where(Deal.deleted_at.is_not(None))
    else:
        q = q.where(Deal.deleted_at.is_(None))
    result = await db.execute(q)
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


@router.get("/pipeline/summary")
async def pipeline_summary_endpoint(
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    """Dashboard widgets: total deals, velocity (6mo), win rate (12mo),
    aging deals, capital deployed, average analyst score. Derived from
    the live Deal table on every call — no materialized view yet.

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
    data["documents"] = [
        {
            "id": doc.id,
            "filename": doc.filename,
            "doc_type": doc.doc_type,
            "page_count": doc.page_count,
            "upload_date": doc.upload_date.isoformat() if doc.upload_date else None,
            "has_text": bool(doc.extracted_text),
            "extraction_quality": {
                "quality_score": (doc.extraction_quality or {}).get("quality_score"),
                "ocr_pages": (doc.extraction_quality or {}).get("ocr_pages", 0),
                "empty_pages": (doc.extraction_quality or {}).get("empty_pages", []),
            }
            if doc.extraction_quality
            else None,
        }
        for doc in deal.documents
    ]
    # Quality summary of the metrics (counts of verified / extracted / conflicting / locked)
    if deal.metrics:
        data["quality"] = quality_summary(deal.metrics)
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
    already in the trash — prevents accidental irreversible removal."""
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


# Size + type guards for uploaded documents. Anything over 50 MB is almost
# certainly not a single OM — reject before we spend tokens on it. Any file
# that's not a PDF won't parse with our pipeline; fail fast with a clear
# message rather than saving garbage to disk.
MAX_UPLOAD_BYTES = 50 * 1024 * 1024          # 50 MB
ALLOWED_MIMETYPES = {"application/pdf", "application/x-pdf"}
ALLOWED_EXTS = {".pdf"}


@router.post("/{deal_id}/documents/upload", dependencies=[Depends(limit("upload"))])
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

    # MIME / extension guard — we only parse PDF today.
    ext = os.path.splitext(file.filename or "")[1].lower()
    ctype = (file.content_type or "").lower()
    if ext not in ALLOWED_EXTS and ctype not in ALLOWED_MIMETYPES:
        raise HTTPException(
            status_code=415,
            detail=f"Only PDF uploads are supported (got {ctype or ext or 'unknown type'}).",
        )

    # Size guard — read in chunks so a 2GB PDF doesn't balloon memory.
    # FastAPI's UploadFile exposes a SpooledTemporaryFile; we can stream
    # it to disk while counting bytes.
    unique_name = f"{uuid.uuid4().hex}{ext or '.pdf'}"
    file_path = os.path.join(UPLOAD_DIR, unique_name)
    total = 0
    with open(file_path, "wb") as f:
        while True:
            chunk = await file.read(1 * 1024 * 1024)  # 1 MB chunks
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_UPLOAD_BYTES:
                f.close()
                try:
                    os.remove(file_path)
                except OSError:
                    pass
                raise HTTPException(
                    status_code=413,
                    detail=f"File exceeds {MAX_UPLOAD_BYTES // (1024 * 1024)}MB upload limit.",
                )
            f.write(chunk)

    # Extract text (+ OCR fallback + tables + images)
    extraction: dict = {}
    quality: dict = {}
    try:
        result_x = extract_pdf(file_path)
        extracted_text = result_x.text
        page_count = result_x.page_count
        empty_pages = [d["page"] for d in result_x.page_diagnostics if d["source"] == "empty"]
        extraction = {
            "ocr_pages": result_x.ocr_page_count,
            "tables": len(result_x.tables),
            "images": len(result_x.images),
            "quality_score": result_x.quality_score,
            "empty_pages": empty_pages,
        }
        quality = {
            "quality_score": result_x.quality_score,
            "ocr_pages": result_x.ocr_page_count,
            "empty_pages": empty_pages,
            "page_diagnostics": result_x.page_diagnostics,
        }
    except Exception as e:
        extracted_text = f"Error extracting text: {str(e)}"
        page_count = 0
        extraction = {"ocr_pages": 0, "tables": 0, "images": 0, "error": str(e)}
        quality = {"error": str(e)}

    doc = DealDocument(
        deal_id=deal_id,
        filename=file.filename or unique_name,
        file_path=file_path,
        doc_type=doc_type,
        extracted_text=extracted_text,
        page_count=page_count,
        extraction_quality=quality,
    )
    db.add(doc)
    await db.commit()
    await db.refresh(doc)

    # Notification: upload complete (low-noise, but users expect feedback
    # for long uploads).
    q_score = quality.get("quality_score") if isinstance(quality, dict) else None
    body_bits = [f"{page_count} page{'s' if page_count != 1 else ''}"]
    if q_score is not None:
        body_bits.append(f"extraction quality {q_score}%")
    empty = (quality or {}).get("empty_pages") or []
    kind = "warning" if empty else "info"
    if empty:
        body_bits.append(f"{len(empty)} page{'s' if len(empty) != 1 else ''} failed OCR")
    await notif_svc.emit(
        db,
        kind=kind,
        title=f"Uploaded {doc.filename}",
        body=" · ".join(body_bits),
        href=f"/deals/{deal_id}?tab=documents",
        payload={"deal_id": deal_id, "doc_id": doc.id},
    )
    await db.commit()

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
    doc.extraction_quality = {
        "quality_score": r.quality_score,
        "ocr_pages": r.ocr_page_count,
        "empty_pages": [d["page"] for d in r.page_diagnostics if d["source"] == "empty"],
        "page_diagnostics": r.page_diagnostics,
    }
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


@router.get("/documents/{doc_id}/file")
async def get_document_file(doc_id: int, db: AsyncSession = Depends(get_db)):
    """Stream the original uploaded PDF so the frontend can render it
    inline via the browser's native viewer. Served with the original
    filename as a Content-Disposition suggestion for saves."""
    from fastapi.responses import FileResponse

    result = await db.execute(select(DealDocument).where(DealDocument.id == doc_id))
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    if not doc.file_path or not os.path.exists(doc.file_path):
        raise HTTPException(
            status_code=410,
            detail="Original file is no longer available on disk.",
        )
    # Path-traversal guard: even though file_path is only writable by our
    # own upload handler (which uses a uuid filename under UPLOAD_DIR), a
    # compromised DB value must not let us serve /etc/passwd or similar.
    real = os.path.realpath(doc.file_path)
    upload_root = os.path.realpath(UPLOAD_DIR)
    if not real.startswith(upload_root + os.sep):
        raise HTTPException(status_code=404, detail="Document not found")
    return FileResponse(
        real,
        media_type="application/pdf",
        # `inline` (not attachment) so the browser renders it; safer for
        # our same-origin UI than forcing a download.
        headers={
            "Content-Disposition": f'inline; filename="{doc.filename or "document.pdf"}"',
            "Cache-Control": "private, max-age=60",
        },
    )


# ===== AI Features =====

@router.post("/{deal_id}/extract", dependencies=[Depends(limit("ai"))])
async def extract_deal_metrics(deal_id: int, db: AsyncSession = Depends(get_db)):
    """AI-extract metrics from all uploaded documents.

    Data-integrity guarantees (see app/services/data_integrity.py):
      1. Smart-merge — a new extraction never overwrites an existing value
         with null. Re-running extraction is always safe.
      2. Provenance — every field records which document it came from,
         when, with what status.
      3. Conflict detection — when multiple docs are uploaded, we run
         extraction per-doc first, compare values, and emit red flags for
         every field where two docs disagree.
      4. Locks — fields the user has manually edited are never overwritten
         by re-extraction.
    """
    result = await db.execute(
        select(Deal).options(selectinload(Deal.documents)).where(Deal.id == deal_id)
    )
    deal = result.scalar_one_or_none()
    if not deal:
        raise HTTPException(status_code=404, detail="Deal not found")

    if not deal.documents:
        raise HTTPException(status_code=400, detail="No documents uploaded yet")

    usable_docs = [d for d in deal.documents if (d.extracted_text or "")]
    usable_pdfs = [
        d for d in deal.documents if d.file_path and d.file_path.endswith(".pdf")
    ]
    if not usable_docs and not usable_pdfs:
        raise HTTPException(
            status_code=400, detail="No extracted text or PDF files available"
        )

    # Per-document extraction — enables conflict detection. We still do a
    # whole-set extraction (the union) so rows that only appear in one doc
    # don't get lost when there are more than 2 docs.
    per_doc_results: list[tuple[int, str, dict]] = []
    try:
        if len(deal.documents) > 1:
            for doc in deal.documents:
                text = doc.extracted_text or ""
                path = (
                    doc.file_path
                    if doc.file_path and doc.file_path.endswith(".pdf")
                    else None
                )
                if not text and not path:
                    continue
                one_doc_text = (
                    [
                        {
                            "filename": doc.filename,
                            "doc_type": doc.doc_type,
                            "text": text,
                        }
                    ]
                    if text
                    else []
                )
                one_doc_path = [path] if path else []
                try:
                    mx = await extract_metrics_from_docs(
                        one_doc_text, doc_paths=one_doc_path
                    )
                    per_doc_results.append((doc.id, doc.filename, mx))
                except Exception:
                    # A single doc failing shouldn't block the batch; it
                    # just won't participate in conflict detection.
                    pass

        # Union extraction over all docs at once — this is what we
        # actually merge into deal.metrics. The per-doc pass above is
        # only used to compute the conflict map.
        doc_texts = [
            {
                "filename": d.filename,
                "doc_type": d.doc_type,
                "text": d.extracted_text or "",
            }
            for d in usable_docs
        ]
        doc_paths = [d.file_path for d in usable_pdfs]
        incoming_metrics = await extract_metrics_from_docs(doc_texts, doc_paths=doc_paths)
    except Exception as e:
        msg = str(e)
        status = 503 if "ANTHROPIC_API_KEY" in msg else 500
        raise HTTPException(status_code=status, detail=f"AI extraction failed: {msg}")

    # Smart-merge into existing metrics (preserves non-null prior values,
    # honors locks, records provenance on every updated field).
    primary_doc = usable_docs[0] if len(usable_docs) == 1 else None
    merged, changes = smart_merge(
        deal.metrics,
        incoming_metrics,
        source_doc_id=primary_doc.id if primary_doc else None,
        source_doc_name=primary_doc.filename if primary_doc else "multiple documents",
    )

    # Conflict detection across documents
    conflicts = detect_conflicts(per_doc_results) if len(per_doc_results) >= 2 else {}
    if conflicts:
        # Annotate provenance with the conflict so the UI can render an
        # inline picker next to each conflicting metric.
        prov = dict(merged.get("_provenance") or {})
        for path, entries in conflicts.items():
            existing_prov = prov.get(path, {})
            existing_prov["conflict"] = entries
            prov[path] = existing_prov
        merged["_provenance"] = prov

    # Keep a short extraction-history breadcrumb trail
    history = list(merged.get("_extraction_history") or [])
    history.append(
        {
            "at": now_iso(),
            "changes": changes[:50],  # cap
            "doc_count": len(deal.documents),
            "conflicts": list(conflicts.keys()),
        }
    )
    merged["_extraction_history"] = history[-20:]  # keep last 20

    # Run validation (includes existing rules + our new conflict + stale flags)
    validation_flags = validate_deal_metrics(merged, deal.property_type)
    validation_flags.extend(conflicts_to_flags(conflicts))
    validation_flags.extend(staleness_flags(merged, deal.documents))
    merged["validation_flags"] = validation_flags

    deal.metrics = merged

    # Auto-populate city/state from extracted data if empty
    ml = merged.get("market_location", {}) or {}
    if not deal.city and ml.get("city"):
        deal.city = ml["city"]
    if not deal.state and ml.get("state"):
        deal.state = ml["state"]

    # Auto-score after a successful extraction. Users were having to
    # click Re-extract and then separately hit Re-score to get a
    # number on the header; for a brand-new deal with no prior scores
    # that just looks broken. Scoring is cheap (pure-python, no AI
    # call) so running it inline is safe.
    try:
        deal.scores = score_deal(merged)
    except Exception:
        # If scoring blows up we still want the extraction to land.
        # The Re-score button remains as a manual retry.
        pass

    # Notification: extraction complete. Conflicts = red, otherwise info.
    reds = [f for f in validation_flags if f.get("severity") == "red"]
    n_conflicts = len(conflicts)
    body_parts = [f"{len(changes)} field{'s' if len(changes) != 1 else ''} updated"]
    if n_conflicts:
        body_parts.append(f"{n_conflicts} cross-document conflict{'s' if n_conflicts != 1 else ''}")
    if reds:
        body_parts.append(f"{len(reds)} red flag{'s' if len(reds) != 1 else ''}")
    await notif_svc.emit(
        db,
        kind="error" if n_conflicts or reds else "success",
        title=f"Metrics extracted for {deal.project_name}",
        body=" · ".join(body_parts),
        href=f"/deals/{deal.id}?tab=overview",
        payload={
            "deal_id": deal.id,
            "changes": len(changes),
            "conflicts": n_conflicts,
            "red_flags": len(reds),
        },
    )

    await db.commit()
    return {
        "message": "Metrics extracted",
        "metrics": merged,
        "validation_flags": validation_flags,
        "changes": changes,
        "conflicts": conflicts,
        "quality": quality_summary(merged),
    }


@router.post("/{deal_id}/score", dependencies=[Depends(limit("write"))])
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


@router.post("/{deal_id}/verify", dependencies=[Depends(limit("ai"))])
async def verify_deal_endpoint(deal_id: int, auto_correct: bool = True, db: AsyncSession = Depends(get_db)):
    """Second-pass AI verification — runs as a background task.

    Returns 202 immediately and runs the (slow) verification in the
    background. The UI polls for completion via the quality endpoint.
    This avoids the Railway edge-proxy 60s timeout killing the request
    mid-verify and losing 4 of 5 section chunks.
    """
    result = await db.execute(
        select(Deal).options(selectinload(Deal.documents)).where(Deal.id == deal_id)
    )
    deal = result.scalar_one_or_none()
    if not deal:
        raise HTTPException(status_code=404, detail="Deal not found")

    if not deal.metrics:
        raise HTTPException(status_code=400, detail="No metrics extracted yet. Run extraction first.")

    # Launch verification as a fire-and-forget background coroutine.
    # FastAPI's BackgroundTasks run AFTER the response is sent, which
    # is perfect here — the client gets 202 immediately, and the 5
    # section-chunked verify calls have all the time they need
    # without worrying about proxy timeouts.
    import asyncio
    asyncio.ensure_future(_run_verify_background(deal_id, auto_correct))

    return {
        "message": "Verification started — this runs in the background (~2-5 min). "
                   "Refresh the page to see updated verification status.",
        "status": "started",
        "deal_id": deal_id,
    }


async def _run_verify_background(deal_id: int, auto_correct: bool):
    """Background verify task. Runs independently of the HTTP request lifecycle.

    Uses its own DB session (can't share the request-scoped one) and
    commits results directly. Any exception is logged to operation_log
    + stderr but never propagates to a client (there's no client).
    """
    import logging
    logger = logging.getLogger("kenyon.verify_bg")

    from app.database import async_session
    async with async_session() as db:
        try:
            result = await db.execute(
                select(Deal).options(selectinload(Deal.documents)).where(Deal.id == deal_id)
            )
            deal = result.scalar_one_or_none()
            if not deal or not deal.metrics:
                logger.warning("verify_bg: deal %s not found or no metrics", deal_id)
                return

            verification = await verify_deal_metrics(deal, db)

            metrics = deal.metrics.copy() if deal.metrics else {}
            changes: list[str] = []
            if auto_correct:
                metrics, changes = apply_corrections(metrics, verification)

            metrics = stamp_verification(metrics, verification)

            flags = validate_deal_metrics(metrics, deal.property_type)
            flags.extend(staleness_flags(metrics, deal.documents))
            metrics["validation_flags"] = flags

            deal.metrics = metrics
            await db.commit()

            # Re-run math checks
            math_results = run_math_checks(deal.metrics or {})

            # Notification
            vsummary = (verification or {}).get("summary") or {}
            confidence = vsummary.get("confidence_score")
            totals = {}
            for row in (verification or {}).get("audit_results", []) or []:
                st = str(row.get("status") or "").lower()
                totals[st] = totals.get(st, 0) + 1
            wrong = totals.get("wrong", 0)
            missing = totals.get("missing", 0)
            body_parts = []
            if confidence is not None:
                body_parts.append(f"{confidence}% confidence")
            if wrong:
                body_parts.append(f"{wrong} corrected")
            if missing:
                body_parts.append(f"{missing} missing")
            if changes:
                body_parts.append(f"{len(changes)} auto-applied")
            await notif_svc.emit(
                db,
                kind="warning" if wrong or missing else "success",
                title=f"Verification complete — {deal.project_name}",
                body=" · ".join(body_parts) if body_parts else "All extracted values match the source docs.",
                href=f"/deals/{deal.id}?tab=overview",
                payload={"deal_id": deal.id, **totals, "confidence": confidence},
            )
            await db.commit()

            logger.info(
                "verify_bg: deal %s complete — %d confirmed, %d wrong, %d unverifiable",
                deal_id, totals.get("confirmed", 0), wrong, totals.get("unverifiable", 0),
            )
        except Exception:
            logger.exception("verify_bg: deal %s failed", deal_id)
            # The per-chunk operation_log entries already captured the
            # error. Nothing else to do — the user will see the stale
            # verified_at timestamp and know to retry.


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


# ===== Data Integrity =====

@router.get("/{deal_id}/quality")
async def deal_quality(deal_id: int, db: AsyncSession = Depends(get_db)):
    """Data-quality summary: counts of verified / extracted / calculated /
    conflicting / locked fields, plus staleness timestamps.

    This is the single endpoint the dashboard calls to render the
    data-integrity panel.
    """
    result = await db.execute(select(Deal).options(selectinload(Deal.documents)).where(Deal.id == deal_id))
    deal = result.scalar_one_or_none()
    if not deal:
        raise HTTPException(status_code=404, detail="Deal not found")
    metrics = deal.metrics or {}
    summary = quality_summary(metrics)
    # Add live staleness flags so the UI can show a "data may be outdated" banner
    stale = staleness_flags(metrics, deal.documents or [])
    return {"summary": summary, "stale_flags": stale}


class FieldEditIn(BaseModel):
    path: str          # dotted, e.g. "deal_structure.ltv"
    value: Optional[float | str | int | bool] = None
    lock: Optional[bool] = True


@router.post("/{deal_id}/fields/edit")
async def edit_field(deal_id: int, data: FieldEditIn, db: AsyncSession = Depends(get_db)):
    """Apply a manual edit to a single metric field and lock it against
    future automatic overwrites.

    Locking is the mechanism that prevents a subsequent `/extract` call
    from clobbering a user correction. Sending `lock=false` just records
    the edit without protecting it.
    """
    result = await db.execute(select(Deal).where(Deal.id == deal_id))
    deal = result.scalar_one_or_none()
    if not deal:
        raise HTTPException(status_code=404, detail="Deal not found")

    metrics = deal.metrics or {}
    metrics = mark_manual_edit(metrics, data.path, data.value, lock=bool(data.lock))
    # Re-validate + re-score so downstream views stay consistent
    flags = validate_deal_metrics(metrics, deal.property_type)
    metrics["validation_flags"] = flags
    deal.metrics = metrics
    await db.commit()
    return {"message": "Field updated", "path": data.path, "locked": bool(data.lock)}


class FieldLockIn(BaseModel):
    path: str
    locked: bool


@router.post("/{deal_id}/fields/lock")
async def lock_field(deal_id: int, data: FieldLockIn, db: AsyncSession = Depends(get_db)):
    """Toggle the lock on a field without changing its value."""
    result = await db.execute(select(Deal).where(Deal.id == deal_id))
    deal = result.scalar_one_or_none()
    if not deal:
        raise HTTPException(status_code=404, detail="Deal not found")

    metrics = deal.metrics or {}
    metrics = set_lock(metrics, data.path, bool(data.locked))
    deal.metrics = metrics
    await db.commit()
    return {"message": "Lock updated", "path": data.path, "locked": bool(data.locked)}


class ConflictResolveIn(BaseModel):
    path: str           # dotted
    value: Optional[float | str | int | bool] = None  # the chosen value


@router.post("/{deal_id}/fields/resolve-conflict")
async def resolve_conflict(deal_id: int, data: ConflictResolveIn, db: AsyncSession = Depends(get_db)):
    """Pick one value from a conflict set. Clears the conflict flag on
    the field, locks it, and removes the corresponding `Data conflict`
    validation flag.
    """
    result = await db.execute(select(Deal).where(Deal.id == deal_id))
    deal = result.scalar_one_or_none()
    if not deal:
        raise HTTPException(status_code=404, detail="Deal not found")

    metrics = deal.metrics.copy() if deal.metrics else {}
    metrics = mark_manual_edit(metrics, data.path, data.value, lock=True)

    # Clear the conflict on the provenance entry
    prov = dict(metrics.get("_provenance") or {})
    if data.path in prov and isinstance(prov[data.path], dict):
        prov[data.path].pop("conflict", None)
        metrics["_provenance"] = prov

    # Remove the matching "Data conflict" flag
    flags = [
        f for f in (metrics.get("validation_flags") or [])
        if not (f.get("category") == "Data conflict" and data.path in (f.get("message") or ""))
    ]
    metrics["validation_flags"] = flags

    deal.metrics = metrics
    await db.commit()
    return {"message": "Conflict resolved", "path": data.path}


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
      - lat, lng             — resolved via Nominatim or user-placed
      - display_name         — free-form, good enough for a map attribution
      - radius_m             — currently fetched radius
      - categories           — {apartments|restaurants|grocery|transit|schools|
                                healthcare|parks|employers: [POI…]}
      - fmr                  — HUD Fair Market Rent (if HUD_API_TOKEN set)
      - fetched_at           — unix timestamp, used for staleness UI

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
    # Invalidate any cached categories — they were centered on the old point.
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

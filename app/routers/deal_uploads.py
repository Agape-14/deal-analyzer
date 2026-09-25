import asyncio
import hashlib
import logging
import os
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import FileResponse
from sqlalchemy import select, update
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import async_session, get_db
from app.models import Deal, DealDocument
from app.rate_limit import limit
from app.services.pdf_extractor import extract_pdf
from app.services.spreadsheet_extractor import extract_spreadsheet
from app.services import notifications as notif_svc
from app.services.document_context import sha256_file, sha256_text
from app.services.document_versions import document_payloads, file_hash
from pydantic import BaseModel, Field
from typing import Literal
from sqlalchemy.orm.attributes import flag_modified

router = APIRouter()
log = logging.getLogger("kenyon.uploads")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
UPLOAD_DIR = os.environ.get(
    "UPLOADS_DIR",
    os.path.join(os.environ.get("DB_DIR", BASE_DIR), "uploads"),
)
os.makedirs(UPLOAD_DIR, exist_ok=True)

MAX_UPLOAD_BYTES = 50 * 1024 * 1024
ALLOWED_EXTS = {".pdf", ".xlsx", ".xlsm", ".xls", ".csv"}
SPREADSHEET_EXTS = {".xlsx", ".xlsm", ".xls", ".csv"}
AUTO_REVIEW_AFTER_UPLOAD = os.getenv("DEAL_REVIEW_AUTO_AFTER_UPLOAD", "1").strip().lower() not in {"0", "false", "no"}


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        log.warning("invalid integer env var %s; using %s", name, default)
        return default


AUTO_REVIEW_DELAY_SECONDS = _env_int("DEAL_REVIEW_AUTO_DELAY_SECONDS", 20)
MEDIA_TYPES = {
    ".pdf": "application/pdf",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".xlsm": "application/vnd.ms-excel.sheet.macroenabled.12",
    ".xls": "application/vnd.ms-excel",
    ".csv": "text/csv",
}
MIMETYPE_EXTS = {
    "application/pdf": ".pdf",
    "application/x-pdf": ".pdf",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "application/vnd.ms-excel.sheet.macroenabled.12": ".xlsm",
    "application/vnd.ms-excel": ".xls",
    "text/csv": ".csv",
    "application/csv": ".csv",
}


@router.get("/{deal_id}/documents")
async def list_uploaded_documents(deal_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(DealDocument).where(DealDocument.deal_id == deal_id).order_by(DealDocument.upload_date.desc())
    )
    return document_payloads(result.scalars().all())


class DocumentVersionChoice(BaseModel):
    expected_revision: int = Field(ge=1)
    source_role: Literal["active", "alternative", "superseded"]
    superseded_by_id: int | None = None
    reason: str = Field(min_length=3, max_length=1000)


@router.put("/{deal_id}/documents/{doc_id}/version")
async def choose_document_version(deal_id: int, doc_id: int, data: DocumentVersionChoice, db: AsyncSession = Depends(get_db)):
    deal = await db.get(Deal, deal_id)
    if not deal or deal.deleted_at is not None:
        raise HTTPException(404, "Deal not found")
    if deal.revision != data.expected_revision:
        raise HTTPException(409, "The deal changed. Reload before changing document versions.")
    if deal.review_job and deal.review_job.status in {"queued", "running"}:
        raise HTTPException(409, "Wait for document review to finish before changing its source package.")
    docs = (await db.execute(select(DealDocument).where(DealDocument.deal_id == deal_id))).scalars().all()
    by_id = {doc.id: doc for doc in docs}
    doc = by_id.get(doc_id)
    if not doc:
        raise HTTPException(404, "Document not found")
    replacement = by_id.get(data.superseded_by_id)
    if data.source_role == "superseded":
        if not replacement or replacement.id == doc.id or replacement.source_role not in {None, "active"}:
            raise HTTPException(422, "Choose a different active replacement document on this deal.")
        if any(d.superseded_by_id == doc.id for d in docs):
            raise HTTPException(422, "This document replaces an earlier version. Point that earlier version to the new replacement first.")
    elif data.superseded_by_id is not None:
        raise HTTPException(422, "Only a superseded document can have a replacement.")
    if data.source_role != "active" and any(d.superseded_by_id == doc.id for d in docs):
        raise HTTPException(422, "An earlier document still uses this one as its current replacement.")
    previous = {"source_role": doc.source_role, "superseded_by_id": doc.superseded_by_id}
    doc.source_role, doc.superseded_by_id, doc.version_note = data.source_role, data.superseded_by_id, data.reason.strip()
    from app.services.data_integrity import now_iso
    metrics = dict(deal.metrics or {})
    metrics["_document_version_history"] = [*(metrics.get("_document_version_history") or []), {
        "document_id": doc.id, "previous": previous, "source_role": data.source_role,
        "superseded_by_id": data.superseded_by_id, "reason": data.reason.strip(), "at": now_iso(),
    }]
    deal.metrics = metrics
    flag_modified(deal, "metrics")
    await db.commit()
    await db.refresh(deal)
    return {"revision": deal.revision, "documents": document_payloads(docs),
            "message": "Source package updated. Originals are retained; source checks need a new review."}


@router.post("/{deal_id}/documents/upload", dependencies=[Depends(limit("upload"))])
async def upload_document(
    deal_id: int,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    doc_type: str = Form("other"),
    db: AsyncSession = Depends(get_db),
):
    file_path: str | None = None
    doc_saved = False
    stage = "starting upload"
    original_name = file.filename or "document"

    try:
        stage = "finding deal"
        result = await db.execute(select(Deal).where(Deal.id == deal_id))
        deal = result.scalar_one_or_none()
        if not deal:
            raise HTTPException(status_code=404, detail="Deal not found")

        stage = "validating file type"
        ext = _upload_extension(file)
        if ext not in ALLOWED_EXTS:
            ctype = (file.content_type or "").lower()
            raise HTTPException(
                status_code=415,
                detail=f"Only PDF, Excel, or CSV uploads are supported (got {ctype or ext or 'unknown type'}).",
            )

        stage = "saving file"
        unique_name = f"{uuid.uuid4().hex}{ext}"
        file_path = os.path.join(UPLOAD_DIR, unique_name)
        total, file_sha256 = await _save_upload_file(file, file_path)
        log.info(
            "Saved uploaded document deal_id=%s filename=%s bytes=%s sha256=%s path=%s",
            deal_id,
            original_name,
            total,
            file_sha256[:12],
            file_path,
        )

        stage = "saving document record"
        doc, duplicate = await _create_document_record_with_retry(
            db,
            {
                "deal_id": deal_id,
                "filename": original_name,
                "file_path": file_path,
                "file_sha256": file_sha256,
                "content_fingerprint": "",
                "doc_type": doc_type,
                "extracted_text": "",
                "page_count": 0,
                "extraction_quality": {
                    "status": "queued",
                    "document_kind": _document_kind(ext),
                    "file_sha256": file_sha256,
                },
            },
            stage,
        )
        if duplicate:
            _remove_partial_file(file_path)
            file_path = None
            return {"id": doc.id, "filename": doc.filename, "duplicate": True,
                    "doc_type": doc.doc_type, "page_count": doc.page_count,
                    "extraction": {"queued": False},
                    "message": "An identical file is already saved. No duplicate or additional review was created."}
        doc_saved = True

        await _safe_emit(
            db,
            kind="info",
            title=f"Uploaded {doc.filename}",
            body=f"{_document_label(ext)} saved; extraction queued",
            href=f"/deals/{deal_id}?tab=documents",
            payload={"deal_id": deal_id, "doc_id": doc.id, "queued": True},
        )
        if not AUTO_REVIEW_AFTER_UPLOAD:
            background_tasks.add_task(_extract_document_background, doc.id, file_path, ext)

        return {
            "id": doc.id,
            "filename": doc.filename,
            "doc_type": doc.doc_type,
            "page_count": 0,
            "text_length": 0,
            "extraction": {"queued": True, "ocr_pages": 0, "tables": 0, "images": 0},
            "message": "Document uploaded; extraction queued",
        }
    except HTTPException:
        if file_path and not doc_saved:
            _remove_partial_file(file_path)
        raise
    except Exception as exc:
        await db.rollback()
        if file_path and not doc_saved:
            _remove_partial_file(file_path)
        log.exception("Document upload failed at stage=%s deal_id=%s filename=%s", stage, deal_id, original_name)
        raise HTTPException(
            status_code=500,
            detail=f"Upload failed during {stage}: {_public_error(exc)}",
        ) from exc
    finally:
        try:
            await file.close()
        except Exception:
            pass


@router.post("/documents/{doc_id}/reprocess")
async def reprocess_document(doc_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(DealDocument).where(DealDocument.id == doc_id))
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    if not doc.file_path or not os.path.exists(doc.file_path):
        raise HTTPException(status_code=410, detail="Original file is no longer available on disk")

    old_len = len(doc.extracted_text or "")
    ext = os.path.splitext(doc.file_path or doc.filename or "")[1].lower()
    extraction, quality, extracted_text, page_count = _extract_uploaded_file(doc.file_path, ext)
    doc.extracted_text = extracted_text
    doc.page_count = page_count
    doc.file_sha256 = quality.get("file_sha256") or doc.file_sha256 or sha256_file(doc.file_path)
    doc.content_fingerprint = quality.get("content_fingerprint") or sha256_text(extracted_text)
    doc.extraction_quality = quality
    await _commit_with_retry(db, "saving reprocessed document")

    return {
        "id": doc.id,
        "filename": doc.filename,
        "page_count": page_count,
        "ocr_pages": extraction.get("ocr_pages", 0),
        "tables": extraction.get("tables", 0),
        "images": extraction.get("images", 0),
        "text_length_before": old_len,
        "text_length_after": len(extracted_text),
        "delta": len(extracted_text) - old_len,
        "message": "Document reprocessed",
    }


@router.get("/documents/{doc_id}/file")
async def get_document_file(doc_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(DealDocument).where(DealDocument.id == doc_id))
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    if not doc.file_path or not os.path.exists(doc.file_path):
        raise HTTPException(status_code=410, detail="Original file is no longer available on disk.")

    real = os.path.realpath(doc.file_path)
    upload_root = os.path.realpath(UPLOAD_DIR)
    if not real.startswith(upload_root + os.sep):
        raise HTTPException(status_code=404, detail="Document not found")

    ext = os.path.splitext(real)[1].lower()
    media_type = MEDIA_TYPES.get(ext, "application/octet-stream")
    disposition = "inline" if ext == ".pdf" else "attachment"
    return FileResponse(
        real,
        media_type=media_type,
        headers={
            "Content-Disposition": f'{disposition}; filename="{doc.filename or "document"}"',
            "Cache-Control": "private, max-age=60",
            "X-Frame-Options": "SAMEORIGIN",
            "Content-Security-Policy": "frame-ancestors 'self'",
        },
    )


def _document_payload(doc: DealDocument) -> dict:
    q = doc.extraction_quality or {}
    extraction_quality = None
    if q:
        extraction_quality = {
            "status": q.get("status"),
            "error": q.get("error"),
            "document_kind": q.get("document_kind"),
            "quality_score": q.get("quality_score"),
            "ocr_pages": q.get("ocr_pages", 0),
            "empty_pages": q.get("empty_pages", []),
            "file_sha256": q.get("file_sha256") or doc.file_sha256,
            "content_fingerprint": q.get("content_fingerprint") or doc.content_fingerprint,
        }
    return {
        "id": doc.id,
        "filename": doc.filename,
        "doc_type": doc.doc_type,
        "page_count": doc.page_count,
        "upload_date": doc.upload_date.isoformat() if doc.upload_date else None,
        "has_text": bool(doc.extracted_text),
        "extraction_quality": extraction_quality,
    }


def _upload_extension(file: UploadFile) -> str:
    ext = os.path.splitext(file.filename or "")[1].lower()
    ctype = (file.content_type or "").lower()
    if not ext:
        ext = MIMETYPE_EXTS.get(ctype, "")
    if ext not in ALLOWED_EXTS and ctype in MIMETYPE_EXTS:
        ext = MIMETYPE_EXTS[ctype]
    return ext


async def _save_upload_file(file: UploadFile, file_path: str) -> tuple[int, str]:
    total = 0
    digest = hashlib.sha256()
    try:
        with open(file_path, "wb") as f:
            while True:
                chunk = await file.read(1 * 1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_UPLOAD_BYTES:
                    raise HTTPException(
                        status_code=413,
                        detail=f"File exceeds {MAX_UPLOAD_BYTES // (1024 * 1024)}MB upload limit.",
                    )
                digest.update(chunk)
                f.write(chunk)
        return total, digest.hexdigest()
    except Exception:
        _remove_partial_file(file_path)
        raise


def _extract_uploaded_file(file_path: str, ext: str) -> tuple[dict, dict, str, int]:
    try:
        result_x = extract_spreadsheet(file_path) if ext in SPREADSHEET_EXTS else extract_pdf(file_path)
        extracted_text = result_x.text
        page_count = result_x.page_count
        file_hash = sha256_file(file_path)
        content_fingerprint = sha256_text(extracted_text)
        empty_pages = [d["page"] for d in result_x.page_diagnostics if d.get("source") == "empty"]
        cells = getattr(result_x, "cells", []) or []
        key_rows = getattr(result_x, "key_rows", []) or []
        extraction = {
            "ocr_pages": result_x.ocr_page_count,
            "tables": len(result_x.tables),
            "images": len(result_x.images),
            "cells": len(cells),
            "key_rows": len(key_rows),
            "quality_score": result_x.quality_score,
            "empty_pages": empty_pages,
            "file_sha256": file_hash,
            "content_fingerprint": content_fingerprint,
        }
        quality = {
            "status": "extracted",
            "quality_score": result_x.quality_score,
            "ocr_pages": result_x.ocr_page_count,
            "empty_pages": empty_pages,
            "page_diagnostics": result_x.page_diagnostics,
            "document_kind": "spreadsheet" if ext in SPREADSHEET_EXTS else "pdf",
            "file_sha256": file_hash,
            "content_fingerprint": content_fingerprint,
        }
        if ext in SPREADSHEET_EXTS:
            quality["cell_provenance"] = cells[:500]
            quality["key_rows"] = key_rows[:100]
        return extraction, quality, extracted_text, page_count
    except Exception as e:
        file_hash = sha256_file(file_path)
        return (
            {"ocr_pages": 0, "tables": 0, "images": 0, "error": str(e), "file_sha256": file_hash},
            {
                "status": "error",
                "error": str(e),
                "document_kind": "spreadsheet" if ext in SPREADSHEET_EXTS else "pdf",
                "file_sha256": file_hash,
            },
            f"Error extracting text: {str(e)}",
            0,
        )


def _document_kind(ext: str) -> str:
    return "spreadsheet" if ext in SPREADSHEET_EXTS else "pdf"


def _document_label(ext: str) -> str:
    return "Spreadsheet" if ext in SPREADSHEET_EXTS else "PDF"


def _remove_partial_file(file_path: str) -> None:
    try:
        if os.path.exists(file_path):
            os.remove(file_path)
    except OSError:
        log.warning("Could not remove partial upload file path=%s", file_path, exc_info=True)


async def _create_document_record_with_retry(
    db: AsyncSession,
    values: dict[str, object],
    stage: str,
) -> tuple[DealDocument, bool]:
    for attempt in range(3):
        try:
            # Serialize uploads for this deal on SQLite and PostgreSQL. Repeat
            # the identity check after every rollback, before enqueuing work.
            await db.execute(update(Deal).where(Deal.id == values["deal_id"]).values(revision=Deal.revision))
            docs = (await db.execute(select(DealDocument).where(DealDocument.deal_id == values["deal_id"]).order_by(DealDocument.id))).scalars().all()
            digest = values.get("file_sha256")
            existing = next((d for d in docs if digest and file_hash(d) == digest), None)
            if existing:
                await db.commit()
                return existing, True
            doc = DealDocument(**values)
            db.add(doc)
            if AUTO_REVIEW_AFTER_UPLOAD:
                from app.services.review_jobs import enqueue_review
                await enqueue_review(db, doc.deal_id)
            await db.commit()
            await db.refresh(doc)
            return doc, False
        except OperationalError as exc:
            await db.rollback()
            if not _is_locked_error(exc) or attempt == 2:
                raise
            await asyncio.sleep(0.5 * (attempt + 1))
            log.warning("Retrying %s after transient database lock", stage)
    raise RuntimeError(f"Could not complete {stage}")


async def _commit_with_retry(db: AsyncSession, stage: str) -> None:
    for attempt in range(3):
        try:
            await db.commit()
            return
        except OperationalError as exc:
            await db.rollback()
            if not _is_locked_error(exc) or attempt == 2:
                raise
            await asyncio.sleep(0.5 * (attempt + 1))
            log.warning("Retrying %s after transient database lock", stage)


def _is_locked_error(exc: OperationalError) -> bool:
    return "locked" in str(exc).lower() or "busy" in str(exc).lower()


def _public_error(exc: Exception) -> str:
    msg = str(exc).strip() or exc.__class__.__name__
    return msg[:500]


async def _safe_emit(db: AsyncSession, **kwargs) -> None:
    try:
        await notif_svc.emit(db, **kwargs)
        await _commit_with_retry(db, "saving notification")
    except Exception:
        await db.rollback()
        log.exception("Notification emit failed during document upload/extraction")


async def _mark_extraction_failed(db: AsyncSession, doc_id: int, ext: str, exc: Exception) -> None:
    try:
        result = await db.execute(select(DealDocument).where(DealDocument.id == doc_id))
        doc = result.scalar_one_or_none()
        if not doc:
            return
        message = _public_error(exc)
        existing_quality = dict(doc.extraction_quality or {})
        doc.extracted_text = f"Error extracting text: {message}"
        doc.page_count = doc.page_count or 0
        doc.extraction_quality = {
            **existing_quality,
            "status": "error",
            "error": message,
            "document_kind": _document_kind(ext),
            "file_sha256": doc.file_sha256 or existing_quality.get("file_sha256"),
        }
        await _commit_with_retry(db, "saving extraction failure")
        await _safe_emit(
            db,
            kind="warning",
            title=f"Extraction failed - {doc.filename}",
            body=message or "The file was saved, but extraction failed.",
            href=f"/deals/{doc.deal_id}?tab=documents",
            payload={"deal_id": doc.deal_id, "doc_id": doc.id, "error": message},
        )
    except Exception:
        await db.rollback()
        log.exception("Could not persist background extraction failure for doc_id=%s", doc_id)


async def _extract_document_background(doc_id: int, file_path: str, ext: str, *, handoff=True) -> None:
    async with async_session() as db:
        result = await db.execute(select(DealDocument).where(DealDocument.id == doc_id))
        doc = result.scalar_one_or_none()
        if not doc:
            return
        try:
            existing_quality = dict(doc.extraction_quality or {})
            file_hash = doc.file_sha256 or existing_quality.get("file_sha256") or sha256_file(file_path)
            if file_hash and not doc.file_sha256:
                doc.file_sha256 = file_hash
            doc.extraction_quality = {
                **existing_quality,
                "status": "extracting",
                "document_kind": _document_kind(ext),
                "file_sha256": file_hash,
            }
            await _commit_with_retry(db, "marking document extracting")

            extraction, quality, extracted_text, page_count = await asyncio.to_thread(_extract_uploaded_file, file_path, ext)
            result = await db.execute(select(DealDocument).where(DealDocument.id == doc_id))
            doc = result.scalar_one_or_none()
            if not doc:
                return
            doc.extracted_text = extracted_text
            doc.page_count = page_count
            doc.file_sha256 = quality.get("file_sha256") or doc.file_sha256 or file_hash
            doc.content_fingerprint = quality.get("content_fingerprint") or sha256_text(extracted_text)
            doc.extraction_quality = quality
            await _commit_with_retry(db, "saving extracted document text")

            if quality.get("status") == "error":
                log.warning("Document extraction failed for doc %s: %s", doc_id, quality.get("error"))
                await _safe_emit(
                    db,
                    kind="warning",
                    title=f"Extraction failed - {doc.filename}",
                    body=str(quality.get("error") or "The file was saved, but extraction failed."),
                    href=f"/deals/{doc.deal_id}?tab=documents",
                    payload={"deal_id": doc.deal_id, "doc_id": doc.id, "error": quality.get("error")},
                )
            else:
                # Progress is visible on the document. Notify once for upload,
                # then for a completed review or failure, not every sub-step.
                if AUTO_REVIEW_AFTER_UPLOAD and handoff:
                    asyncio.create_task(_auto_review_after_upload(doc.deal_id, doc.id))
        except Exception as exc:
            await db.rollback()
            log.exception("Background extraction failed for doc_id=%s", doc_id)
            await _mark_extraction_failed(db, doc_id, ext, exc)
            if AUTO_REVIEW_AFTER_UPLOAD and handoff:
                try:
                    asyncio.create_task(_auto_review_after_upload(doc.deal_id, doc.id))
                except Exception:
                    log.exception("Could not schedule auto document review after extraction failure")


def _document_extraction_pending(doc: DealDocument) -> bool:
    quality = doc.extraction_quality or {}
    status = str(quality.get("status") or "").lower() if isinstance(quality, dict) else ""
    return status in {"queued", "extracting"}


async def _auto_review_after_upload(deal_id: int, source_doc_id: int) -> None:
    """Persist the handoff; queue coalescing replaces an in-memory debounce."""
    from app.services.review_jobs import enqueue_review
    async with async_session() as db:
        await enqueue_review(db, deal_id)
        await db.commit()

import asyncio
import logging
import os
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session, get_db
from app.models import Deal, DealDocument
from app.rate_limit import limit
from app.services.pdf_extractor import extract_pdf
from app.services.spreadsheet_extractor import extract_spreadsheet
from app.services import notifications as notif_svc

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
    return [_document_payload(doc) for doc in result.scalars().all()]


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
        total = await _save_upload_file(file, file_path)
        log.info(
            "Saved uploaded document deal_id=%s filename=%s bytes=%s path=%s",
            deal_id,
            original_name,
            total,
            file_path,
        )

        stage = "saving document record"
        doc = await _create_document_record_with_retry(
            db,
            {
                "deal_id": deal_id,
                "filename": original_name,
                "file_path": file_path,
                "doc_type": doc_type,
                "extracted_text": "",
                "page_count": 0,
                "extraction_quality": {"status": "queued", "document_kind": _document_kind(ext)},
            },
            stage,
        )
        doc_saved = True

        await _safe_emit(
            db,
            kind="info",
            title=f"Uploaded {doc.filename}",
            body=f"{_document_label(ext)} saved; extraction queued",
            href=f"/deals/{deal_id}?tab=documents",
            payload={"deal_id": deal_id, "doc_id": doc.id, "queued": True},
        )
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


async def _save_upload_file(file: UploadFile, file_path: str) -> int:
    total = 0
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
                f.write(chunk)
        return total
    except Exception:
        _remove_partial_file(file_path)
        raise


def _extract_uploaded_file(file_path: str, ext: str) -> tuple[dict, dict, str, int]:
    try:
        result_x = extract_spreadsheet(file_path) if ext in SPREADSHEET_EXTS else extract_pdf(file_path)
        extracted_text = result_x.text
        page_count = result_x.page_count
        empty_pages = [d["page"] for d in result_x.page_diagnostics if d.get("source") == "empty"]
        extraction = {
            "ocr_pages": result_x.ocr_page_count,
            "tables": len(result_x.tables),
            "images": len(result_x.images),
            "cells": len(getattr(result_x, "cells", []) or []),
            "quality_score": result_x.quality_score,
            "empty_pages": empty_pages,
        }
        quality = {
            "status": "extracted",
            "quality_score": result_x.quality_score,
            "ocr_pages": result_x.ocr_page_count,
            "empty_pages": empty_pages,
            "page_diagnostics": result_x.page_diagnostics,
            "document_kind": "spreadsheet" if ext in SPREADSHEET_EXTS else "pdf",
        }
        if ext in SPREADSHEET_EXTS:
            quality["cell_provenance"] = (getattr(result_x, "cells", []) or [])[:500]
        return extraction, quality, extracted_text, page_count
    except Exception as e:
        return (
            {"ocr_pages": 0, "tables": 0, "images": 0, "error": str(e)},
            {"status": "error", "error": str(e), "document_kind": "spreadsheet" if ext in SPREADSHEET_EXTS else "pdf"},
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
) -> DealDocument:
    for attempt in range(3):
        doc = DealDocument(**values)
        db.add(doc)
        try:
            await db.commit()
            await db.refresh(doc)
            return doc
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
        doc.extracted_text = f"Error extracting text: {message}"
        doc.page_count = doc.page_count or 0
        doc.extraction_quality = {
            "status": "error",
            "error": message,
            "document_kind": _document_kind(ext),
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


async def _extract_document_background(doc_id: int, file_path: str, ext: str) -> None:
    async with async_session() as db:
        result = await db.execute(select(DealDocument).where(DealDocument.id == doc_id))
        doc = result.scalar_one_or_none()
        if not doc:
            return
        try:
            doc.extraction_quality = {"status": "extracting", "document_kind": _document_kind(ext)}
            await _commit_with_retry(db, "marking document extracting")

            extraction, quality, extracted_text, page_count = _extract_uploaded_file(file_path, ext)
            result = await db.execute(select(DealDocument).where(DealDocument.id == doc_id))
            doc = result.scalar_one_or_none()
            if not doc:
                return
            doc.extracted_text = extracted_text
            doc.page_count = page_count
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
                unit = "sheet" if ext in SPREADSHEET_EXTS else "page"
                await _safe_emit(
                    db,
                    kind="info",
                    title=f"Extraction complete - {doc.filename}",
                    body=f"{page_count} {unit}{'s' if page_count != 1 else ''} - {len(extracted_text)} characters extracted",
                    href=f"/deals/{doc.deal_id}?tab=documents",
                    payload={"deal_id": doc.deal_id, "doc_id": doc.id, **extraction},
                )
        except Exception as exc:
            await db.rollback()
            log.exception("Background extraction failed for doc_id=%s", doc_id)
            await _mark_extraction_failed(db, doc_id, ext, exc)

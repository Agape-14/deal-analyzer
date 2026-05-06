import os
import uuid
import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import FileResponse
from sqlalchemy import select
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
ALLOWED_MIMETYPES = {
    "application/pdf",
    "application/x-pdf",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-excel.sheet.macroenabled.12",
    "application/vnd.ms-excel",
    "text/csv",
    "application/csv",
}
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


@router.post("/{deal_id}/documents/upload", dependencies=[Depends(limit("upload"))])
async def upload_document(
    deal_id: int,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    doc_type: str = Form("other"),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Deal).where(Deal.id == deal_id))
    deal = result.scalar_one_or_none()
    if not deal:
        raise HTTPException(status_code=404, detail="Deal not found")

    ext = os.path.splitext(file.filename or "")[1].lower()
    ctype = (file.content_type or "").lower()
    if not ext:
        ext = MIMETYPE_EXTS.get(ctype, "")
    if ext not in ALLOWED_EXTS and ctype not in ALLOWED_MIMETYPES:
        raise HTTPException(
            status_code=415,
            detail=f"Only PDF, Excel, or CSV uploads are supported (got {ctype or ext or 'unknown type'}).",
        )

    unique_name = f"{uuid.uuid4().hex}{ext or '.pdf'}"
    file_path = os.path.join(UPLOAD_DIR, unique_name)
    total = 0
    with open(file_path, "wb") as f:
        while True:
            chunk = await file.read(1 * 1024 * 1024)
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

    if ext in SPREADSHEET_EXTS:
        doc = DealDocument(
            deal_id=deal_id,
            filename=file.filename or unique_name,
            file_path=file_path,
            doc_type=doc_type,
            extracted_text="",
            page_count=0,
            extraction_quality={"status": "queued", "document_kind": "spreadsheet"},
        )
        db.add(doc)
        await db.commit()
        await db.refresh(doc)
        await notif_svc.emit(
            db,
            kind="info",
            title=f"Uploaded {doc.filename}",
            body="Spreadsheet saved · extraction queued",
            href=f"/deals/{deal_id}?tab=documents",
            payload={"deal_id": deal_id, "doc_id": doc.id, "queued": True},
        )
        await db.commit()
        background_tasks.add_task(_extract_document_background, doc.id, file_path, ext)
        return {
            "id": doc.id,
            "filename": doc.filename,
            "doc_type": doc.doc_type,
            "page_count": 0,
            "text_length": 0,
            "extraction": {"queued": True, "ocr_pages": 0, "tables": 0, "images": 0},
            "message": "Spreadsheet uploaded; extraction queued",
        }

    extraction, quality, extracted_text, page_count = _extract_uploaded_file(file_path, ext)

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
    await db.commit()

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
        return extraction, quality, extracted_text, page_count
    except Exception as e:
        return (
            {"ocr_pages": 0, "tables": 0, "images": 0, "error": str(e)},
            {"status": "error", "error": str(e), "document_kind": "spreadsheet" if ext in SPREADSHEET_EXTS else "pdf"},
            f"Error extracting text: {str(e)}",
            0,
        )


async def _extract_document_background(doc_id: int, file_path: str, ext: str) -> None:
    async with async_session() as db:
        result = await db.execute(select(DealDocument).where(DealDocument.id == doc_id))
        doc = result.scalar_one_or_none()
        if not doc:
            return
        extraction, quality, extracted_text, page_count = _extract_uploaded_file(file_path, ext)
        doc.extracted_text = extracted_text
        doc.page_count = page_count
        doc.extraction_quality = quality
        await db.commit()
        if quality.get("status") == "error":
            log.warning("Spreadsheet extraction failed for doc %s: %s", doc_id, quality.get("error"))
            await notif_svc.emit(
                db,
                kind="warning",
                title=f"Extraction failed · {doc.filename}",
                body=str(quality.get("error") or "The file was saved, but extraction failed."),
                href=f"/deals/{doc.deal_id}?tab=documents",
                payload={"deal_id": doc.deal_id, "doc_id": doc.id, "error": quality.get("error")},
            )
        else:
            await notif_svc.emit(
                db,
                kind="info",
                title=f"Extraction complete · {doc.filename}",
                body=f"{page_count} sheet{'s' if page_count != 1 else ''} · {len(extracted_text)} characters extracted",
                href=f"/deals/{doc.deal_id}?tab=documents",
                payload={"deal_id": doc.deal_id, "doc_id": doc.id, **extraction},
            )
        await db.commit()

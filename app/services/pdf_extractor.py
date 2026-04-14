"""PDF extraction service.

Extracts text (with OCR fallback for scanned pages), tables, and images from
PDFs uploaded for deal analysis. Image extraction is best-effort — images are
saved next to the source PDF in an `images/` subdirectory and referenced by
relative path so downstream callers (AI extractor) can attach them as vision
inputs.
"""

from __future__ import annotations

import io
import os
from dataclasses import dataclass, field

import fitz  # PyMuPDF

# Minimum number of non-whitespace characters a page must have before we
# consider its text layer "real." Anything shorter triggers OCR.
MIN_TEXT_CHARS = 40

# Render DPI for OCR and image extraction. Higher = better quality, slower.
OCR_DPI = 200
IMAGE_DPI = 150

# Cap per-page OCR time by limiting image count per page, etc.
MAX_IMAGES_PER_PAGE = 10


@dataclass
class PdfExtractionResult:
    """Structured result returned by the enhanced extractor."""

    text: str = ""
    page_count: int = 0
    ocr_page_count: int = 0
    tables: list[dict] = field(default_factory=list)
    images: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "page_count": self.page_count,
            "ocr_page_count": self.ocr_page_count,
            "tables": self.tables,
            "images": self.images,
        }


def _ocr_page(page: "fitz.Page") -> str:
    """Render a page and OCR it. Returns empty string on any failure."""
    try:
        import pytesseract  # type: ignore
        from PIL import Image  # type: ignore
    except ImportError:
        return ""

    try:
        pix = page.get_pixmap(dpi=OCR_DPI)
        img = Image.open(io.BytesIO(pix.tobytes("png")))
        return pytesseract.image_to_string(img) or ""
    except Exception:
        return ""


def _extract_tables(page: "fitz.Page", page_num: int) -> list[dict]:
    """Extract tables from a page using PyMuPDF's table finder.

    Returns a list of {page, rows, markdown} dicts. Failures are swallowed —
    table extraction is best-effort and must not block text extraction.
    """
    results: list[dict] = []
    try:
        tf = page.find_tables()
    except Exception:
        return results

    tables = getattr(tf, "tables", None) or []
    for idx, tbl in enumerate(tables, 1):
        try:
            rows = tbl.extract()
        except Exception:
            continue
        if not rows:
            continue
        # Render as markdown for easy inclusion in AI prompts.
        md_lines: list[str] = []
        for row_idx, row in enumerate(rows):
            cells = ["" if c is None else str(c).replace("|", "\\|") for c in row]
            md_lines.append("| " + " | ".join(cells) + " |")
            if row_idx == 0:
                md_lines.append("|" + "|".join("---" for _ in cells) + "|")
        results.append({
            "page": page_num,
            "table_index": idx,
            "rows": rows,
            "markdown": "\n".join(md_lines),
        })
    return results


def _extract_images(
    doc: "fitz.Document",
    page: "fitz.Page",
    page_num: int,
    output_dir: str,
) -> list[dict]:
    """Extract embedded images from a page and write them to disk.

    Returns metadata for each saved image. Skips tiny images (likely logos /
    icons / bullets) and caps the count per page.
    """
    results: list[dict] = []
    try:
        img_list = page.get_images(full=True)
    except Exception:
        return results

    os.makedirs(output_dir, exist_ok=True)
    for img_idx, img_info in enumerate(img_list[:MAX_IMAGES_PER_PAGE], 1):
        xref = img_info[0]
        try:
            base = doc.extract_image(xref)
        except Exception:
            continue
        if not base:
            continue
        img_bytes = base.get("image")
        ext = base.get("ext", "png")
        width = base.get("width", 0)
        height = base.get("height", 0)

        # Skip trivially small images.
        if width < 80 or height < 80:
            continue
        if not img_bytes:
            continue

        fname = f"page{page_num:03d}_img{img_idx:02d}.{ext}"
        fpath = os.path.join(output_dir, fname)
        try:
            with open(fpath, "wb") as fh:
                fh.write(img_bytes)
        except OSError:
            continue

        results.append({
            "page": page_num,
            "index": img_idx,
            "path": fpath,
            "width": width,
            "height": height,
            "ext": ext,
        })
    return results


def extract_pdf(file_path: str) -> PdfExtractionResult:
    """Full extraction: text (with OCR fallback), tables, and images.

    The primary consumer is the deal extractor. Keeping this function as the
    single entry point makes it easy to tune (e.g., skip tables for large
    docs, or disable image extraction for non-PDF files)."""
    result = PdfExtractionResult()

    if not file_path.lower().endswith(".pdf"):
        return result

    try:
        doc = fitz.open(file_path)
    except Exception as e:
        result.text = f"[Failed to open PDF: {e}]"
        return result

    result.page_count = len(doc)

    images_dir = os.path.join(os.path.dirname(file_path), "images")

    text_parts: list[str] = []
    for page_num, page in enumerate(doc, 1):
        page_text = (page.get_text() or "").strip()

        # OCR fallback for pages with no / near-no text layer.
        if len(page_text) < MIN_TEXT_CHARS:
            ocr_text = _ocr_page(page).strip()
            if len(ocr_text) > len(page_text):
                page_text = ocr_text
                result.ocr_page_count += 1

        if page_text:
            text_parts.append(f"--- Page {page_num} ---\n{page_text}")

        # Best-effort tables and images. Failures are silently skipped.
        result.tables.extend(_extract_tables(page, page_num))
        result.images.extend(_extract_images(doc, page, page_num, images_dir))

    doc.close()
    result.text = "\n\n".join(text_parts)
    return result


def extract_text_from_pdf(file_path: str) -> tuple[str, int]:
    """Backwards-compatible wrapper returning (text, page_count).

    Existing callers (routers/deals.py upload handler) use this signature.
    New callers should prefer ``extract_pdf`` for the full structured result.
    """
    result = extract_pdf(file_path)
    return result.text, result.page_count

"""PDF extraction service.

Extracts text (with OCR fallback for scanned pages), tables, and images from
PDFs uploaded for deal analysis. Image extraction is best-effort — images are
saved next to the source PDF in an `images/` subdirectory and referenced by
relative path so downstream callers (AI extractor) can attach them as vision
inputs.
"""

from __future__ import annotations

import io
import math
import os
import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

import fitz  # PyMuPDF

# Minimum number of non-whitespace characters a page must have before we
# consider its text layer "real." Anything shorter triggers OCR.
MIN_TEXT_CHARS = 40
SPARSE_TEXT_CHARS = 800
LARGE_IMAGE_PAGE_FRACTION = 0.30

# Render DPI for OCR and image extraction. Higher = better quality, slower.
OCR_DPI = 200
IMAGE_DPI = 150

# Cap per-page OCR time by limiting image count per page, etc.
MAX_IMAGES_PER_PAGE = 10
MAX_PDF_TABLES = 32
MAX_TABLE_ROWS = 120
MAX_TABLE_COLUMNS = 20
MAX_PDF_TABLE_CELLS = 2000
MAX_CELL_CHARS = 400
MAX_TABLE_TEXT_CHARS = 40000
MAX_TABLE_REVIEW_CHARS = 8000
MAX_PDF_REVIEW_CHARS = 40000
MAX_NUMERIC_CHECKS_PER_PAGE = 12
MAX_PDF_NUMERIC_CHECKS = 48
MAX_NUMERIC_DIAGNOSTICS = 80
MAX_DIAGNOSTIC_TEXT_CHARS = 20000
_TABLE_REVIEW_MARKER = "\n\n--- Extracted PDF table rows ---\n"

_NUMBER = re.compile(r"(?<![\w.])(?:\(\s*)?[-+−]?\s*[$€£]?\s*\d[\d,.]*(?:\s*[%x×])?(?:\s*\))?(?!\w)", re.I)
_PROPORTION_LABEL = re.compile(
    r"vacancy|occupancy|cap(?:italization)?\s*rate|interest|expense.*ratio|%.*(?:total|egi|gpi|receipts)|"
    r"loan.*(?:cost|value)|\b(?:ltv|ltc)\b", re.I,
)


@dataclass
class PdfExtractionResult:
    """Structured result returned by the enhanced extractor."""

    text: str = ""
    page_count: int = 0
    ocr_page_count: int = 0
    tables: list[dict] = field(default_factory=list)
    images: list[dict] = field(default_factory=list)
    # Per-page extraction diagnostics so the UI can surface "page 3 had
    # no usable text" instead of silently dropping that page's data.
    #   source: "text" | "ocr" | "ocr_weak" | "ocr_image" | "image_text_unread" | "empty"
    #   chars:  non-whitespace character count
    page_diagnostics: list[dict] = field(default_factory=list)
    # Aggregate quality score 0..100 based on page coverage. 100 = every
    # page yielded reasonable text; 0 = all pages empty.
    quality_score: int = 100
    numeric_diagnostics: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "page_count": self.page_count,
            "ocr_page_count": self.ocr_page_count,
            "tables": self.tables,
            "numeric_diagnostics": self.numeric_diagnostics,
            "images": self.images,
            "page_diagnostics": self.page_diagnostics,
            "quality_score": self.quality_score,
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


def _read_budget():
    return {"tables": 0, "cells": 0, "text_chars": 0, "review_chars": 0, "numeric_checks": 0,
            "diagnostics": 0, "diagnostic_chars": 0, "page_checks": {},
            "review_pages": set(), "truncated_pages": set(), "unchecked_pages": set()}


def _bbox(value):
    try:
        box = fitz.Rect(value)
        values = [float(value) for value in box]
        if not all(math.isfinite(value) for value in values) or box.is_empty:
            return None
        return [round(value, 2) for value in values]
    except (TypeError, ValueError, AssertionError):
        return None


def _number_value(token):
    text = re.sub(r"[\s$€£%x×()]", "", token.casefold()).replace("−", "-")
    if not re.fullmatch(r"[-+]?\d+(?:,\d{3})*(?:\.\d+)?", text):
        return None
    try:
        value = Decimal(text.replace(",", ""))
        return -value if token.strip().startswith("(") and token.strip().endswith(")") else value
    except InvalidOperation:
        return None


def _numeric_issue(native_token, other_token):
    if native_token.strip() == other_token.strip():
        return None
    native, other = _number_value(native_token), _number_value(other_token)
    if native is not None and other is not None and native == other:
        return None
    native_digits = re.sub(r"\D", "", native_token)
    other_digits = re.sub(r"\D", "", other_token)
    if native_digits == other_digits and ("," in native_token or "," in other_token):
        return "numeric_grouping_disagreement"
    if native is not None and other is not None and native and other:
        ratio = abs(native / other)
        if ratio in {Decimal("0.001"), Decimal("0.01"), Decimal("0.1"), Decimal(10), Decimal(100), Decimal(1000)}:
            return "possible_dropped_decimal"
    return "numeric_text_disagreement"


def _suspect_number(token, labels):
    grouped = re.sub(r"[\s$€£()%]", "", token)
    money_context = re.search(r"cost|expense|budget|debt|loan|income|revenue|rent|price|proceeds|cash|total|per.unit", labels, re.I)
    if ("." in grouped and re.fullmatch(r"[-+]?[1-9]\d{0,2}(?:[,.]\d{3}){2,}", grouped)
            and (money_context or re.search(r"[$€£(]", token))):
        return "ambiguous_numeric_grouping"
    number = _number_value(token)
    if number is not None and ("%" in token or "%" in labels) and abs(number) > 100 and _PROPORTION_LABEL.search(labels):
        return "unverified_suspect_percentage"
    if number is not None and abs(number) > 20 and re.search(r"\bdscr\b|debt.service.coverage", labels, re.I):
        return "unverified_suspect_ratio"
    return None


def _ocr_region(page, box):
    try:
        import pytesseract
        from PIL import Image

        pix = page.get_pixmap(dpi=OCR_DPI, clip=fitz.Rect(box))
        img = Image.open(io.BytesIO(pix.tobytes("png")))
        return (pytesseract.image_to_string(img, config="--psm 6") or "").strip()
    except Exception:
        return ""


def _add_diagnostic(diagnostic, budget, output):
    size = len(diagnostic["source_row"]) + len(diagnostic.get("corroborating_token") or "")
    if budget["diagnostics"] >= MAX_NUMERIC_DIAGNOSTICS or budget["diagnostic_chars"] + size > MAX_DIAGNOSTIC_TEXT_CHARS:
        budget["unchecked_pages"].add(diagnostic["page"])
        return
    output.append(diagnostic)
    budget["diagnostics"] += 1
    budget["diagnostic_chars"] += size


def _table_numeric_diagnostics(page, table, found_table, words, budget):
    output = []
    checks = budget["page_checks"].get(table["page"], 0)
    review_rows = {row["row"]: row["text"] for row in table["review_rows"]}
    geometry = getattr(found_table, "rows", []) or []
    for row_index, row in enumerate(table["rows"], 1):
        if row_index not in review_rows:
            continue
        for column, text in enumerate(row, 1):
            tokens = _NUMBER.findall(text or "")
            if column == 1 or len(tokens) != 1:
                continue
            token = tokens[0].strip()
            labels = table["row_labels"][row_index - 1] + " " + table["column_labels"][column - 1]
            suspect = _suspect_number(token, labels)
            cells = getattr(geometry[row_index - 1], "cells", []) if row_index <= len(geometry) else []
            box = _bbox(cells[column - 1]) if column <= len(cells) else None
            positioned = []
            if box:
                positioned = [word for word in words
                              if box[0] <= (word[0] + word[2]) / 2 <= box[2]
                              and box[1] <= (word[1] + word[3]) / 2 <= box[3]]
                positioned.sort(key=lambda word: (word[5:] if len(word) >= 8 else (word[1], word[0])))
            native_words = _NUMBER.findall(" ".join(str(word[4]) for word in positioned))
            conflict = _numeric_issue(token, native_words[0]) if len(native_words) == 1 else None
            if not suspect and not conflict:
                continue
            diagnostic = {
                "code": conflict or suspect, "page": table["page"], "table_index": table["table_index"],
                "row": row_index, "column": column, "row_label": table["row_labels"][row_index - 1],
                "column_label": table["column_labels"][column - 1], "native_token": token,
                "reading_source": "native_pdf_table",
                "source_row": review_rows[row_index], "cell_bbox": box,
                "corroborating_token": native_words[0].strip() if conflict else None,
                "corroborating_source": "positioned_native_text" if conflict else None,
            }
            if box and checks < MAX_NUMERIC_CHECKS_PER_PAGE and budget["numeric_checks"] < MAX_PDF_NUMERIC_CHECKS:
                checks += 1
                budget["page_checks"][table["page"]] = checks
                budget["numeric_checks"] += 1
                ocr_tokens = _NUMBER.findall(_ocr_region(page, box))
                if len(ocr_tokens) == 1:
                    ocr_token = ocr_tokens[0].strip()
                    ocr_issue = _numeric_issue(token, ocr_token)
                    if ocr_issue:
                        diagnostic.update(code=ocr_issue, corroborating_token=ocr_token,
                                          corroborating_source="rendered_cell_ocr")
                    elif not conflict and suspect != "ambiguous_numeric_grouping":
                        continue
            elif box:
                budget["unchecked_pages"].add(table["page"])
            _add_diagnostic(diagnostic, budget, output)
    return output


def _ocr_numeric_diagnostics(text, page_text, page_num, budget):
    diagnostics = []
    for row, line in enumerate(text.splitlines(), 1):
        if not line.strip() or line not in page_text or len(line) > 1000:
            continue
        for token in _NUMBER.findall(line):
            code = _suspect_number(token, line)
            if not code:
                continue
            _add_diagnostic({
                "code": code, "page": page_num, "table_index": None, "row": row, "column": None,
                "row_label": line[:line.find(token)].strip()[:120], "column_label": "",
                "native_token": token.strip(), "source_row": line, "cell_bbox": None,
                "reading_source": "rendered_page_ocr",
                "corroborating_token": None, "corroborating_source": None,
            }, budget, diagnostics)
    return diagnostics


def _extract_tables(page: "fitz.Page", page_num: int, budget=None) -> list[dict]:
    """Extract tables from a page using PyMuPDF's table finder.

    Returns a list of {page, rows, markdown} dicts. Failures are swallowed —
    table extraction is best-effort and must not block text extraction.
    """
    results: list[dict] = []
    budget = budget if budget is not None else _read_budget()
    try:
        tf = page.find_tables()
    except Exception:
        return results

    tables = getattr(tf, "tables", None) or []
    try:
        words = page.get_text("words") or []
    except Exception:
        words = []
    for idx, tbl in enumerate(tables, 1):
        if budget["tables"] >= MAX_PDF_TABLES or budget["cells"] >= MAX_PDF_TABLE_CELLS:
            budget["truncated_pages"].add(page_num)
            break
        try:
            rows = tbl.extract()
        except Exception:
            continue
        if not rows:
            continue
        original_rows = len(rows)
        original_columns = max(len(row) for row in rows)
        if not original_columns:
            continue
        bounded_rows = []
        truncated = original_rows > MAX_TABLE_ROWS or original_columns > MAX_TABLE_COLUMNS
        for row in rows[:MAX_TABLE_ROWS]:
            if not row:
                bounded_rows.append([])
                continue
            bounded = []
            for value in row[:MAX_TABLE_COLUMNS]:
                if budget["cells"] >= MAX_PDF_TABLE_CELLS:
                    truncated = True
                    break
                text = None if value is None else str(value)
                if text is not None and (len(text) > MAX_CELL_CHARS or budget["text_chars"] + len(text) > MAX_TABLE_TEXT_CHARS):
                    marker = "[cell text omitted]"
                    text = marker if budget["text_chars"] + len(marker) <= MAX_TABLE_TEXT_CHARS else None
                    truncated = True
                if text is not None:
                    budget["text_chars"] += len(text)
                bounded.append(text)
                budget["cells"] += 1
            if not bounded:
                break
            bounded_rows.append(bounded)
        rows = bounded_rows
        column_count = max(len(row) for row in rows)
        header = getattr(tbl, "header", None)
        names = getattr(header, "names", []) or []
        column_labels = [str(names[index] or "")[:100] if index < len(names) else "" for index in range(column_count)]
        row_labels = [str(row[0] or "")[:120] if row else "" for row in rows]
        truncated = truncated or any(len(str(name or "")) > 100 for name in names[:column_count])
        truncated = truncated or any(row and len(str(row[0] or "")) > 120 for row in rows)
        review_rows = []
        review_size = 0
        for row_index, row in enumerate(rows, 1):
            cells = [f"{column_labels[column - 1] or f'Column {column}'}={' '.join(str(value or '').split())}"
                     for column, value in enumerate(row, 1)]
            line = f"Table {idx} row {row_index} | " + " | ".join(cells)
            size = len(line) + 1
            overhead = len(_TABLE_REVIEW_MARKER) if page_num not in budget["review_pages"] else 0
            if review_size + size > MAX_TABLE_REVIEW_CHARS or budget["review_chars"] + size + overhead > MAX_PDF_REVIEW_CHARS:
                truncated = True
                break
            review_rows.append({"row": row_index, "text": line})
            review_size += size
            budget["review_chars"] += size + overhead
            budget["review_pages"].add(page_num)
        # Render as markdown for easy inclusion in AI prompts.
        md_lines: list[str] = []
        for row_idx, row in enumerate(rows):
            cells = ["" if c is None else str(c).replace("|", "\\|") for c in row]
            md_lines.append("| " + " | ".join(cells) + " |")
            if row_idx == 0:
                md_lines.append("|" + "|".join("---" for _ in cells) + "|")
        table = {
            "page": page_num,
            "table_index": idx,
            "rows": rows,
            "markdown": "\n".join(md_lines),
            "bbox": _bbox(getattr(tbl, "bbox", None)),
            "column_labels": column_labels,
            "row_labels": row_labels,
            "header_external": bool(getattr(header, "external", False)),
            "review_rows": review_rows,
            "original_row_count": original_rows,
            "original_column_count": original_columns,
            "truncated": truncated,
        }
        table["numeric_diagnostics"] = _table_numeric_diagnostics(page, table, tbl, words, budget)
        results.append(table)
        budget["tables"] += 1
        if truncated:
            budget["truncated_pages"].add(page_num)
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


def _has_large_image(page: "fitz.Page") -> bool:
    try:
        page_area = page.rect.get_area()
        images = page.get_image_info() or []
    except Exception:
        return False
    if page_area <= 0:
        return False
    for image in images:
        try:
            image_area = (fitz.Rect(image["bbox"]) & page.rect).get_area()
        except (KeyError, TypeError, ValueError, AssertionError):
            continue
        if image_area >= page_area * LARGE_IMAGE_PAGE_FRACTION:
            return True
    return False


def _merge_page_text(native_text: str, ocr_text: str) -> str:
    normalized_ocr = " ".join(ocr_text.split()).casefold()
    native_lines = [" ".join(line.split()).casefold() for line in native_text.splitlines() if line.strip()]
    if normalized_ocr in " ".join(native_text.split()).casefold():
        return native_text
    if all(line in normalized_ocr for line in native_lines):
        return ocr_text
    return native_text + "\n\n" + ocr_text


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
    budget = _read_budget()
    for page_num, page in enumerate(doc, 1):
        page_text = (page.get_text() or "").strip()
        native_text = page_text
        source = "text" if len(page_text) >= MIN_TEXT_CHARS else "empty"
        image_needs_reading = len(page_text) < SPARSE_TEXT_CHARS and _has_large_image(page)
        ocr_text = ""

        # A native heading can sit above an image containing the actual budget.
        if len(page_text) < MIN_TEXT_CHARS or image_needs_reading:
            ocr_text = _ocr_page(page).strip()
            page_text = _merge_page_text(page_text, ocr_text)
            normalized_page = " ".join(page_text.split()).casefold()
            normalized_native = " ".join(native_text.split()).casefold()
            added_text = normalized_page != normalized_native
            if added_text:
                result.ocr_page_count += 1
                source = "ocr" if len(ocr_text) >= MIN_TEXT_CHARS else "ocr_weak"
            if image_needs_reading:
                image_chars = len(normalized_page) - len(normalized_native)
                source = "ocr_image" if image_chars >= MIN_TEXT_CHARS else "image_text_unread"

        page_tables = _extract_tables(page, page_num, budget)
        page_diagnostics = []
        for table in page_tables:
            page_diagnostics.extend(table.pop("numeric_diagnostics", []))
        page_diagnostics.extend(_ocr_numeric_diagnostics(ocr_text, page_text, page_num, budget))
        review_text = "\n".join(row["text"] for table in page_tables for row in table["review_rows"])
        read_chars = len(page_text)
        if review_text:
            page_text += _TABLE_REVIEW_MARKER + review_text
        if page_text:
            text_parts.append(f"--- Page {page_num} ---\n{page_text}")
        else:
            source = "empty"

        result.page_diagnostics.append(
            {"page": page_num, "source": source, "chars": read_chars, "table_review_chars": len(review_text),
             "image_text_unread": image_needs_reading and source == "image_text_unread",
             "table_count": len(page_tables), "table_details_truncated": page_num in budget["truncated_pages"],
             "numeric_diagnostics_count": len(page_diagnostics),
             "numeric_checks_truncated": page_num in budget["unchecked_pages"]}
        )

        # Best-effort tables and images. Failures are silently skipped.
        result.tables.extend(page_tables)
        result.numeric_diagnostics.extend(page_diagnostics)
        result.images.extend(_extract_images(doc, page, page_num, images_dir))

    doc.close()
    result.text = "\n\n".join(text_parts)

    # Quality score: fraction of pages that produced >= MIN_TEXT_CHARS.
    # Weight early pages (1..5) more heavily — OMs put deal terms up front.
    if result.page_count > 0:
        good = 0.0
        total = 0.0
        for d in result.page_diagnostics:
            w = 2.0 if d["page"] <= 5 else 1.0
            total += w
            if d["chars"] >= MIN_TEXT_CHARS and not d.get("image_text_unread"):
                good += w
        result.quality_score = int(round((good / total) * 100)) if total else 0
    return result


def extract_text_from_pdf(file_path: str) -> tuple[str, int]:
    """Backwards-compatible wrapper returning (text, page_count).

    Existing callers (routers/deals.py upload handler) use this signature.
    New callers should prefer ``extract_pdf`` for the full structured result.
    """
    result = extract_pdf(file_path)
    return result.text, result.page_count

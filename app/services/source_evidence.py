"""Check that a verification citation points to text in a current source.

This validates the citation, not the investment judgment. A provider's confidence
or a page number alone is not evidence that the reported statement exists.
"""
from __future__ import annotations

import re
import math
import unicodedata

from app.services.document_context import split_text_pages


def normalized_text(value):
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", str(value or ""))).strip().casefold()


def numeric_quote_error(value, citation):
    """A source quote must at least contain the audited number, with rounding.

    This necessary check does not establish its investor class or meaning.
    Those still require the semantic review and explicit fact context.
    """
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return ""
    quote = str(citation.get("source_excerpt") or "")
    # Exclude cell addresses so e.g. row 13 cannot substantiate a 13% return.
    quote = re.sub(r"\b[A-Z]{1,3}\$?\d+\s*=", "=", quote, flags=re.I)
    workbook = bool(citation.get("source_sheet"))
    for match in re.finditer(r"(?<![\w.])(-?\d[\d,]*(?:\.\d+)?)\s*(%|million|billion|mm|[mk])?(?![a-z])", quote, re.I):
        raw, suffix = match.groups()
        raw = raw.replace(",", "")
        scale = {"million": 1e6, "mm": 1e6, "m": 1e6, "billion": 1e9, "k": 1e3}.get((suffix or "").lower(), 1)
        number = float(raw) * scale
        decimals = len(raw.split(".")[1]) if "." in raw else 0
        # Half of the last printed decimal; unrounded integers must match.
        tolerance = 0.5 * 10 ** -decimals * scale if decimals else 1e-8
        if math.isclose(value, number, rel_tol=1e-8, abs_tol=tolerance):
            return ""
        if workbook and not suffix and abs(number) <= 1 and math.isclose(value, number * 100, rel_tol=1e-8, abs_tol=tolerance * 100):
            return ""
    return "The supporting quote does not contain the audited value. Recheck the number and its units."


def check_source_excerpt(provenance, documents):
    """Require a verbatim excerpt inside the cited PDF page or workbook sheet."""
    doc = next((doc for doc in documents if doc.id == provenance.get("source_doc_id")), None)
    if doc is None:
        return "The cited source could not be identified."
    text = getattr(doc, "extracted_text", "") or ""
    excerpt = normalized_text(provenance.get("source_excerpt"))
    if len(excerpt) < 8:
        return "The source check needs a supporting quote from the cited page or cell."
    is_workbook = str(getattr(doc, "filename", "")).lower().endswith((".xlsx", ".xlsm", ".xls", ".csv"))
    if is_workbook:
        sheet, cell = provenance.get("source_sheet"), provenance.get("source_cell") or provenance.get("source_range")
        if not isinstance(sheet, str) or not isinstance(cell, str) or not re.fullmatch(r"\$?[A-Z]{1,3}\$?[1-9]\d*(?::\$?[A-Z]{1,3}\$?[1-9]\d*)?", cell, re.I):
            return "The spreadsheet citation needs a sheet name and a valid cell or range."
        marker = re.search(r"^--- Sheet: " + re.escape(sheet) + r" ---\s*$", text, re.M)
        if not marker:
            return "The cited sheet was not found in the extracted workbook."
        end = re.search(r"^--- Sheet: .* ---\s*$", text[marker.end():], re.M)
        source = text[marker.end():marker.end() + end.start()] if end else text[marker.end():]
        # Cell addresses are retained in full sheet text by the extractor.
        start_cell = cell.split(":")[0].replace("$", "").upper()
        if not re.search(r"(?<![A-Z0-9])" + re.escape(start_cell) + r"\s*=", source, re.I):
            return "The cited cell was not found in the extracted workbook. Re-read the original file."
        if not re.search(r"(?<![a-z0-9])" + re.escape(start_cell.casefold()) + r"\s*=", excerpt):
            return "The supporting quote must include the cited cell address and value."
    else:
        page = provenance.get("source_page")
        source = next((body for n, body in split_text_pages(text) if n == page), "")
        if not source:
            return "The cited PDF page has no extracted text. Re-read or visually review the original page."
    if excerpt not in normalized_text(source):
        return "The supporting quote was not found in the cited source. Recheck the page or cell."
    return ""


def fresh_audit_evidence(row, documents, manifest):
    """Resolve this audit row without inheriting any earlier source locator."""
    from app.services.analysis import evidence_for
    citation = {}
    for key in ("source_doc_name", "source_sheet", "source_cell", "source_range", "source_excerpt"):
        if isinstance(row.get(key), str) and row[key].strip():
            citation[key] = row[key].strip()
    if isinstance(row.get("source"), str):
        citation["verification_source"] = row["source"].strip()
    for key in ("source_doc_id", "source_page"):
        if isinstance(row.get(key), int) and not isinstance(row[key], bool) and row[key] > 0:
            citation[key] = row[key]
    if "source_page" not in citation:
        match = re.search(r"\bpage\s+(\d+)\b", citation.get("verification_source", ""), re.I)
        if match:
            citation["source_page"] = int(match[1])
    if documents is None:
        return citation, ""
    evidence, error = evidence_for(citation, manifest)
    if len(evidence) == 1:
        item = evidence[0]
        if citation.get("source_doc_name") and normalized_text(citation["source_doc_name"]) != normalized_text(item["document_name"]):
            return citation, "The document ID and filename in the source check disagree."
        citation.update(source_doc_id=item["document_id"], source_doc_name=item["document_name"], source_document_hash=item["content_hash"])
    return citation, error or check_source_excerpt(citation, documents)

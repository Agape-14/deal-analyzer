"""Shared document context helpers for cost-aware review.

The goal is to reduce repeated AI work without lowering the quality floor:
- hash uploaded files so unchanged packages can reuse prior results;
- build stable fingerprints for metrics/documents;
- select likely-relevant text snippets and page numbers for focused verify
  calls while preserving the full extracted text as the source of truth.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from typing import Any, Iterable


FINANCIAL_TERMS = {
    "irr",
    "return",
    "multiple",
    "equity",
    "cash",
    "yield",
    "pref",
    "preferred",
    "distribution",
    "debt",
    "loan",
    "ltv",
    "dscr",
    "noi",
    "cap rate",
    "cost",
    "budget",
    "hard cost",
    "soft cost",
    "land",
    "contingency",
    "rent",
    "occupancy",
    "units",
    "sponsor",
    "gp",
    "fee",
    "waterfall",
    "hold",
    "sale",
    "exit",
}

_SECTION_TERMS = {
    "deal_structure": {"equity", "debt", "loan", "ltv", "pref", "waterfall", "fee", "capital stack", "sources", "uses", "gp"},
    "target_returns": {"irr", "return", "multiple", "cash", "yield", "distribution", "hold", "sale", "exit", "investor"},
    "project_details": {"units", "unit mix", "sqft", "square", "rent", "occupancy", "stabilization", "construction"},
    "construction_costs": {"cost", "budget", "hard", "soft", "land", "contingency", "site", "developer fee", "reserves"},
    "financial_projections": {"noi", "rent", "occupancy", "expense", "cap rate", "growth", "stabilized"},
    "underwriting_checks": {"dscr", "yield", "noi", "debt service", "cap rate", "break even", "sensitivity"},
    "sponsor_evaluation": {"sponsor", "track record", "aum", "full cycle", "communication", "skin", "gp"},
    "risk_assessment": {"risk", "entitlement", "execution", "market", "developer", "financial"},
    "market_location": {"market", "submarket", "population", "employment", "vacancy", "comparable", "rents"},
}

_PAGE_RE = re.compile(r"---\s*Page\s+(\d+)\s*---", re.IGNORECASE)

VOLATILE_META_KEYS = {
    "_pipeline",
    "_document_review_cache",
    "_verification_cache",
    "_extraction_history",
    "_field_history",
    "_math_checks",
    "_canonical_returns",
    "_data_quality",
    "_shape_errors",
    "_review_resolutions",
    "_manual_edit_warning",
}


def sha256_file(path: str, *, chunk_size: int = 1024 * 1024) -> str:
    """Return the SHA-256 hash of a file, or an empty string if unavailable."""
    if not path or not os.path.exists(path):
        return ""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            chunk = fh.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8", errors="replace")).hexdigest()


def stable_fingerprint(value: Any) -> str:
    """Hash JSON-like data while ignoring volatile pipeline/cache metadata."""
    def scrub(v: Any) -> Any:
        if isinstance(v, dict):
            return {
                str(k): scrub(val)
                for k, val in sorted(v.items(), key=lambda item: str(item[0]))
                if str(k) not in VOLATILE_META_KEYS
            }
        if isinstance(v, list):
            return [scrub(item) for item in v]
        return v

    payload = json.dumps(scrub(value), sort_keys=True, default=str, separators=(",", ":"))
    return sha256_text(payload)


def document_fingerprint(doc: Any) -> dict[str, Any]:
    """Return stable identity fields for one uploaded document."""
    quality = getattr(doc, "extraction_quality", None) or {}
    stored_hash = getattr(doc, "file_sha256", "") or quality.get("file_sha256") or ""
    file_hash = stored_hash or sha256_file(getattr(doc, "file_path", "") or "")
    text = getattr(doc, "extracted_text", "") or ""
    return {
        "id": getattr(doc, "id", None),
        "filename": getattr(doc, "filename", "") or "",
        "doc_type": getattr(doc, "doc_type", "") or "",
        "page_count": getattr(doc, "page_count", 0) or 0,
        "file_sha256": file_hash,
        "text_sha256": sha256_text(text) if text else "",
    }


def documents_fingerprint(docs: Iterable[Any]) -> str:
    payload = [document_fingerprint(doc) for doc in docs or []]
    payload.sort(key=lambda item: (str(item.get("id")), item.get("filename") or ""))
    return stable_fingerprint(payload)


def metrics_sections_fingerprint(metrics: dict[str, Any], sections: Iterable[str]) -> str:
    subset = {s: metrics.get(s) for s in sections if metrics.get(s) is not None}
    return stable_fingerprint(subset)


def split_text_pages(text: str) -> list[tuple[int | None, str]]:
    """Split extracted text into (page_number, page_text) chunks."""
    raw = text or ""
    matches = list(_PAGE_RE.finditer(raw))
    if not matches:
        return [(None, raw)] if raw.strip() else []

    pages: list[tuple[int | None, str]] = []
    for idx, match in enumerate(matches):
        page_num = int(match.group(1))
        start = match.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(raw)
        pages.append((page_num, raw[start:end].strip()))
    return pages


def terms_for_context(sections: Iterable[str], subset_metrics: dict[str, Any] | None = None) -> set[str]:
    terms = set(FINANCIAL_TERMS)
    for section in sections:
        terms.update(_SECTION_TERMS.get(section, set()))
        terms.add(section.replace("_", " "))

    def walk(v: Any) -> None:
        if isinstance(v, dict):
            for k, val in v.items():
                terms.add(str(k).replace("_", " ").lower())
                walk(val)
        elif isinstance(v, list):
            for item in v[:20]:
                walk(item)
        elif isinstance(v, (str, int, float)) and v not in (None, ""):
            rendered = str(v).lower()
            if len(rendered) <= 80:
                for token in re.findall(r"[a-z0-9.%-]+", rendered):
                    if len(token) >= 3:
                        terms.add(token)

    walk(subset_metrics or {})
    return {t.lower() for t in terms if t}


def page_relevance_score(text: str, terms: set[str]) -> int:
    lower = (text or "").lower()
    score = 0
    for term in terms:
        if term and term in lower:
            score += 1
    score += len(re.findall(r"\$?\d[\d,]*(?:\.\d+)?\s*(?:%|x|k|m|mm|million)?", lower)) // 4
    return score


def select_context_for_sections(
    doc_texts: list[dict[str, Any]],
    sections: Iterable[str],
    subset_metrics: dict[str, Any] | None = None,
    *,
    max_chars: int = 70000,
    max_pages_per_doc: int = 8,
    full_text_threshold_chars: int = 50000,
) -> tuple[str, dict[str, list[int]]]:
    """Return focused text plus selected page numbers for verification.

    We include first pages for orientation, then the highest-scoring pages for
    the sections/metrics under review. This reduces image tokens while keeping
    source-backed context specific and auditable.
    """
    terms = terms_for_context(sections, subset_metrics)
    selected_pages: dict[str, list[int]] = {}
    blocks: list[str] = []
    remaining = max_chars
    total_text_chars = sum(len(doc.get("text") or "") for doc in doc_texts or [])

    for doc in doc_texts or []:
        filename = doc.get("filename") or "document"
        pages = split_text_pages(doc.get("text") or "")
        if not pages:
            continue
        scored = []
        for page_num, page_text in pages:
            score = page_relevance_score(page_text, terms)
            if page_num is not None and page_num <= 2:
                score += 3
            scored.append((score, page_num, page_text))
        scored.sort(key=lambda item: (-item[0], item[1] or 999999))

        # When the extracted package is small enough, send the full text for
        # accuracy and still render only the best pages as images. This avoids
        # false "unverifiable" results caused by an over-tight retrieval cut.
        use_full_text = total_text_chars <= min(max_chars, full_text_threshold_chars)
        top = scored if use_full_text else scored[:max_pages_per_doc]
        image_top = scored[:max_pages_per_doc]
        top.sort(key=lambda item: item[1] or 999999)

        nums = [page_num for _, page_num, _ in image_top if page_num is not None]
        if nums:
            selected_pages[filename] = sorted(set(nums))

        heading = "FULL EXTRACTED TEXT" if use_full_text else "RELEVANT TEXT"
        doc_block_lines = [f"===== {heading}: {filename} ====="]
        for score, page_num, page_text in top:
            label = f"--- Page {page_num} (relevance {score}) ---" if page_num is not None else "--- Text excerpt ---"
            excerpt = page_text if use_full_text else page_text[: min(len(page_text), max(3000, remaining // 3))]
            doc_block_lines.append(label)
            doc_block_lines.append(excerpt)
        block = "\n".join(doc_block_lines)
        if len(block) > remaining:
            block = block[:remaining]
        blocks.append(block)
        remaining -= len(block)
        if remaining <= 0:
            break

    return "\n\n".join(blocks), selected_pages


def select_pdf_pages_for_extraction(doc_texts: list[dict[str, Any]], *, max_pages_total: int = 18) -> dict[str, list[int]]:
    """Select PDF pages worth sending as images during extraction.

    Full extracted text is still sent separately. Images are focused on first
    pages and pages with heavy financial terminology/numbers.
    """
    terms = set(FINANCIAL_TERMS)
    chosen: dict[str, list[int]] = {}
    budget = max_pages_total
    for doc in doc_texts or []:
        if budget <= 0:
            break
        filename = doc.get("filename") or "document"
        pages = split_text_pages(doc.get("text") or "")
        scored = []
        for page_num, page_text in pages:
            if page_num is None:
                continue
            score = page_relevance_score(page_text, terms)
            if page_num <= 3:
                score += 4
            scored.append((score, page_num))
        scored.sort(key=lambda item: (-item[0], item[1]))
        per_doc = max(1, min(8, budget))
        nums = sorted({page_num for _, page_num in scored[:per_doc]})
        if nums:
            chosen[filename] = nums
            budget -= len(nums)
    return chosen

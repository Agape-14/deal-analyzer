"""Deal verification engine.

Second-pass AI audit of extracted metrics:
- verify extracted values against source documents;
- flag wrong, missing, unverifiable, and calculated fields;
- return an audit trail used by provenance, review queues, and confidence.

The verifier is intentionally cost-aware but not quality-light. It uses a
retrieval step to send each audit chunk the most relevant text and page images,
while the extraction step still keeps full-document text coverage.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
from typing import Any

import anthropic
import fitz  # PyMuPDF

from app.config import MODEL_VERIFY
from app.services.document_context import (
    documents_fingerprint,
    metrics_sections_fingerprint,
    select_context_for_sections,
)


VERIFY_PROMPT = """You are a forensic real estate investment auditor. Your job is to VERIFY extracted data against source documents.

You will receive:
1. EXTRACTED METRICS JSON for only the sections being audited in this call
2. RELEVANT EXTRACTED TEXT selected from the source documents
3. SELECTED ORIGINAL DOCUMENT PAGE IMAGES when available

Your task: verify every non-null extracted value in the provided sections. Use the text first and the page images as visual support for tables, screenshots, and formatted pages. If the selected evidence does not support a value, mark it wrong or unverifiable; do not guess.

For each field, determine:
- "confirmed": the value matches source evidence. Include document/page/quote or formula.
- "wrong": the extracted value does not match the source. Provide correct_value.
- "unverifiable": you cannot find source support in the supplied evidence.
- "calculated": this is derived and the math checks out.
- "missing": the value is null but the evidence clearly contains it. Provide found_value.

Return ONLY a valid JSON object with this structure:
{
  "audit_results": [
    {
      "section": "deal_structure",
      "field": "total_project_cost",
      "extracted_value": 53287500,
      "status": "calculated",
      "correct_value": 53287500,
      "source": "Calculated from equity ($9,687,500) + debt ($43,600,000)",
      "note": "Math checks out: 9687500 + 43600000 = 53287500"
    }
  ],
  "missing_data": [
    {
      "section": "financial_projections",
      "field": "construction_budget",
      "found_value": 36000000,
      "source": "Page 3 shows Total Construction Budget: $36,000,000",
      "note": "This was present but not extracted"
    }
  ],
  "calculation_checks": [
    {
      "calculation": "price_per_unit",
      "formula": "total_project_cost / unit_count",
      "inputs": "53287500 / 119",
      "result": 447794,
      "extracted_value": 447794,
      "status": "correct"
    }
  ],
  "summary": {
    "total_fields_checked": 65,
    "confirmed": 40,
    "wrong": 3,
    "unverifiable": 15,
    "calculated_correct": 5,
    "calculated_wrong": 0,
    "missing_found": 2,
    "confidence_score": 85
  }
}

Rules:
1. Return only valid JSON, no markdown.
2. Check every non-null field in the supplied sections.
3. For calculated fields, show the formula and math.
4. Use "confirmed" only when there is clear source support.
5. For every confirmed, wrong, calculated, or missing value, include the best available citation in source: document name/page and a short quote or formula.
6. A value from text is source-backed only when you can quote nearby text.
7. For risk scores assigned by analysis rather than stated by the document, mark as "calculated" with a note explaining the basis.
8. If evidence conflicts, mark the field wrong or unverifiable and explain the conflict.
9. Do not silently correct investor-level return metrics from a sponsor/GP column. Investor/LP returns should come from Investor, LP, Class A/B, or new-money investor columns.

HERE ARE THE EXTRACTED METRICS TO VERIFY:
"""


VERIFY_SECTION_GROUPS: list[list[str]] = [
    ["deal_structure", "target_returns"],
    ["project_details", "market_location", "construction_costs", "financial_projections", "underwriting_checks"],
    ["sponsor_evaluation", "risk_assessment"],
]


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


VERIFY_MAX_IMAGE_PAGES_PER_CALL = _env_int("VERIFY_MAX_IMAGE_PAGES_PER_CALL", 5)
VERIFY_MAX_CONTEXT_CHARS = _env_int("VERIFY_MAX_CONTEXT_CHARS", 65000)
VERIFY_FULL_TEXT_THRESHOLD_CHARS = _env_int("VERIFY_FULL_TEXT_THRESHOLD_CHARS", 50000)
VERIFY_MAX_OUTPUT_TOKENS = _env_int("VERIFY_MAX_OUTPUT_TOKENS", 16000)
VERIFY_CONCURRENCY = max(1, _env_int("VERIFY_CONCURRENCY", 2))
VERIFICATION_CACHE_VERSION = 1


def _coerce_json_object(parsed: Any, raw: str, context: str) -> dict:
    value = parsed
    for _ in range(2):
        if not isinstance(value, str):
            break
        candidate = value.strip()
        if not candidate:
            return {}
        try:
            value = json.loads(candidate)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"{context} returned a JSON string, not a JSON object "
                f"(error: {exc}; first 200 chars: {raw[:200]!r})"
            ) from exc

    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    raise ValueError(
        f"{context} returned {type(value).__name__}, expected a JSON object "
        f"(first 200 chars: {raw[:200]!r})"
    )


def _json_preview(value: Any) -> str:
    if value is None:
        return ""
    try:
        return json.dumps(value)[:200]
    except TypeError:
        return str(value)[:200]


def _parse_json_defensively(text: str) -> dict:
    """Parse Claude JSON output, recovering from common formatting issues."""
    raw = text.strip()

    if raw.startswith("```"):
        lines = raw.split("\n")
        lines = [line for line in lines if not line.startswith("```")]
        raw = "\n".join(lines).strip()

    try:
        return _coerce_json_object(json.loads(raw), raw, "Claude response")
    except json.JSONDecodeError:
        pass

    start = raw.find("{")
    end = raw.rfind("}") + 1
    if start >= 0 and end > start:
        candidate = raw[start:end]
        try:
            return _coerce_json_object(json.loads(candidate), raw, "Claude response")
        except json.JSONDecodeError:
            import re

            scrubbed = re.sub(r",(\s*[}\]])", r"\1", candidate)
            try:
                return _coerce_json_object(json.loads(scrubbed), raw, "Claude response")
            except json.JSONDecodeError as exc:
                raise ValueError(
                    "Could not parse verification response as JSON "
                    f"(error: {exc}; first 200 chars: {raw[:200]!r})"
                ) from exc

    raise ValueError(f"No JSON object found in verification response (first 200 chars: {raw[:200]!r})")


def _render_pdf_pages_to_b64(
    pdf_docs: list[tuple[str, str]],
    selected_pages_by_name: dict[str, list[int]],
    max_pages: int,
) -> list[tuple[str, int, int, str]]:
    """Render selected PDF pages to base64 JPEGs."""
    rendered: list[tuple[str, int, int, str]] = []
    remaining = max_pages
    for original_name, path in pdf_docs:
        if remaining <= 0:
            break
        if not path or not os.path.exists(path):
            continue
        pdf_doc = fitz.open(path)
        try:
            selected = selected_pages_by_name.get(original_name) or []
            if not selected:
                selected = list(range(1, min(pdf_doc.page_count, remaining) + 1))
            selected = [p for p in selected if 1 <= p <= pdf_doc.page_count]
            for page_number in selected[:remaining]:
                page = pdf_doc[page_number - 1]
                mat = fitz.Matrix(150 / 72, 150 / 72)
                pix = page.get_pixmap(matrix=mat)
                img_bytes = pix.tobytes("jpeg")
                rendered.append(
                    (
                        original_name,
                        page_number,
                        pdf_doc.page_count,
                        base64.b64encode(img_bytes).decode("utf-8"),
                    )
                )
                remaining -= 1
                if remaining <= 0:
                    break
        finally:
            pdf_doc.close()
    return rendered


async def _verify_sections(
    sections: list[str],
    subset_metrics: dict,
    pdf_docs: list[tuple[str, str]],
    doc_texts: list[dict],
    api_key: str,
    deal_id: int | None,
) -> dict:
    """Verify one metric section group against focused evidence."""
    focused_text, selected_pages = select_context_for_sections(
        doc_texts,
        sections,
        subset_metrics,
        max_chars=VERIFY_MAX_CONTEXT_CHARS,
        max_pages_per_doc=VERIFY_MAX_IMAGE_PAGES_PER_CALL,
        full_text_threshold_chars=VERIFY_FULL_TEXT_THRESHOLD_CHARS,
    )
    rendered_pages = _render_pdf_pages_to_b64(
        pdf_docs,
        selected_pages,
        VERIFY_MAX_IMAGE_PAGES_PER_CALL,
    ) if pdf_docs else []

    content_blocks: list[dict] = [
        {
            "type": "text",
            "text": (
                VERIFY_PROMPT
                + "\n\nFOCUS: only audit fields in these sections: "
                + ", ".join(sections)
                + ".\n\n"
                + json.dumps(subset_metrics, indent=2)
            ),
        }
    ]

    if focused_text:
        content_blocks.append(
            {
                "type": "text",
                "text": "\n\nRELEVANT EXTRACTED TEXT FROM SOURCE DOCUMENTS:\n" + focused_text,
            }
        )

    if rendered_pages:
        content_blocks.append(
            {
                "type": "text",
                "text": "\n\nSELECTED ORIGINAL DOCUMENT PAGE IMAGES FOR THIS AUDIT CHUNK:\n",
            }
        )
        for fname, page_num, total, b64 in rendered_pages:
            content_blocks.append(
                {"type": "text", "text": f"Document '{fname}' - Page {page_num} of {total}:"}
            )
            content_blocks.append(
                {
                    "type": "image",
                    "source": {"type": "base64", "media_type": "image/jpeg", "data": b64},
                }
            )

    from app.services.operation_log import record

    async with record(
        "verify",
        deal_id=deal_id,
        model=MODEL_VERIFY,
        note=f"sections: {','.join(sections)}",
        meta={
            "sections": sections,
            "pages": len(rendered_pages),
            "focused_text_chars": len(focused_text or ""),
            "selected_pages": selected_pages,
        },
    ) as op:
        client = anthropic.AsyncAnthropic(api_key=api_key)
        response_text = ""
        input_tokens = None
        output_tokens = None
        stop_reason = None
        async with client.messages.stream(
            model=MODEL_VERIFY,
            max_tokens=VERIFY_MAX_OUTPUT_TOKENS,
            messages=[{"role": "user", "content": content_blocks}],
        ) as stream:
            async for chunk in stream.text_stream:
                response_text += chunk
            final = await stream.get_final_message()
            try:
                input_tokens = getattr(final.usage, "input_tokens", None)
                output_tokens = getattr(final.usage, "output_tokens", None)
            except Exception:
                pass
            stop_reason = getattr(final, "stop_reason", None)

        op.input_tokens = input_tokens
        op.output_tokens = output_tokens
        op.meta["stop_reason"] = stop_reason
        if stop_reason == "max_tokens":
            raise ValueError(
                f"Verification for {sections} hit max_tokens ceiling. "
                "Try splitting the sections further or reducing pages."
            )

        response_text = response_text.strip()
        op.response_preview = response_text[:2000]
        op.note = "parsing response"
        return _parse_json_defensively(response_text)


async def verify_deal_metrics(deal, db) -> dict:
    """Run second-pass verification on extracted metrics."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY not set")

    metrics = _coerce_json_object(deal.metrics, _json_preview(deal.metrics), "Stored deal metrics")
    deal.metrics = metrics
    if not metrics:
        return {"error": "No metrics to verify"}

    pdf_docs = [
        (doc.filename, doc.file_path)
        for doc in deal.documents
        if doc.file_path and str(doc.file_path).lower().endswith(".pdf")
    ]
    doc_texts = []
    for doc in deal.documents:
        text = (doc.extracted_text or "").strip()
        quality = doc.extraction_quality or {}
        if text and not text.startswith("Error extracting text:") and not (isinstance(quality, dict) and quality.get("error")):
            doc_texts.append({"filename": doc.filename, "text": text})

    groups_to_run: list[list[str]] = []
    for group in VERIFY_SECTION_GROUPS:
        if any(metrics.get(section) for section in group):
            groups_to_run.append(group)

    planned = {section for group in VERIFY_SECTION_GROUPS for section in group}
    extra_sections = [
        section
        for section in metrics.keys()
        if section not in planned
        and not str(section).startswith("_")
        and section not in ("validation_flags",)
        and isinstance(metrics.get(section), dict)
        and metrics.get(section)
    ]
    if extra_sections:
        groups_to_run.append(extra_sections)

    docs_fp = documents_fingerprint(deal.documents or [])
    metrics_fp = metrics_sections_fingerprint(metrics, [s for group in groups_to_run for s in group])
    cache = metrics.get("_verification_cache")
    if isinstance(cache, dict):
        cached_verification = cache.get("verification")
        if (
            cache.get("cache_version") == VERIFICATION_CACHE_VERSION
            and cache.get("documents_fingerprint") == docs_fp
            and cache.get("metrics_fingerprint") == metrics_fp
            and isinstance(cached_verification, dict)
        ):
            reused = json.loads(json.dumps(cached_verification, default=str))
            summary = reused.setdefault("summary", {})
            if isinstance(summary, dict):
                summary["cache_hit"] = True
            return reused

    combined: dict = {"audit_results": [], "missing_data": [], "calculation_checks": [], "summary": {}}
    confidences: list[float] = []
    errors: list[str] = []
    semaphore = asyncio.Semaphore(VERIFY_CONCURRENCY)

    async def _run_one(group: list[str]) -> tuple[list[str], dict | Exception]:
        subset = {section: metrics.get(section) for section in group if metrics.get(section) is not None}
        async with semaphore:
            try:
                result = await _verify_sections(group, subset, pdf_docs, doc_texts, api_key, getattr(deal, "id", None))
                return group, result
            except Exception as exc:
                return group, exc

    results = await asyncio.gather(*[_run_one(group) for group in groups_to_run])

    for group, result in results:
        if isinstance(result, Exception):
            errors.append(f"{','.join(group)}: {result}")
            continue
        if isinstance(result, dict):
            combined["audit_results"].extend(result.get("audit_results") or [])
            combined["missing_data"].extend(result.get("missing_data") or [])
            combined["calculation_checks"].extend(result.get("calculation_checks") or [])
            summary = result.get("summary") or {}
            confidence = summary.get("confidence_score")
            try:
                if confidence is not None:
                    confidences.append(float(confidence))
            except (TypeError, ValueError):
                pass

    if confidences:
        combined["summary"]["confidence_score"] = round(sum(confidences) / len(confidences), 1)
    if errors:
        combined["summary"]["partial_errors"] = errors

    metrics["_verification_cache"] = {
        "cache_version": VERIFICATION_CACHE_VERSION,
        "documents_fingerprint": docs_fp,
        "metrics_fingerprint": metrics_fp,
        "verification": combined,
        "updated_at": _now_iso(),
    }
    deal.metrics = metrics
    return combined


def apply_corrections(metrics: dict, verification: dict) -> tuple[dict, list[str]]:
    """Apply verified corrections to metrics and preserve provenance."""
    metrics = _coerce_json_object(metrics, _json_preview(metrics), "Metrics corrections input")
    verification = _coerce_json_object(verification, _json_preview(verification), "Verification corrections input")
    changes = []
    prov = dict(metrics.get("_provenance") or {})

    for result in verification.get("audit_results", []):
        status = result.get("status", "")
        correct_val = result.get("correct_value")
        extracted_val = result.get("extracted_value")
        needs_fix = status == "wrong"
        if status == "calculated" and correct_val is not None and extracted_val is not None:
            try:
                needs_fix = abs(float(correct_val) - float(extracted_val)) > 0.01
            except (TypeError, ValueError):
                needs_fix = str(correct_val) != str(extracted_val)
        if needs_fix and correct_val is not None:
            section = result.get("section")
            field = result.get("field")
            if section in metrics and isinstance(metrics[section], dict):
                pre = metrics[section].get(field, extracted_val)
                metrics[section][field] = correct_val
                changes.append(
                    f"CORRECTED {section}.{field}: {pre} -> {correct_val} "
                    f"(Source: {result.get('source', 'verification')})"
                )
                path = f"{section}.{field}"
                p = dict(prov.get(path) or {})
                p["previous_value"] = pre
                p["corrected_value"] = correct_val
                if result.get("source"):
                    p["correction_source"] = str(result.get("source"))
                if result.get("note"):
                    p["correction_note"] = str(result.get("note"))
                prov[path] = p

    metrics["_provenance"] = prov

    for found in verification.get("missing_data", []):
        section = found.get("section")
        field = found.get("field")
        value = found.get("found_value")
        if section and field and value is not None:
            if section not in metrics:
                metrics[section] = {}
            if isinstance(metrics[section], dict):
                old_val = metrics[section].get(field)
                if old_val is None or old_val == "" or old_val == 0:
                    metrics[section][field] = value
                    changes.append(
                        f"ADDED {section}.{field}: {value} "
                        f"(Source: {found.get('source', 'found in document')})"
                    )

    if changes:
        from app.services.deal_extractor import _post_process_metrics

        _post_process_metrics(metrics)

    return metrics, changes


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()

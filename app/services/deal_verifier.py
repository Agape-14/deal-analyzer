"""
Deal Verification Engine — Second-pass AI audit of extracted metrics.

Pattern: Extract → Verify → Flag discrepancies
- Sends the extracted metrics + original document back to AI
- AI checks EVERY value against the source
- Flags: CONFIRMED, WRONG, UNVERIFIABLE, CALCULATED (with recalc check)
- Returns detailed audit trail
"""

import os
import io
import json
import base64
import anthropic
import fitz  # PyMuPDF

from app.config import MODEL_VERIFY


VERIFY_PROMPT = """You are a forensic real estate investment auditor. Your job is to VERIFY extracted data against source documents.

You will receive:
1. A set of EXTRACTED METRICS (JSON) that an AI previously extracted from deal documents
2. The ORIGINAL DOCUMENT PAGES (as images) to check against

Your task: Go through EVERY non-null extracted value and verify it against what you can actually see in the documents.

For EACH field, determine:
- "confirmed" — You can see this exact value (or very close) in the source document
- "wrong" — The extracted value does NOT match what's in the document. Provide the CORRECT value.
- "unverifiable" — You cannot find this data point in the visible pages (it may be correct but you can't confirm)
- "calculated" — This is a derived/calculated value. Verify the math is correct.
- "missing" — The value is null but you CAN see this data in the documents. Provide the correct value.

Return a JSON object with this structure:
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
    },
    {
      "section": "project_details",
      "field": "unit_count",
      "extracted_value": 119,
      "status": "wrong",
      "correct_value": 141,
      "source": "Page 1 shows 141 Units Total (119 market rate + 22 affordable)",
      "note": "Extracted only market rate units, should include all 141"
    }
  ],
  "missing_data": [
    {
      "section": "financial_projections",
      "field": "construction_budget",
      "found_value": 36000000,
      "source": "Page 3 shows Total Construction Budget: $36,000,000",
      "note": "This was in the document but the extractor missed it"
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

IMPORTANT RULES:
1. Return ONLY valid JSON
2. Check EVERY non-null field — do not skip any
3. For calculated fields, show your math step by step
4. If you find data in the images that was NOT extracted, include it in missing_data
5. Be especially careful with: unit counts (market rate vs total), dollar amounts, percentages, fee structures
6. For the unit_count field specifically: check if it should be market rate only (119) or total including affordable (141) — note which is used
7. Double-check all division calculations (price/unit, price/sqft, etc.)
8. Flag ANY inconsistency, even small ones
9. confidence_score: 0-100 based on how much you could verify

HERE ARE THE EXTRACTED METRICS TO VERIFY:
"""


def _parse_json_defensively(text: str) -> dict:
    """Parse Claude's JSON output, recovering from common issues.

    Claude sometimes wraps JSON in markdown fences, appends a stray
    trailing comma, or prepends a one-line preamble. Walk through
    a ladder of recovery attempts before giving up.
    """
    raw = text.strip()

    # Strip markdown fences like ```json ... ```
    if raw.startswith("```"):
        lines = raw.split("\n")
        lines = [l for l in lines if not l.startswith("```")]
        raw = "\n".join(lines).strip()

    # Happy path
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    # Fall back to the largest balanced {...} span we can find.
    start = raw.find("{")
    end = raw.rfind("}") + 1
    if start >= 0 and end > start:
        candidate = raw[start:end]
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            # Last-resort: drop trailing commas before a closing
            # bracket/brace — Claude occasionally emits them.
            import re
            scrubbed = re.sub(r",(\s*[}\]])", r"\1", candidate)
            try:
                return json.loads(scrubbed)
            except json.JSONDecodeError as e:
                raise ValueError(
                    f"Could not parse verification response as JSON "
                    f"(error: {e}; tried raw + span + trailing-comma "
                    f"scrub; first 200 chars: {raw[:200]!r})"
                )

    raise ValueError(
        f"No JSON object found in verification response "
        f"(first 200 chars: {raw[:200]!r})"
    )


# Groups of metric sections audited together — kept small so each
# verify call stays well under Anthropic's input-tokens-per-minute
# ceiling AND under the output-tokens cap we set per call. Early
# attempts paired deal_structure + target_returns but that combo
# hit ~45 fields × ~400 output-tokens = 18K which tripped the
# per-call max_tokens ceiling. One section per group is the
# conservative default; we only pair small sections.
VERIFY_SECTION_GROUPS: list[list[str]] = [
    ["deal_structure"],
    ["target_returns"],
    ["project_details", "market_location"],
    ["financial_projections", "underwriting_checks"],
    ["sponsor_evaluation"],
]
# Max PDF pages per verify call. Below the Anthropic message-size
# soft ceiling that was causing 429s. Each page at 150 DPI base64
# is ~250 KB, so 5 pages keeps a single verify well under ~1.5 MB.
VERIFY_MAX_PAGES = 5
# Output ceiling per chunk. Each audit row is ~300-500 tokens
# (status + correct_value + source citation + note + confidence);
# 16K gives us ~35-50 fields of headroom which comfortably covers
# even the biggest single section (deal_structure ~25 fields).
VERIFY_MAX_OUTPUT_TOKENS = 16000


def _render_pdf_pages_to_b64(doc_paths: list[str], max_pages: int) -> list[tuple[str, int, int, str]]:
    """Render the first `max_pages` pages of each PDF to base64 PNGs.

    Returns a list of (filename, page_number, total_pages, b64_data) tuples.
    Shared by all per-group verify calls so we only pay the PDF render
    cost once per verify run.
    """
    rendered: list[tuple[str, int, int, str]] = []
    for path in doc_paths:
        if not os.path.exists(path):
            continue
        pdf_doc = fitz.open(path)
        try:
            fname = os.path.basename(path)
            n = min(pdf_doc.page_count, max_pages)
            for page_num in range(n):
                page = pdf_doc[page_num]
                mat = fitz.Matrix(150 / 72, 150 / 72)
                pix = page.get_pixmap(matrix=mat)
                img_bytes = pix.tobytes("png")
                rendered.append(
                    (fname, page_num + 1, pdf_doc.page_count,
                     base64.b64encode(img_bytes).decode("utf-8"))
                )
        finally:
            pdf_doc.close()
    return rendered


async def _verify_sections(
    sections: list[str],
    subset_metrics: dict,
    rendered_pages: list[tuple[str, int, int, str]],
    api_key: str,
    deal_id: int | None,
) -> dict:
    """Verify one group of metric sections against the rendered PDF pages.

    Returns the parsed verification dict (audit_results, missing_data,
    summary). Runs inside a dedicated operation_log.record() so each
    chunk is visible in the diagnostics panel with its own timing.
    """
    content_blocks: list[dict] = []
    content_blocks.append({
        "type": "text",
        "text": (
            VERIFY_PROMPT
            + "\n\nFOCUS: only audit fields in these sections: "
            + ", ".join(sections)
            + ".\n\n"
            + json.dumps(subset_metrics, indent=2)
        ),
    })
    if rendered_pages:
        content_blocks.append({
            "type": "text",
            "text": "\n\nBELOW ARE THE ORIGINAL DOCUMENT PAGES. Check every extracted value against these:\n",
        })
        for fname, page_num, total, b64 in rendered_pages:
            content_blocks.append({
                "type": "text",
                "text": f"Document '{fname}' — Page {page_num} of {total}:",
            })
            content_blocks.append({
                "type": "image",
                "source": {"type": "base64", "media_type": "image/png", "data": b64},
            })

    from app.services.operation_log import record
    async with record(
        "verify",
        deal_id=deal_id,
        model=MODEL_VERIFY,
        note=f"sections: {','.join(sections)}",
        meta={"sections": sections, "pages": len(rendered_pages)},
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
    """Run second-pass verification on extracted metrics.

    Verification is split into multiple smaller Anthropic calls — one
    per group of tightly-related metric sections — so we stay under
    Anthropic's per-minute input-tokens rate limit on non-enterprise
    tiers. A single monolithic call with all ~100 fields and 10 PDF
    pages was hitting 429s. Per-chunk calls are short (8-15s each)
    and their results are merged into one verification dict compatible
    with the existing stamp_verification / apply_corrections pipeline.

    Args:
        deal: Deal ORM object with metrics and documents
        db: Database session

    Returns:
        Verification results dict with audit trail (audit_results,
        missing_data, summary) — same shape as before, regardless of
        how many underlying calls ran.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY not set")

    metrics = deal.metrics
    if not metrics:
        return {"error": "No metrics to verify"}

    doc_paths = [
        doc.file_path
        for doc in deal.documents
        if doc.file_path and doc.file_path.endswith(".pdf")
    ]
    # Render pages once up-front so each chunk reuses the same b64 data.
    rendered = _render_pdf_pages_to_b64(doc_paths, VERIFY_MAX_PAGES) if doc_paths else []

    # Decide which section groups actually have something to audit.
    groups_to_run: list[list[str]] = []
    for group in VERIFY_SECTION_GROUPS:
        if any(metrics.get(s) for s in group):
            groups_to_run.append(group)
    # Any sections the metrics have that we didn't plan for — fold
    # them into their own group so nothing is silently skipped.
    planned = {s for g in VERIFY_SECTION_GROUPS for s in g}
    extra_sections = [
        s for s in metrics.keys()
        if s not in planned
        and not s.startswith("_")
        and s not in ("validation_flags",)
        and isinstance(metrics.get(s), dict)
        and metrics.get(s)
    ]
    if extra_sections:
        groups_to_run.append(extra_sections)

    # Merge the per-group results into a single verification dict.
    combined: dict = {"audit_results": [], "missing_data": [], "summary": {}}
    confidences: list[float] = []
    errors: list[str] = []

    for group in groups_to_run:
        subset = {s: metrics.get(s) for s in group if metrics.get(s) is not None}
        try:
            res = await _verify_sections(group, subset, rendered, api_key, getattr(deal, "id", None))
        except Exception as e:
            # One group failing shouldn't sink the whole verification —
            # other sections still get audited. The diagnostics entry
            # for the failed group records the exception.
            errors.append(f"{','.join(group)}: {e}")
            continue

        if isinstance(res, dict):
            combined["audit_results"].extend(res.get("audit_results") or [])
            combined["missing_data"].extend(res.get("missing_data") or [])
            s = (res.get("summary") or {})
            c = s.get("confidence_score")
            try:
                if c is not None:
                    confidences.append(float(c))
            except (TypeError, ValueError):
                pass

    if confidences:
        combined["summary"]["confidence_score"] = round(sum(confidences) / len(confidences), 1)
    if errors:
        combined["summary"]["partial_errors"] = errors

    return combined


def apply_corrections(metrics: dict, verification: dict) -> tuple[dict, list[str]]:
    """Apply verified corrections to metrics.

    Returns:
        (corrected_metrics, list of changes made)

    Also stashes the previous extracted value on the provenance tree
    under `_provenance[<path>].previous_value` so the UI can show
    "corrected from X → Y" and offer a revert.
    """
    changes = []
    prov = dict(metrics.get("_provenance") or {})

    # Apply corrections for wrong AND calculated-wrong fields
    for result in verification.get("audit_results", []):
        status = result.get("status", "")
        correct_val = result.get("correct_value")
        extracted_val = result.get("extracted_value")
        # Correct if wrong, or if calculated and values differ
        needs_fix = (status == "wrong")
        if status == "calculated" and correct_val is not None and extracted_val is not None:
            try:
                needs_fix = abs(float(correct_val) - float(extracted_val)) > 0.01
            except (TypeError, ValueError):
                needs_fix = str(correct_val) != str(extracted_val)
        if needs_fix and correct_val is not None:
            section = result.get("section")
            field = result.get("field")
            old_val = extracted_val
            new_val = correct_val

            if section in metrics and isinstance(metrics[section], dict):
                # Capture the pre-correction value from the actual
                # metrics dict (more reliable than the verification
                # result's extracted_value, which the model sometimes
                # reformats before echoing back).
                pre = metrics[section].get(field, old_val)
                metrics[section][field] = new_val
                changes.append(
                    f"CORRECTED {section}.{field}: {pre} → {new_val} "
                    f"(Source: {result.get('source', 'verification')})"
                )
                # Stash previous value + correction metadata on
                # provenance so the UI's integrity badge can render
                # an actionable "corrected from X" card with a
                # revert button.
                path = f"{section}.{field}"
                p = dict(prov.get(path) or {})
                p["previous_value"] = pre
                p["corrected_value"] = new_val
                if result.get("source"):
                    p["correction_source"] = str(result.get("source"))
                if result.get("note"):
                    p["correction_note"] = str(result.get("note"))
                prov[path] = p

    metrics["_provenance"] = prov

    # Apply missing data that was found
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
    
    # Re-run post-processing to recalculate derived fields from corrected base values
    if changes:
        from app.services.deal_extractor import _post_process_metrics
        _post_process_metrics(metrics)
    
    return metrics, changes

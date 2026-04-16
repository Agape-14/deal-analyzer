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


async def verify_deal_metrics(deal, db) -> dict:
    """Run second-pass verification on extracted metrics.
    
    Args:
        deal: Deal ORM object with metrics and documents
        db: Database session
        
    Returns:
        Verification results dict with audit trail
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY not set")
    
    metrics = deal.metrics
    if not metrics:
        return {"error": "No metrics to verify"}
    
    # Build content blocks
    content_blocks = []
    
    # Clean metrics for verification (remove validation_flags)
    clean_metrics = {k: v for k, v in metrics.items() if k != 'validation_flags'}
    
    # Add the prompt + extracted metrics
    content_blocks.append({
        "type": "text",
        "text": VERIFY_PROMPT + json.dumps(clean_metrics, indent=2)
    })
    
    # Add document page images
    doc_paths = [
        doc.file_path
        for doc in deal.documents
        if doc.file_path and doc.file_path.endswith(".pdf")
    ]
    
    if doc_paths:
        content_blocks.append({
            "type": "text",
            "text": "\n\nBELOW ARE THE ORIGINAL DOCUMENT PAGES. Check every extracted value against these:\n"
        })
        
        for path in doc_paths:
            if not os.path.exists(path):
                continue
            pdf_doc = fitz.open(path)
            fname = os.path.basename(path)
            # Send up to 10 pages at lower res to stay within limits
            max_pages = min(pdf_doc.page_count, 10)
            for page_num in range(max_pages):
                page = pdf_doc[page_num]
                # 150 DPI for readability while managing size
                mat = fitz.Matrix(150/72, 150/72)
                pix = page.get_pixmap(matrix=mat)
                img_bytes = pix.tobytes("png")
                img_b64 = base64.b64encode(img_bytes).decode("utf-8")
                content_blocks.append({
                    "type": "text",
                    "text": f"Document '{fname}' — Page {page_num + 1} of {pdf_doc.page_count}:"
                })
                content_blocks.append({
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/png",
                        "data": img_b64
                    }
                })
            pdf_doc.close()
    
    from app.services.operation_log import record
    async with record(
        "verify",
        deal_id=getattr(deal, "id", None),
        model=MODEL_VERIFY,
        meta={"num_pdf_docs": len(doc_paths)},
    ) as op:
        client = anthropic.Anthropic(api_key=api_key)
        op.note = "calling Anthropic"
        message = client.messages.create(
            model=MODEL_VERIFY,
            max_tokens=8192,
            messages=[{"role": "user", "content": content_blocks}]
        )
        try:
            op.input_tokens = getattr(message.usage, "input_tokens", None)
            op.output_tokens = getattr(message.usage, "output_tokens", None)
        except Exception:
            pass

        response_text = message.content[0].text.strip()
        op.response_preview = response_text[:2000]

        # Parse JSON response
        op.note = "parsing response"
        if response_text.startswith("```"):
            lines = response_text.split("\n")
            lines = [l for l in lines if not l.startswith("```")]
            response_text = "\n".join(lines)

        try:
            verification = json.loads(response_text)
        except json.JSONDecodeError:
            start = response_text.find("{")
            end = response_text.rfind("}") + 1
            if start >= 0 and end > start:
                verification = json.loads(response_text[start:end])
            else:
                raise ValueError("Could not parse verification response as JSON")

        return verification


def apply_corrections(metrics: dict, verification: dict) -> tuple[dict, list[str]]:
    """Apply verified corrections to metrics.
    
    Returns:
        (corrected_metrics, list of changes made)
    """
    changes = []
    
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
                metrics[section][field] = new_val
                changes.append(
                    f"CORRECTED {section}.{field}: {old_val} → {new_val} "
                    f"(Source: {result.get('source', 'verification')})"
                )
    
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

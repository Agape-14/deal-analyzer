"""Cost-aware document extraction.

This keeps the same high-accuracy extraction prompt/schema from
``deal_extractor`` but avoids sending a blanket set of PDF images on every run.
Full extracted text is still included; PDF images are selected from pages most
likely to contain financial tables and deal terms.
"""

from __future__ import annotations

import base64
import os

import anthropic

from app.config import MODEL_EXTRACT
from app.services.deal_extractor import EXTRACTION_PROMPT, _post_process_metrics
from app.services.document_context import select_pdf_pages_for_extraction
from app.services.operation_log import record

EXTRACT_MAX_IMAGE_PAGES = int(os.getenv("EXTRACT_MAX_IMAGE_PAGES", "18"))
EXTRACT_IMAGE_DPI = int(os.getenv("EXTRACT_IMAGE_DPI", "150"))


async def extract_metrics_from_docs(doc_texts: list[dict], doc_paths: list[str] | None = None) -> dict:
    """Extract metrics using full text plus selected PDF page images."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY not set")

    content_blocks: list[dict] = []
    doc_context = ""
    for doc in doc_texts:
        doc_context += f"\n\n===== DOCUMENT: {doc['filename']} (Type: {doc['doc_type']}) =====\n"
        doc_context += doc.get("text") or ""

    content_blocks.append({"type": "text", "text": EXTRACTION_PROMPT + doc_context})

    pages_used = 0
    selected_pages_meta: dict[str, list[int]] = {}
    if doc_paths:
        try:
            import fitz

            pdf_doc_texts = [
                doc
                for doc in doc_texts
                if str(doc.get("filename") or "").lower().endswith(".pdf")
            ]
            selected_by_name = select_pdf_pages_for_extraction(
                pdf_doc_texts,
                max_pages_total=EXTRACT_MAX_IMAGE_PAGES,
            )

            for index, path in enumerate(doc_paths):
                if pages_used >= EXTRACT_MAX_IMAGE_PAGES:
                    break
                if not path or not os.path.exists(path):
                    continue
                pdf_text = pdf_doc_texts[index] if index < len(pdf_doc_texts) else {}
                original_name = pdf_text.get("filename") or os.path.basename(path)
                pdf_doc = fitz.open(path)
                try:
                    selected_pages = selected_by_name.get(original_name) or list(
                        range(1, min(pdf_doc.page_count, EXTRACT_MAX_IMAGE_PAGES - pages_used) + 1)
                    )
                    selected_pages = [p for p in selected_pages if 1 <= p <= pdf_doc.page_count]
                    if not selected_pages:
                        continue
                    selected_pages_meta[original_name] = selected_pages[:]
                    content_blocks.append(
                        {
                            "type": "text",
                            "text": (
                                f"\n\nBELOW ARE SELECTED PAGE IMAGES from '{original_name}' "
                                f"({pdf_doc.page_count} pages total, showing {len(selected_pages)} selected pages). "
                                "Use these for tables, charts, and formatted data that may not appear cleanly in text.\n"
                            ),
                        }
                    )
                    for page_number in selected_pages:
                        if pages_used >= EXTRACT_MAX_IMAGE_PAGES:
                            break
                        page = pdf_doc[page_number - 1]
                        mat = fitz.Matrix(EXTRACT_IMAGE_DPI / 72, EXTRACT_IMAGE_DPI / 72)
                        pix = page.get_pixmap(matrix=mat)
                        img_bytes = pix.tobytes("jpeg")
                        img_b64 = base64.b64encode(img_bytes).decode("utf-8")
                        content_blocks.append(
                            {"type": "text", "text": f"Page {page_number} of {pdf_doc.page_count}:"}
                        )
                        content_blocks.append(
                            {
                                "type": "image",
                                "source": {"type": "base64", "media_type": "image/jpeg", "data": img_b64},
                            }
                        )
                        pages_used += 1
                finally:
                    pdf_doc.close()
        except Exception as exc:
            content_blocks.append(
                {"type": "text", "text": f"\n(Note: Could not attach selected page images: {exc}. Relying on text only.)\n"}
            )

    filenames = [doc.get("filename") for doc in doc_texts] or (doc_paths or [])
    async with record(
        "extract",
        model=MODEL_EXTRACT,
        meta={
            "docs": filenames,
            "pages_used": pages_used,
            "selected_pages": selected_pages_meta,
            "text_chars": sum(len(doc.get("text", "") or "") for doc in doc_texts),
            "mode": "cost_aware_selected_images",
        },
    ) as op:
        client = anthropic.AsyncAnthropic(api_key=api_key)
        op.note = "calling Anthropic (selected page images)"
        response_text = ""
        input_tokens = None
        output_tokens = None
        stop_reason = None
        async with client.messages.stream(
            model=MODEL_EXTRACT,
            max_tokens=32768,
            messages=[{"role": "user", "content": content_blocks}],
        ) as stream:
            async for text_chunk in stream.text_stream:
                response_text += text_chunk
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
                "Extraction response hit the max_tokens ceiling - Claude's JSON was truncated. "
                "Try fewer documents per extraction or a tighter prompt."
            )

        op.note = "received response, parsing"
        response_text = response_text.strip()
        op.response_preview = response_text[:2000]

        from app.services.deal_verifier import _parse_json_defensively

        metrics = _parse_json_defensively(response_text)
        if "underwriting_checks" not in metrics:
            metrics["underwriting_checks"] = {}
        if "sponsor_evaluation" not in metrics:
            metrics["sponsor_evaluation"] = {}

        op.note = "post-processing"
        _post_process_metrics(metrics)
        op.meta["top_level_keys"] = sorted(list(metrics.keys()))
        return metrics

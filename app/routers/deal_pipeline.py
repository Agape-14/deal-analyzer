import asyncio
import json
import logging
import os

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import async_session, get_db
from app.models import Deal
from app.rate_limit import limit
from app.services.canonical_metrics import annotate_canonical_metrics
from app.services import notifications as notif_svc
from app.services.confidence import summarize_math_checks
from app.services.data_integrity import (
    auto_resolve_conflicts,
    conflicts_to_flags,
    detect_conflicts,
    quality_summary,
    smart_merge,
    stamp_verification,
    staleness_flags,
    now_iso,
)
from app.services.deal_extractor_cost_aware import extract_metrics_from_docs
from app.services.deal_scorer import score_deal
from app.services.deal_validator import validate_deal_metrics
from app.services.deal_verifier import apply_corrections, verify_deal_metrics
from app.services.document_context import documents_fingerprint
from app.services.math_checker import run_math_checks

router = APIRouter()
log = logging.getLogger("kenyon.deal_pipeline")

EXTRACTION_CACHE_VERSION = 1


def _deep_conflict_scan_enabled() -> bool:
    """Opt-in expensive per-document AI extraction used only for diagnostics.

    The normal document review already runs one combined extraction across the
    full package, then a verification pass against source docs. Running a full
    AI extraction for each document before the combined extraction made two-doc
    deals perform three large Opus calls before verification even started.
    """
    return os.getenv("DEAL_REVIEW_DEEP_CONFLICT_SCAN", "").strip().lower() in {"1", "true", "yes"}


def _pipeline_status(
    status: str,
    step: str,
    message: str,
    *,
    started_at: str | None = None,
    error: str | None = None,
    error_kind: str | None = None,
    progress_pct: int | None = None,
    estimated_total_seconds: int | None = None,
) -> dict:
    now = now_iso()
    return {
        "status": status,
        "step": step,
        "message": message,
        "started_at": started_at or now,
        "updated_at": now,
        "error": error,
        "error_kind": error_kind,
        "progress_pct": _pipeline_progress(status, step, progress_pct),
        "estimated_total_seconds": estimated_total_seconds,
    }


def _pipeline_progress(status: str, step: str, explicit: int | None = None) -> int:
    if explicit is not None:
        return max(0, min(100, int(explicit)))
    status_name = str(status or "").lower()
    step_name = str(step or "").lower()
    if status_name == "complete":
        return 100
    if status_name == "extract_complete":
        return 45
    if status_name == "verify_complete":
        return 82
    if status_name == "failed":
        return 0
    if step_name == "extract":
        return 12
    if step_name == "verify":
        return 55
    if step_name == "score":
        return 92
    return 5


def _estimate_review_seconds(deal: Deal) -> int:
    """Return a conservative ETA for reading, verifying, and scoring docs.

    AI provider queueing and rate limits can dominate runtime, so this is only a
    planning estimate for the UI. It scales mainly by document type/count.
    """
    docs = list(deal.documents or [])
    if not docs:
        return 60
    pdf_count = len(_pdf_docs(deal))
    sheet_count = sum(
        1
        for doc in docs
        if str(doc.file_path or doc.filename or "").lower().endswith((".xlsx", ".xls", ".csv"))
    )
    text_only_count = max(0, len(docs) - pdf_count - sheet_count)
    seconds = 90 + (pdf_count * 120) + (sheet_count * 45) + (text_only_count * 25)
    return max(120, min(45 * 60, seconds))


def _ensure_metrics_dict(value, context: str) -> dict:
    """Return a metrics dict, accepting double-encoded JSON strings.

    Claude and older upload paths can occasionally hand us a JSON object
    encoded as a string. Without this guard, later merge code crashes with
    messages like "'str' object has no attribute 'keys'". Parse one or two
    layers, then fail with a user-readable error if it still is not an object.
    """
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return {}
        parsed = raw
        for _ in range(2):
            if not isinstance(parsed, str):
                break
            try:
                parsed = json.loads(parsed)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"{context} returned text instead of a JSON object. "
                    f"First 120 characters: {raw[:120]!r}. Parse error: {exc}"
                ) from exc
        if isinstance(parsed, dict):
            return parsed
        raise ValueError(f"{context} returned {type(parsed).__name__}, expected a JSON object.")
    raise ValueError(f"{context} returned {type(value).__name__}, expected a JSON object.")


def _set_pipeline_status(metrics: dict | None, status: dict) -> dict:
    next_metrics = _ensure_metrics_dict(metrics, "Stored deal metrics")
    existing = next_metrics.get("_pipeline") if isinstance(next_metrics.get("_pipeline"), dict) else {}
    if existing and not status.get("started_at"):
        status["started_at"] = existing.get("started_at")
    if existing and status.get("estimated_total_seconds") is None:
        status["estimated_total_seconds"] = existing.get("estimated_total_seconds")
    if existing and status.get("status") == "failed" and status.get("progress_pct") == 0:
        status["progress_pct"] = existing.get("progress_pct")
    next_metrics["_pipeline"] = status
    return next_metrics


def _pipeline_error_kind(error: Exception) -> str:
    text = str(error) or error.__class__.__name__
    lower = text.lower()
    if any(token in lower for token in ("credit", "credits", "quota", "balance", "billing", "payment", "insufficient_quota", "insufficient quota")):
        return "ai_quota"
    if ("rate" in lower and "limit" in lower) or "429" in lower or "too many requests" in lower:
        return "ai_rate_limit"
    if "overloaded" in lower or "529" in lower:
        return "ai_temporarily_unavailable"
    if "anthropic" in lower:
        return "ai_provider"
    return "unknown"


def _pipeline_error_message(error: Exception) -> str:
    text = str(error) or error.__class__.__name__
    kind = _pipeline_error_kind(error)
    if kind == "ai_quota":
        return "Document review incomplete: the AI provider quota or credit balance was exhausted. The deal was not fully re-read, verified, or rescored. Add API credits or update billing, then review documents again."
    if kind == "ai_rate_limit":
        return "Document review incomplete: the AI provider rate limit was reached. The deal was not fully re-read, verified, or rescored. Wait for the limit window to reset, then review documents again."
    if kind == "ai_temporarily_unavailable":
        return "Document review incomplete: the AI provider was temporarily unavailable or overloaded. The deal was not fully re-read, verified, or rescored. Wait a few minutes, then review documents again."
    if kind == "ai_provider":
        return f"Document review incomplete during the Anthropic AI call. The deal was not fully re-read, verified, or rescored. Details: {text[:420]}"
    return text[:500]


def _pdf_docs(deal: Deal):
    return [
        d
        for d in deal.documents
        if d.file_path and str(d.file_path).lower().endswith(".pdf")
    ]


def _doc_has_usable_text(doc) -> bool:
    text = (getattr(doc, "extracted_text", "") or "").strip()
    quality = getattr(doc, "extraction_quality", None) or {}
    if not text or text.startswith("Error extracting text:"):
        return False
    if isinstance(quality, dict) and quality.get("status") == "error":
        return False
    return True


def _usable_text_docs(deal: Deal):
    return [d for d in deal.documents if _doc_has_usable_text(d)]


@router.get("/{deal_id}/quality")
async def deal_quality(deal_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Deal).options(selectinload(Deal.documents)).where(Deal.id == deal_id))
    deal = result.scalar_one_or_none()
    if not deal:
        raise HTTPException(status_code=404, detail="Deal not found")
    metrics = _ensure_metrics_dict(deal.metrics, "Stored deal metrics")
    return {
        "summary": quality_summary(metrics),
        "stale_flags": staleness_flags(metrics, deal.documents or []),
        "pipeline": metrics.get("_pipeline"),
    }


@router.post("/{deal_id}/extract", dependencies=[Depends(limit("ai"))])
async def extract_deal_metrics(deal_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Deal).options(selectinload(Deal.documents)).where(Deal.id == deal_id)
    )
    deal = result.scalar_one_or_none()
    if not deal:
        raise HTTPException(status_code=404, detail="Deal not found")
    if not deal.documents:
        raise HTTPException(status_code=400, detail="No documents uploaded yet")

    usable_docs = _usable_text_docs(deal)
    usable_pdfs = _pdf_docs(deal)
    if not usable_docs and not usable_pdfs:
        raise HTTPException(status_code=400, detail="No extracted text or PDF files available")

    deal.metrics = _set_pipeline_status(
        deal.metrics,
        _pipeline_status(
            "running",
            "extract",
            "Document review started. Reading all uploaded documents.",
            progress_pct=10,
            estimated_total_seconds=_estimate_review_seconds(deal),
        ),
    )
    await db.commit()
    asyncio.ensure_future(_run_extract_background(deal_id))
    return {"message": "Document review started", "status": "started", "deal_id": deal_id}


@router.post("/{deal_id}/review", dependencies=[Depends(limit("ai"))])
async def review_deal_documents(deal_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Deal).options(selectinload(Deal.documents)).where(Deal.id == deal_id)
    )
    deal = result.scalar_one_or_none()
    if not deal:
        raise HTTPException(status_code=404, detail="Deal not found")
    if not deal.documents:
        raise HTTPException(status_code=400, detail="No documents uploaded yet")

    usable_docs = _usable_text_docs(deal)
    usable_pdfs = _pdf_docs(deal)
    if not usable_docs and not usable_pdfs:
        raise HTTPException(status_code=400, detail="No extracted text or PDF files available")

    deal.metrics = _set_pipeline_status(
        deal.metrics,
        _pipeline_status(
            "running",
            "extract",
            "Document review started. Reading all uploaded documents.",
            progress_pct=10,
            estimated_total_seconds=_estimate_review_seconds(deal),
        ),
    )
    await db.commit()
    asyncio.ensure_future(_run_document_review_background(deal_id))
    return {"message": "Document review started", "status": "started", "deal_id": deal_id}


async def _run_document_review_background(deal_id: int):
    """Run the full document review as one backend-owned job.

    The browser should not be responsible for sequencing extraction,
    verification, and scoring. If it disconnects or times out, the backend
    keeps the review moving and persists the real status for the UI to poll.
    """
    await _run_extract_background(deal_id)
    status = await _pipeline_for_deal(deal_id)
    if str(status.get("status") or "").lower() != "extract_complete":
        return

    await _mark_pipeline_running(
        deal_id,
        "verify",
        "Documents read. Checking extracted values against source documents.",
        progress_pct=55,
    )
    await _run_verify_background(deal_id, True)
    status = await _pipeline_for_deal(deal_id)
    if str(status.get("status") or "").lower() != "verify_complete":
        return

    await _run_score_background(deal_id)


async def _mark_pipeline_running(deal_id: int, step: str, message: str, *, progress_pct: int) -> None:
    async with async_session() as db:
        result = await db.execute(select(Deal).where(Deal.id == deal_id))
        deal = result.scalar_one_or_none()
        if not deal:
            return
        existing_metrics = _ensure_metrics_dict(deal.metrics, "Stored deal metrics")
        started_at = existing_metrics.get("_pipeline", {}).get("started_at") if isinstance(existing_metrics.get("_pipeline"), dict) else None
        deal.metrics = _set_pipeline_status(
            existing_metrics,
            _pipeline_status(
                "running",
                step,
                message,
                started_at=started_at,
                progress_pct=progress_pct,
            ),
        )
        await db.commit()


async def _pipeline_for_deal(deal_id: int) -> dict:
    async with async_session() as db:
        result = await db.execute(select(Deal).where(Deal.id == deal_id))
        deal = result.scalar_one_or_none()
        if not deal:
            return {}
        metrics = _ensure_metrics_dict(deal.metrics, "Stored deal metrics")
        pipeline = metrics.get("_pipeline")
        return pipeline if isinstance(pipeline, dict) else {}


async def _run_extract_background(deal_id: int):
    async with async_session() as db:
        try:
            result = await db.execute(
                select(Deal).options(selectinload(Deal.documents)).where(Deal.id == deal_id)
            )
            deal = result.scalar_one_or_none()
            if not deal or not deal.documents:
                return

            existing_metrics = _ensure_metrics_dict(deal.metrics, "Stored deal metrics")
            docs_fp = documents_fingerprint(deal.documents or [])
            extraction_cache = existing_metrics.get("_document_review_cache")
            if not isinstance(extraction_cache, dict):
                extraction_cache = {}
            usable_docs = _usable_text_docs(deal)
            usable_pdfs = _pdf_docs(deal)
            per_doc_results: list[tuple[int, str, dict]] = []

            incoming_metrics = None
            cache_hit = False
            cached_metrics = extraction_cache.get("extraction_metrics")
            if (
                extraction_cache.get("cache_version") == EXTRACTION_CACHE_VERSION
                and extraction_cache.get("documents_fingerprint") == docs_fp
                and isinstance(cached_metrics, dict)
            ):
                incoming_metrics = _ensure_metrics_dict(cached_metrics, "Cached document extraction")
                cache_hit = True
                log.info("Using cached extraction for deal %s docs_fp=%s", deal_id, docs_fp[:12])

            if not cache_hit and len(deal.documents) > 1 and _deep_conflict_scan_enabled():
                for doc in deal.documents:
                    text = doc.extracted_text or ""
                    path = doc.file_path if doc in usable_pdfs else None
                    if not text and not path:
                        continue
                    one_doc_text = (
                        [{"filename": doc.filename, "doc_type": doc.doc_type, "text": text}]
                        if text
                        else []
                    )
                    try:
                        mx = await extract_metrics_from_docs(one_doc_text, doc_paths=[path] if path else [])
                        mx = _ensure_metrics_dict(mx, f"Extraction for {doc.filename}")
                        per_doc_results.append((doc.id, doc.filename, mx))
                    except Exception:
                        log.exception("per-document extraction failed for deal %s doc %s", deal_id, doc.id)

            doc_texts = [
                {"filename": d.filename, "doc_type": d.doc_type, "text": d.extracted_text or ""}
                for d in usable_docs
            ]
            if incoming_metrics is None:
                incoming_metrics = await extract_metrics_from_docs(
                    doc_texts,
                    doc_paths=[d.file_path for d in usable_pdfs],
                )
                incoming_metrics = _ensure_metrics_dict(incoming_metrics, "Document extraction")

            primary_doc = usable_docs[0] if len(usable_docs) == 1 else None
            merged, changes = smart_merge(
                existing_metrics,
                incoming_metrics,
                source_doc_id=primary_doc.id if primary_doc else None,
                source_doc_name=primary_doc.filename if primary_doc else "multiple documents",
            )

            conflicts = detect_conflicts(per_doc_results) if len(per_doc_results) >= 2 else {}
            n_auto_resolved = 0
            if conflicts:
                doc_upload_dates = {d.id: d.upload_date for d in deal.documents}
                n_auto_resolved = auto_resolve_conflicts(conflicts, merged, doc_upload_dates)
                prov = dict(merged.get("_provenance") or {})
                for path, entries in conflicts.items():
                    if any(e.get("auto_resolved") for e in entries):
                        continue
                    existing_prov = prov.get(path, {})
                    existing_prov["conflict"] = entries
                    prov[path] = existing_prov
                merged["_provenance"] = prov

            merged["_document_review_cache"] = {
                "cache_version": EXTRACTION_CACHE_VERSION,
                "documents_fingerprint": docs_fp,
                "extraction_metrics": incoming_metrics,
                "document_count": len(deal.documents),
                "updated_at": now_iso(),
            }

            history = list(merged.get("_extraction_history") or [])
            history.append(
                {
                    "at": now_iso(),
                    "changes": changes[:50],
                    "doc_count": len(deal.documents),
                    "conflicts": list(conflicts.keys()),
                    "cache_hit": cache_hit,
                }
            )
            merged["_extraction_history"] = history[-20:]

            validation_flags = validate_deal_metrics(merged, deal.property_type)
            validation_flags.extend(conflicts_to_flags(conflicts))
            validation_flags.extend(staleness_flags(merged, deal.documents))
            merged["validation_flags"] = validation_flags
            merged = annotate_canonical_metrics(merged)
            merged["_pipeline"] = _pipeline_status(
                "extract_complete",
                "extract",
                "Documents read. Source verification still needs to finish before the score can be trusted.",
                started_at=existing_metrics.get("_pipeline", {}).get("started_at")
                if isinstance(existing_metrics.get("_pipeline"), dict)
                else None,
                progress_pct=45,
            )

            deal.metrics = merged
            ml = merged.get("market_location", {}) or {}
            if not deal.city and ml.get("city"):
                deal.city = ml["city"]
            if not deal.state and ml.get("state"):
                deal.state = ml["state"]

            n_unresolved_conflicts = len(conflicts) - n_auto_resolved
            reds = [f for f in validation_flags if f.get("severity") == "red"]
            body_parts = [
                "reused prior extraction" if cache_hit else f"{len(changes)} field{'s' if len(changes) != 1 else ''} updated"
            ]
            if n_auto_resolved:
                body_parts.append(f"{n_auto_resolved} conflict{'s' if n_auto_resolved != 1 else ''} auto-resolved")
            if n_unresolved_conflicts:
                body_parts.append(f"{n_unresolved_conflicts} unresolved conflict{'s' if n_unresolved_conflicts != 1 else ''}")
            if reds:
                body_parts.append(f"{len(reds)} red flag{'s' if len(reds) != 1 else ''}")
            await notif_svc.emit(
                db,
                kind="error" if n_unresolved_conflicts or reds else "success",
                title=f"Metrics extracted for {deal.project_name}",
                body=" - ".join(body_parts),
                href=f"/deals/{deal.id}?tab=overview",
                payload={"deal_id": deal.id, "changes": len(changes), "red_flags": len(reds), "cache_hit": cache_hit},
            )
            await db.commit()
        except Exception as e:
            log.exception("extract pipeline failed for deal %s", deal_id)
            await _persist_pipeline_failure(db, deal_id, "extract", "Document reading failed.", e)


@router.post("/{deal_id}/verify", dependencies=[Depends(limit("ai"))])
async def verify_deal_endpoint(deal_id: int, auto_correct: bool = True, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Deal).options(selectinload(Deal.documents)).where(Deal.id == deal_id)
    )
    deal = result.scalar_one_or_none()
    if not deal:
        raise HTTPException(status_code=404, detail="Deal not found")
    if not deal.metrics:
        raise HTTPException(status_code=400, detail="No metrics extracted yet. Run extraction first.")

    deal.metrics = _set_pipeline_status(
        deal.metrics,
        _pipeline_status("running", "verify", "Source verification started. Checking extracted values against source documents."),
    )
    await db.commit()
    asyncio.ensure_future(_run_verify_background(deal_id, auto_correct))
    return {"message": "Source verification started", "status": "started", "deal_id": deal_id}


async def _run_verify_background(deal_id: int, auto_correct: bool):
    async with async_session() as db:
        try:
            result = await db.execute(
                select(Deal).options(selectinload(Deal.documents)).where(Deal.id == deal_id)
            )
            deal = result.scalar_one_or_none()
            if not deal or not deal.metrics:
                return

            verification = await verify_deal_metrics(deal, db)
            metrics = _ensure_metrics_dict(deal.metrics, "Stored deal metrics")
            changes: list[str] = []
            if auto_correct:
                metrics, changes = apply_corrections(metrics, verification)
            metrics = stamp_verification(metrics, verification)

            math_results = run_math_checks(metrics)
            metrics["_math_checks"] = {
                "checked_at": now_iso(),
                "summary": summarize_math_checks(math_results, metrics),
                "results": math_results,
            }
            flags = validate_deal_metrics(metrics, deal.property_type)
            flags.extend(staleness_flags(metrics, deal.documents or []))
            metrics["validation_flags"] = flags
            metrics = annotate_canonical_metrics(metrics)
            metrics["_pipeline"] = _pipeline_status(
                "verify_complete",
                "verify",
                "Sources checked. Values are ready for scoring.",
                started_at=(deal.metrics or {}).get("_pipeline", {}).get("started_at")
                if isinstance((deal.metrics or {}).get("_pipeline"), dict)
                else None,
                progress_pct=82,
            )
            deal.metrics = metrics
            deal.scores = score_deal(metrics, math_checks=math_results)
            await notif_svc.emit(
                db,
                kind="success",
                title=f"Verification complete - {deal.project_name}",
                body=f"{len(changes)} correction{'s' if len(changes) != 1 else ''} applied",
                href=f"/deals/{deal.id}?tab=overview",
                payload={"deal_id": deal.id, "corrections": len(changes)},
            )
            await db.commit()
        except Exception as e:
            log.exception("verify pipeline failed for deal %s", deal_id)
            await _persist_pipeline_failure(db, deal_id, "verify", "Source verification failed.", e)


@router.post("/{deal_id}/score", dependencies=[Depends(limit("write"))])
async def score_deal_endpoint(deal_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Deal).where(Deal.id == deal_id))
    deal = result.scalar_one_or_none()
    if not deal:
        raise HTTPException(status_code=404, detail="Deal not found")
    if not deal.metrics:
        raise HTTPException(status_code=400, detail="No metrics extracted yet. Run extraction first.")

    deal.metrics = _set_pipeline_status(
        deal.metrics,
        _pipeline_status("running", "score", "Updating score. Rechecking validation, math checks, and score."),
    )
    await db.commit()
    try:
        metrics = _ensure_metrics_dict(deal.metrics, "Stored deal metrics")
        metrics = annotate_canonical_metrics(metrics)
        scores = score_deal(metrics)
    except Exception as e:
        await _persist_pipeline_failure(db, deal_id, "score", "Score update failed.", e)
        raise HTTPException(status_code=503, detail=_pipeline_error_message(e))

    deal.scores = scores
    deal.metrics = _set_pipeline_status(
        metrics,
        _pipeline_status("complete", "score", "Document review complete. Values were extracted, source-checked, math-checked, and scored."),
    )
    await db.commit()
    return {"message": "Deal scored", "scores": scores}


async def _run_score_background(deal_id: int):
    async with async_session() as db:
        result = await db.execute(select(Deal).where(Deal.id == deal_id))
        deal = result.scalar_one_or_none()
        if not deal or not deal.metrics:
            return

        existing_metrics = _ensure_metrics_dict(deal.metrics, "Stored deal metrics")
        started_at = existing_metrics.get("_pipeline", {}).get("started_at") if isinstance(existing_metrics.get("_pipeline"), dict) else None
        deal.metrics = _set_pipeline_status(
            existing_metrics,
            _pipeline_status(
                "running",
                "score",
                "Updating score. Rechecking validation, math checks, and score.",
                started_at=started_at,
                progress_pct=92,
            ),
        )
        await db.commit()
        try:
            metrics = _ensure_metrics_dict(deal.metrics, "Stored deal metrics")
            metrics = annotate_canonical_metrics(metrics)
            math_checks = metrics.get("_math_checks", {})
            results = math_checks.get("results") if isinstance(math_checks, dict) else None
            scores = score_deal(metrics, math_checks=results if isinstance(results, list) else None)
        except Exception as e:
            await _persist_pipeline_failure(db, deal_id, "score", "Score update failed.", e)
            return

        deal.scores = scores
        deal.metrics = _set_pipeline_status(
            metrics,
            _pipeline_status(
                "complete",
                "score",
                "Document review complete. Values were extracted, source-checked, math-checked, and scored.",
                started_at=started_at,
                progress_pct=100,
            ),
        )
        await notif_svc.emit(
            db,
            kind="success",
            title=f"Document review complete - {deal.project_name}",
            body="Values were extracted, source-checked, math-checked, and scored.",
            href=f"/deals/{deal.id}?tab=overview",
            payload={"deal_id": deal.id},
        )
        await db.commit()


async def _persist_pipeline_failure(db: AsyncSession, deal_id: int, step: str, message: str, error: Exception) -> None:
    try:
        await db.rollback()
        result = await db.execute(select(Deal).where(Deal.id == deal_id))
        deal = result.scalar_one_or_none()
        if not deal:
            return
        error_message = _pipeline_error_message(error)
        error_kind = _pipeline_error_kind(error)
        deal.metrics = _set_pipeline_status(
            deal.metrics,
            _pipeline_status("failed", step, message, error=error_message, error_kind=error_kind),
        )
        await notif_svc.emit(
            db,
            kind="error",
            title=f"Document review stopped - {deal.project_name}",
            body=error_message,
            href=f"/deals/{deal.id}?tab=overview",
            payload={"deal_id": deal.id, "step": step, "error": error_message, "error_kind": error_kind},
        )
        await db.commit()
    except Exception:
        log.exception("failed to persist pipeline failure for deal %s", deal_id)

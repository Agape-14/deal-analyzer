import asyncio
import logging

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
from app.services.deal_extractor import extract_metrics_from_docs
from app.services.deal_scorer import score_deal
from app.services.deal_validator import validate_deal_metrics
from app.services.deal_verifier import apply_corrections, verify_deal_metrics
from app.services.math_checker import run_math_checks
from app.services.pipeline_runs import (
    attach_run_status,
    get_latest_pipeline_run,
    get_pipeline_run,
    run_to_dict,
    start_pipeline_run,
    update_pipeline_run,
)

router = APIRouter()
log = logging.getLogger("kenyon.deal_pipeline")


def _pipeline_status(
    status: str,
    step: str,
    message: str,
    *,
    started_at: str | None = None,
    error: str | None = None,
) -> dict:
    now = now_iso()
    return {
        "status": status,
        "step": step,
        "message": message,
        "started_at": started_at or now,
        "updated_at": now,
        "error": error,
    }


def _set_pipeline_status(metrics: dict | None, status: dict) -> dict:
    next_metrics = dict(metrics or {})
    existing = next_metrics.get("_pipeline") if isinstance(next_metrics.get("_pipeline"), dict) else {}
    if existing and not status.get("started_at"):
        status["started_at"] = existing.get("started_at")
    next_metrics["_pipeline"] = status
    return next_metrics


def _active_run_id(metrics: dict | None) -> int | None:
    pipeline = (metrics or {}).get("_pipeline")
    if not isinstance(pipeline, dict):
        return None
    try:
        return int(pipeline.get("run_id"))
    except (TypeError, ValueError):
        return None


def _pipeline_error_message(error: Exception) -> str:
    text = str(error) or error.__class__.__name__
    lower = text.lower()
    if "rate" in lower and "limit" in lower:
        return "Pipeline stopped because the AI provider rate limit was reached. Wait a few minutes, then re-run the pipeline."
    if "429" in lower or "too many requests" in lower:
        return "Pipeline stopped because the AI provider returned a rate-limit error. Wait a few minutes, then re-run the pipeline."
    if "anthropic" in lower:
        return f"Pipeline stopped during the Anthropic AI call: {text[:420]}"
    return text[:500]


def _pdf_docs(deal: Deal):
    return [
        d
        for d in deal.documents
        if d.file_path and str(d.file_path).lower().endswith(".pdf")
    ]


@router.get("/{deal_id}/quality")
async def deal_quality(deal_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Deal).options(selectinload(Deal.documents)).where(Deal.id == deal_id))
    deal = result.scalar_one_or_none()
    if not deal:
        raise HTTPException(status_code=404, detail="Deal not found")
    metrics = deal.metrics or {}
    latest_run = await get_latest_pipeline_run(db, deal.id)
    return {
        "summary": quality_summary(metrics),
        "stale_flags": staleness_flags(metrics, deal.documents or []),
        "pipeline": metrics.get("_pipeline"),
        "latest_pipeline_run": run_to_dict(latest_run),
    }


@router.get("/{deal_id}/validate")
async def validate_deal(deal_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Deal).where(Deal.id == deal_id))
    deal = result.scalar_one_or_none()
    if not deal:
        raise HTTPException(status_code=404, detail="Deal not found")
    if not deal.metrics:
        raise HTTPException(status_code=400, detail="No metrics extracted yet. Run extraction first.")

    flags = validate_deal_metrics(deal.metrics, deal.property_type)
    metrics = dict(deal.metrics or {})
    metrics["validation_flags"] = flags
    deal.metrics = metrics
    await db.commit()
    return {
        "flags": flags,
        "summary": {
            "red": len([f for f in flags if f.get("severity") == "red"]),
            "yellow": len([f for f in flags if f.get("severity") == "yellow"]),
            "green": len([f for f in flags if f.get("severity") == "green"]),
        },
    }


@router.get("/{deal_id}/math-check")
async def math_check_deal(deal_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Deal).where(Deal.id == deal_id))
    deal = result.scalar_one_or_none()
    if not deal:
        raise HTTPException(status_code=404, detail="Deal not found")
    if not deal.metrics:
        raise HTTPException(status_code=400, detail="No metrics extracted yet.")

    checks = run_math_checks(deal.metrics)
    summary = {
        "pass": len([c for c in checks if c.get("status") == "pass"]),
        "fail": len([c for c in checks if c.get("status") == "fail"]),
        "warn": len([c for c in checks if c.get("status") == "warn"]),
        "info": len([c for c in checks if c.get("status") == "info"]),
        "total": len(checks),
    }
    return {"checks": checks, "summary": summary}


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

    usable_docs = [d for d in deal.documents if (d.extracted_text or "")]
    usable_pdfs = _pdf_docs(deal)
    if not usable_docs and not usable_pdfs:
        raise HTTPException(status_code=400, detail="No extracted text or PDF files available")

    run = await start_pipeline_run(
        db,
        deal,
        trigger="manual",
        step="extract",
        message="Extraction started. Reading all uploaded documents.",
    )
    await db.commit()
    asyncio.ensure_future(_run_extract_background(deal_id, run.id))
    return {
        "message": "Extraction started",
        "status": "started",
        "deal_id": deal_id,
        "pipeline_run": run_to_dict(run),
    }


async def _run_extract_background(deal_id: int, run_id: int | None = None):
    async with async_session() as db:
        try:
            result = await db.execute(
                select(Deal).options(selectinload(Deal.documents)).where(Deal.id == deal_id)
            )
            deal = result.scalar_one_or_none()
            if not deal or not deal.documents:
                return

            usable_docs = [d for d in deal.documents if (d.extracted_text or "")]
            usable_pdfs = _pdf_docs(deal)
            per_doc_results: list[tuple[int, str, dict]] = []
            if len(deal.documents) > 1:
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
                        per_doc_results.append((doc.id, doc.filename, mx))
                    except Exception:
                        log.exception("per-document extraction failed for deal %s doc %s", deal_id, doc.id)

            doc_texts = [
                {"filename": d.filename, "doc_type": d.doc_type, "text": d.extracted_text or ""}
                for d in usable_docs
            ]
            incoming_metrics = await extract_metrics_from_docs(
                doc_texts,
                doc_paths=[d.file_path for d in usable_pdfs],
            )

            primary_doc = usable_docs[0] if len(usable_docs) == 1 else None
            merged, changes = smart_merge(
                deal.metrics,
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

            history = list(merged.get("_extraction_history") or [])
            history.append(
                {
                    "at": now_iso(),
                    "changes": changes[:50],
                    "doc_count": len(deal.documents),
                    "conflicts": list(conflicts.keys()),
                }
            )
            merged["_extraction_history"] = history[-20:]

            validation_flags = validate_deal_metrics(merged, deal.property_type)
            validation_flags.extend(conflicts_to_flags(conflicts))
            validation_flags.extend(staleness_flags(merged, deal.documents))
            merged["validation_flags"] = validation_flags
            merged = annotate_canonical_metrics(merged)
            run = await update_pipeline_run(
                db,
                run_id,
                status="extract_complete",
                step="extract",
                message="Extraction complete. Values are ready for source verification.",
                summary={
                    "changes": len(changes),
                    "doc_count": len(deal.documents),
                    "conflicts": len(conflicts),
                    "red_flags": len([f for f in validation_flags if f.get("severity") == "red"]),
                },
            )
            if run:
                merged = attach_run_status(merged, run)
            else:
                merged["_pipeline"] = _pipeline_status(
                    "extract_complete",
                    "extract",
                    "Extraction complete. Values are ready for source verification.",
                    started_at=(deal.metrics or {}).get("_pipeline", {}).get("started_at")
                    if isinstance((deal.metrics or {}).get("_pipeline"), dict)
                    else None,
                )

            deal.metrics = merged
            ml = merged.get("market_location", {}) or {}
            if not deal.city and ml.get("city"):
                deal.city = ml["city"]
            if not deal.state and ml.get("state"):
                deal.state = ml["state"]
            try:
                deal.scores = score_deal(merged)
            except Exception:
                log.exception("score refresh after extraction failed for deal %s", deal_id)

            n_unresolved_conflicts = len(conflicts) - n_auto_resolved
            reds = [f for f in validation_flags if f.get("severity") == "red"]
            body_parts = [f"{len(changes)} field{'s' if len(changes) != 1 else ''} updated"]
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
                payload={"deal_id": deal.id, "changes": len(changes), "red_flags": len(reds)},
            )
            await db.commit()
        except Exception as e:
            log.exception("extract pipeline failed for deal %s", deal_id)
            await _persist_pipeline_failure(db, deal_id, "extract", "Extraction failed.", e, run_id=run_id)


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

    run = await get_pipeline_run(db, _active_run_id(deal.metrics))
    if run and run.status not in {"failed", "complete", "cancelled"}:
        run = await update_pipeline_run(
            db,
            run.id,
            status="running",
            step="verify",
            message="Verification started. Checking extracted values against source documents.",
        )
        deal.metrics = attach_run_status(deal.metrics, run)
    else:
        run = await start_pipeline_run(
            db,
            deal,
            trigger="manual_verify",
            step="verify",
            message="Verification started. Checking extracted values against source documents.",
        )
    await db.commit()
    asyncio.ensure_future(_run_verify_background(deal_id, auto_correct, run.id))
    return {
        "message": "Verification started",
        "status": "started",
        "deal_id": deal_id,
        "pipeline_run": run_to_dict(run),
    }


async def _run_verify_background(deal_id: int, auto_correct: bool, run_id: int | None = None):
    async with async_session() as db:
        try:
            result = await db.execute(
                select(Deal).options(selectinload(Deal.documents)).where(Deal.id == deal_id)
            )
            deal = result.scalar_one_or_none()
            if not deal or not deal.metrics:
                return

            verification = await verify_deal_metrics(deal, db)
            metrics = dict(deal.metrics or {})
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
            run = await update_pipeline_run(
                db,
                run_id,
                status="verify_complete",
                step="verify",
                message="Verification complete. Values are ready to be scored.",
                summary={
                    "corrections": len(changes),
                    "math_failures": (metrics.get("_math_checks") or {}).get("summary", {}).get("fail", 0),
                    "math_warnings": (metrics.get("_math_checks") or {}).get("summary", {}).get("warn", 0),
                },
            )
            if run:
                metrics = attach_run_status(metrics, run)
            else:
                metrics["_pipeline"] = _pipeline_status(
                    "verify_complete",
                    "verify",
                    "Verification complete. Values are ready to be scored.",
                    started_at=(deal.metrics or {}).get("_pipeline", {}).get("started_at")
                    if isinstance((deal.metrics or {}).get("_pipeline"), dict)
                    else None,
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
            await _persist_pipeline_failure(db, deal_id, "verify", "Verification failed.", e, run_id=run_id)


@router.post("/{deal_id}/score", dependencies=[Depends(limit("write"))])
async def score_deal_endpoint(deal_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Deal).where(Deal.id == deal_id))
    deal = result.scalar_one_or_none()
    if not deal:
        raise HTTPException(status_code=404, detail="Deal not found")
    if not deal.metrics:
        raise HTTPException(status_code=400, detail="No metrics extracted yet. Run extraction first.")

    run = await get_pipeline_run(db, _active_run_id(deal.metrics))
    if run and run.status not in {"failed", "complete", "cancelled"}:
        run = await update_pipeline_run(
            db,
            run.id,
            status="running",
            step="score",
            message="Scoring started. Recalculating validation, math checks, and score.",
        )
        deal.metrics = attach_run_status(deal.metrics, run)
    else:
        run = await start_pipeline_run(
            db,
            deal,
            trigger="manual_score",
            step="score",
            message="Scoring started. Recalculating validation, math checks, and score.",
        )
    await db.commit()
    try:
        metrics = annotate_canonical_metrics(deal.metrics)
        scores = score_deal(metrics)
    except Exception as e:
        await _persist_pipeline_failure(db, deal_id, "score", "Scoring failed.", e, run_id=run.id if run else None)
        raise HTTPException(status_code=503, detail=_pipeline_error_message(e))

    deal.scores = scores
    run = await update_pipeline_run(
        db,
        run.id if run else None,
        status="complete",
        step="score",
        message="Pipeline complete. Extraction, verification, math checks, and scoring finished.",
        summary={"score": scores.get("overall_score") if isinstance(scores, dict) else None},
    )
    deal.metrics = attach_run_status(metrics, run) if run else _set_pipeline_status(
        metrics,
        _pipeline_status("complete", "score", "Pipeline complete. Extraction, verification, math checks, and scoring finished."),
    )
    await db.commit()
    return {"message": "Deal scored", "scores": scores, "pipeline_run": run_to_dict(run)}


async def _persist_pipeline_failure(
    db: AsyncSession,
    deal_id: int,
    step: str,
    message: str,
    error: Exception,
    *,
    run_id: int | None = None,
) -> None:
    try:
        await db.rollback()
        result = await db.execute(select(Deal).where(Deal.id == deal_id))
        deal = result.scalar_one_or_none()
        if not deal:
            return
        error_message = _pipeline_error_message(error)
        run = await update_pipeline_run(
            db,
            run_id or _active_run_id(deal.metrics),
            status="failed",
            step=step,
            message=message,
            error=error_message,
        )
        deal.metrics = attach_run_status(deal.metrics, run) if run else _set_pipeline_status(
            deal.metrics,
            _pipeline_status("failed", step, message, error=error_message),
        )
        await notif_svc.emit(
            db,
            kind="error",
            title=f"Pipeline stopped - {deal.project_name}",
            body=error_message,
            href=f"/deals/{deal.id}?tab=overview",
            payload={"deal_id": deal.id, "step": step, "error": error_message},
        )
        await db.commit()
    except Exception:
        log.exception("failed to persist pipeline failure for deal %s", deal_id)

"""Backend-owned deal pipeline runner.

The UI can start extraction, but the browser should not be responsible for the
high-confidence part of the workflow. This lightweight worker runs in the API
process and looks for deals whose extracted metrics have not yet been verified
against the source documents. It then runs:

    verification -> deterministic math checks -> confidence gates -> scoring

That keeps deal scoring from depending on an operator clicking a second button
or leaving a browser tab open.
"""

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.database import async_session
from app.models import Deal
from app.services.confidence import assess_data_quality, summarize_math_checks
from app.services.data_integrity import now_iso, staleness_flags, stamp_verification
from app.services.deal_scorer import score_deal
from app.services.deal_validator import validate_deal_metrics
from app.services.deal_verifier import apply_corrections, verify_deal_metrics
from app.services.math_checker import run_math_checks
from app.services import notifications as notif_svc
from app.services.pipeline_runs import attach_run_status, start_pipeline_run, update_pipeline_run

log = logging.getLogger("kenyon.pipeline")

DEFAULT_INTERVAL_SECONDS = 20
DEFAULT_BATCH_SIZE = 2
RUNNING_TIMEOUT_SECONDS = 30 * 60


def start_pipeline_runner() -> Optional[asyncio.Task]:
    """Start the background verifier unless disabled by env."""
    enabled = os.getenv("DEAL_PIPELINE_RUNNER", "1").strip().lower() not in {"0", "false", "no"}
    if not enabled:
        log.info("deal pipeline runner disabled")
        return None
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        log.warning("deal pipeline runner skipped: no running event loop")
        return None
    task = loop.create_task(_run_loop(), name="deal-pipeline-runner")
    log.info("deal pipeline runner started")
    return task


async def stop_pipeline_runner(task: Optional[asyncio.Task]) -> None:
    if not task:
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        log.info("deal pipeline runner stopped")


async def _run_loop() -> None:
    interval = _env_int("DEAL_PIPELINE_INTERVAL_SECONDS", DEFAULT_INTERVAL_SECONDS)
    while True:
        try:
            await process_pending_deals()
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("deal pipeline scan failed")
        await asyncio.sleep(max(5, interval))


async def process_pending_deals() -> int:
    """Verify and score a small batch of deals that need backend follow-through."""
    batch_size = _env_int("DEAL_PIPELINE_BATCH_SIZE", DEFAULT_BATCH_SIZE)
    processed = 0

    async with async_session() as db:
        result = await db.execute(
            select(Deal)
            .options(selectinload(Deal.documents))
            .where(Deal.deleted_at.is_(None))
            .order_by(Deal.created_at.desc())
            .limit(50)
        )
        candidates = result.scalars().all()

        for deal in candidates:
            if processed >= batch_size:
                break
            if not _needs_backend_verification(deal.metrics or {}):
                continue
            await _verify_score_and_commit(db, deal)
            processed += 1

    if processed:
        log.info("deal pipeline processed %d deal(s)", processed)
    return processed


def _needs_backend_verification(metrics: dict[str, Any]) -> bool:
    if not metrics:
        return False

    latest_extracted = _latest_extracted_at(metrics)
    if latest_extracted is None:
        return False

    pipeline = metrics.get("_pipeline") or {}
    if isinstance(pipeline, dict):
        status = str(pipeline.get("verify_status") or "").lower()
        started = _parse_iso(pipeline.get("verify_started_at"))
        finished = _parse_iso(pipeline.get("verify_finished_at"))

        if status == "running" and started and _age_seconds(started) < RUNNING_TIMEOUT_SECONDS:
            return False
        if status == "failed" and finished and finished >= latest_extracted:
            return False

    verified_at = _parse_iso(((metrics.get("_verification") or {}) if isinstance(metrics.get("_verification"), dict) else {}).get("verified_at"))
    if verified_at is None:
        return True
    return latest_extracted > verified_at


async def _verify_score_and_commit(db, deal: Deal) -> None:
    run = await start_pipeline_run(
        db,
        deal,
        trigger="backend_runner",
        step="verify",
        message="Backend verification started after a document update.",
    )
    metrics = dict(deal.metrics or {})
    pipeline = dict(metrics.get("_pipeline") or {})
    pipeline.update(
        {
            "verify_status": "running",
            "verify_started_at": now_iso(),
            "verify_source": "backend_pipeline",
            "last_error": None,
        }
    )
    metrics["_pipeline"] = pipeline
    deal.metrics = attach_run_status(metrics, run)
    await db.commit()

    try:
        verification = await verify_deal_metrics(deal, db)
        metrics = dict(deal.metrics or {})
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
        metrics["_data_quality"] = assess_data_quality(metrics, math_checks=math_results)

        pipeline = dict(metrics.get("_pipeline") or {})
        pipeline.update(
            {
                "verify_status": "complete",
                "verify_finished_at": now_iso(),
                "corrections_applied": len(changes),
                "last_error": None,
            }
        )
        metrics["_pipeline"] = pipeline
        run = await update_pipeline_run(
            db,
            run.id,
            status="complete",
            step="score",
            message="Backend pipeline complete. Verification, math checks, and scoring finished.",
            summary={
                "corrections": len(changes),
                "math_failures": (metrics.get("_math_checks") or {}).get("summary", {}).get("fail", 0),
                "math_warnings": (metrics.get("_math_checks") or {}).get("summary", {}).get("warn", 0),
            },
        )

        deal.metrics = attach_run_status(metrics, run)
        deal.scores = score_deal(metrics, math_checks=math_results, require_verified=True)
        await _emit_verification_notification(db, deal, verification, len(changes))
        await db.commit()
    except Exception as exc:
        log.exception("backend pipeline failed for deal %s", deal.id)
        metrics = dict(deal.metrics or {})
        pipeline = dict(metrics.get("_pipeline") or {})
        pipeline.update(
            {
                "verify_status": "failed",
                "verify_finished_at": now_iso(),
                "last_error": str(exc),
            }
        )
        metrics["_pipeline"] = pipeline
        run = await update_pipeline_run(
            db,
            run.id,
            status="failed",
            step="verify",
            message="Backend verification failed.",
            error=str(exc)[:500],
        )
        deal.metrics = attach_run_status(metrics, run)
        await db.commit()


async def _emit_verification_notification(db, deal: Deal, verification: dict[str, Any], corrections: int) -> None:
    vsummary = (verification or {}).get("summary") or {}
    confidence = vsummary.get("confidence_score")
    totals: dict[str, int] = {}
    for row in (verification or {}).get("audit_results", []) or []:
        status = str(row.get("status") or "").lower()
        totals[status] = totals.get(status, 0) + 1

    wrong = totals.get("wrong", 0)
    missing = totals.get("missing", 0)
    body_parts = []
    if confidence is not None:
        body_parts.append(f"{confidence}% confidence")
    if corrections:
        body_parts.append(f"{corrections} correction{'s' if corrections != 1 else ''} applied")
    if wrong:
        body_parts.append(f"{wrong} wrong")
    if missing:
        body_parts.append(f"{missing} missing")

    await notif_svc.emit(
        db,
        kind="warning" if wrong or missing else "success",
        title=f"Verification complete - {deal.project_name}",
        body=" · ".join(body_parts) if body_parts else "All extracted values match the source docs.",
        href=f"/deals/{deal.id}?tab=overview",
        payload={"deal_id": deal.id, **totals, "confidence": confidence, "backend_pipeline": True},
    )


def _latest_extracted_at(metrics: dict[str, Any]) -> Optional[datetime]:
    latest: Optional[datetime] = None
    provenance = metrics.get("_provenance") or {}
    if not isinstance(provenance, dict):
        return None
    for value in provenance.values():
        if not isinstance(value, dict):
            continue
        extracted_at = _parse_iso(value.get("extracted_at"))
        if extracted_at and (latest is None or extracted_at > latest):
            latest = extracted_at
    return latest


def _parse_iso(value: Any) -> Optional[datetime]:
    if not value or not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _age_seconds(value: datetime) -> float:
    return (datetime.now(timezone.utc) - value).total_seconds()


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default

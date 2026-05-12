from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Deal, PipelineRun
from app.services.data_integrity import now_iso


def _now_dt() -> datetime:
    return datetime.now(timezone.utc)


def _step_entry(status: str, step: str, message: str, error: str | None = None) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "status": status,
        "step": step,
        "message": message,
        "at": now_iso(),
    }
    if error:
        entry["error"] = error
    return entry


def run_to_dict(run: PipelineRun | None) -> dict[str, Any] | None:
    if not run:
        return None
    return {
        "id": run.id,
        "deal_id": run.deal_id,
        "status": run.status,
        "current_step": run.current_step,
        "trigger": run.trigger,
        "message": run.message,
        "error": run.error,
        "steps": run.steps or [],
        "summary": run.summary or {},
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "updated_at": run.updated_at.isoformat() if run.updated_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
    }


def attach_run_status(metrics: dict | None, run: PipelineRun | None) -> dict:
    next_metrics = dict(metrics or {})
    if not run:
        return next_metrics
    existing = next_metrics.get("_pipeline") if isinstance(next_metrics.get("_pipeline"), dict) else {}
    next_metrics["_pipeline"] = {
        **existing,
        "run_id": run.id,
        "status": run.status,
        "step": run.current_step,
        "message": run.message,
        "error": run.error,
        "started_at": run.started_at.isoformat() if run.started_at else existing.get("started_at"),
        "updated_at": run.updated_at.isoformat() if run.updated_at else now_iso(),
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
    }
    return next_metrics


async def start_pipeline_run(
    db: AsyncSession,
    deal: Deal,
    *,
    trigger: str = "manual",
    step: str = "extract",
    message: str = "Pipeline started.",
) -> PipelineRun:
    run = PipelineRun(
        deal_id=deal.id,
        status="running",
        current_step=step,
        trigger=trigger,
        message=message,
        steps=[_step_entry("running", step, message)],
        summary={},
    )
    db.add(run)
    await db.flush()
    deal.metrics = attach_run_status(deal.metrics, run)
    return run


async def get_latest_pipeline_run(db: AsyncSession, deal_id: int) -> PipelineRun | None:
    result = await db.execute(
        select(PipelineRun)
        .where(PipelineRun.deal_id == deal_id)
        .order_by(PipelineRun.started_at.desc(), PipelineRun.id.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def get_pipeline_run(db: AsyncSession, run_id: int | None) -> PipelineRun | None:
    if not run_id:
        return None
    result = await db.execute(select(PipelineRun).where(PipelineRun.id == run_id))
    return result.scalar_one_or_none()


async def update_pipeline_run(
    db: AsyncSession,
    run_id: int | None,
    *,
    status: str | None = None,
    step: str | None = None,
    message: str | None = None,
    error: str | None = None,
    summary: dict[str, Any] | None = None,
) -> PipelineRun | None:
    run = await get_pipeline_run(db, run_id)
    if not run:
        return None

    next_status = status or run.status
    next_step = step or run.current_step
    next_message = message if message is not None else run.message
    run.status = next_status
    run.current_step = next_step
    run.message = next_message
    run.error = error if error is not None else run.error
    run.updated_at = _now_dt()
    if next_status in {"complete", "failed", "cancelled"}:
        run.finished_at = run.updated_at
    if summary:
        run.summary = {**(run.summary or {}), **summary}

    steps = list(run.steps or [])
    steps.append(_step_entry(next_status, next_step, next_message, error))
    run.steps = steps[-50:]
    await db.flush()
    return run

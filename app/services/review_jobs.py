"""Database-backed, coalesced document review with bounded retries and leases.

The request survives process restarts. A lease fences old workers out of all
ORM writes; the existing extraction/verification caches provide checkpoints.
"""
from __future__ import annotations

import asyncio
import logging
import os
import uuid
from contextvars import ContextVar
from datetime import datetime, timedelta

from sqlalchemy import and_, case, or_, select, update
from sqlalchemy.orm.exc import StaleDataError

from app.database import async_session
from app.models import Deal, DealDocument, ReviewJob

log = logging.getLogger("kenyon.review_jobs")
active_lease = ContextVar("review_job_lease", default=None)
LEASE_SECONDS = 180


def utcnow():
    # SQLite returns naive UTC datetimes; use one representation for comparisons.
    return datetime.utcnow()


def public_pipeline(deal):
    pipeline = dict((deal.metrics or {}).get("_pipeline") or {})
    job = deal.__dict__.get("review_job")
    if not job:
        return pipeline
    if job.status in {"queued", "running"}:
        pipeline.update(status="running", step=pipeline.get("step") or "extract", progress_pct=5 if job.status == "queued" else pipeline.get("progress_pct", 10),
            message="Review queued; it will resume automatically." if job.status == "queued" else pipeline.get("message") or "Reading and checking documents.",
            updated_at=job.updated_at.isoformat(), job_status=job.status, attempt=job.attempts)
    elif job.status == "failed":
        pipeline.update(status="failed", error=job.error, message="Review stopped after three attempts. Retry when the source or service issue is resolved.", updated_at=job.updated_at.isoformat())
    return pipeline


async def enqueue_review(db, deal_id, *, mode="review", auto_correct=True):
    if mode not in {"review", "extract", "verify", "read"}:
        raise ValueError("Unknown review mode")
    now = utcnow()
    dialect = db.get_bind().dialect.name
    if dialect == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
    else:
        from sqlalchemy.dialects.sqlite import insert
    stmt = insert(ReviewJob).values(deal_id=deal_id, request_seq=1, mode=mode, status="queued", attempts=0,
        auto_correct=int(auto_correct), next_attempt_at=now + timedelta(seconds=2), updated_at=now)
    stmt = stmt.on_conflict_do_update(index_elements=[ReviewJob.deal_id], set_={
        "request_seq": ReviewJob.request_seq + 1, "mode": mode,
        "status": case((ReviewJob.status == "running", "running"), else_="queued"),
        "attempts": 0, "auto_correct": int(auto_correct), "next_attempt_at": now + timedelta(seconds=2), "updated_at": now, "error": None,
    })
    await db.execute(stmt)


def assert_lease(session):
    lease = active_lease.get()
    if not lease:
        return
    deal_id, token = lease
    # A conditional write holds the job row (SQLite: writer transaction) until
    # commit, closing the gap between checking ownership and saving results.
    result = session.execute(update(ReviewJob).where(ReviewJob.deal_id == deal_id, ReviewJob.lease_token == token,
        ReviewJob.lease_until >= utcnow()).values(lease_token=token).execution_options(synchronize_session=False))
    if result.rowcount != 1:
        raise StaleDataError("This review worker no longer owns the job")


async def claim_job():
    now = utcnow()
    eligible = and_(ReviewJob.next_attempt_at <= now, or_(ReviewJob.status == "queued", and_(ReviewJob.status == "running", ReviewJob.lease_until < now)))
    async with async_session() as db:
        job = (await db.execute(select(ReviewJob).where(eligible).order_by(ReviewJob.next_attempt_at).limit(1))).scalar_one_or_none()
        if not job:
            return None
        token = uuid.uuid4().hex
        result = await db.execute(update(ReviewJob).where(ReviewJob.deal_id == job.deal_id, eligible, ReviewJob.request_seq == job.request_seq)
            .values(status="running", lease_token=token, lease_until=now + timedelta(seconds=LEASE_SECONDS), attempts=ReviewJob.attempts + 1, updated_at=now).execution_options(synchronize_session=False))
        await db.commit()
        if result.rowcount != 1:
            return None
        return {"deal_id": job.deal_id, "token": token, "seq": job.request_seq, "mode": job.mode, "auto_correct": bool(job.auto_correct), "attempt": job.attempts + 1}


async def heartbeat(job):
    while True:
        await asyncio.sleep(30)
        async with async_session() as db:
            await db.execute(update(ReviewJob).where(ReviewJob.deal_id == job["deal_id"], ReviewJob.lease_token == job["token"])
                .values(lease_until=utcnow() + timedelta(seconds=LEASE_SECONDS), updated_at=utcnow()))
            await db.commit()


async def execute_job(job):
    from app.routers import deal_pipeline, deal_uploads
    deal_id = job["deal_id"]
    async with async_session() as db:
        deal = await db.get(Deal, deal_id)
        if not deal or deal.deleted_at is not None:
            return "cancelled"
        docs = (await db.execute(select(DealDocument).where(DealDocument.deal_id == deal_id))).scalars().all()
        pending = [(doc.id, doc.file_path, os.path.splitext(doc.file_path)[1].lower()) for doc in docs if (doc.extraction_quality or {}).get("status") in {"queued", "extracting"}]
    for doc_id, path, ext in pending:
        await deal_uploads._extract_document_background(doc_id, path, ext, handoff=False)
    if job["mode"] == "read":
        return "complete"
    if job["mode"] == "review":
        await deal_pipeline._run_document_review_background(deal_id)
    elif job["mode"] == "extract":
        await deal_pipeline._run_extract_background(deal_id)
    else:
        await deal_pipeline._run_verify_background(deal_id, job["auto_correct"])
    async with async_session() as db:
        deal = await db.get(Deal, deal_id)
        if not deal or deal.deleted_at is not None:
            return "cancelled"
        pipeline = (deal.metrics or {}).get("_pipeline") or {}
        expected = {"review": "complete", "extract": "extract_complete", "verify": "verify_complete"}[job["mode"]]
        if pipeline.get("status") != expected:
            raise RuntimeError(pipeline.get("error") or "Inputs changed or review did not finish; retrying the latest revision.")
        return "questions" if (deal.analysis_snapshot or {}).get("questions") else "complete"


async def finish_job(job, outcome, error=None):
    from app.services.notifications import emit
    async with async_session() as db:
        row = await db.get(ReviewJob, job["deal_id"])
        if not row or row.lease_token != job["token"]:
            return
        rerun = row.request_seq != job["seq"]
        retry = error is not None and job["attempt"] < 3
        state = "queued" if rerun or retry else "failed" if error else outcome
        result = await db.execute(update(ReviewJob).where(ReviewJob.deal_id == row.deal_id, ReviewJob.lease_token == job["token"])
            .values(status=case((ReviewJob.request_seq != job["seq"], "queued"), else_=state), lease_token=None, lease_until=None, error=str(error)[:1500] if error else None,
                    next_attempt_at=utcnow() + timedelta(seconds=2 if rerun else 30 * job["attempt"] if retry else 0), updated_at=utcnow()))
        if result.rowcount != 1:
            return
        await db.refresh(row)
        state = row.status
        if state not in {"queued", "cancelled"}:
            deal = await db.get(Deal, row.deal_id)
            if deal and deal.deleted_at is None:
                count = len((deal.analysis_snapshot or {}).get("questions") or [])
                label = {"read": "Document reading", "extract": "Metric extraction", "verify": "Source verification"}.get(job["mode"], "Document review")
                await emit(db, "error" if error else "warning" if count else "success", f"{label} {'stopped' if error else 'finished'} - {deal.project_name}",
                    body="Review could not finish after three attempts. Your previous analysis is preserved; retry from Documents." if error else f"{count} material question groups remain. Open the accepted summary and evidence.",
                    href=f"/deals/{deal.id}?tab={'questions' if count else 'overview'}", payload={"deal_id": deal.id, "analysis_version": deal.analysis_version, "job_status": state})
        await db.commit()


async def process_one_job():
    job = await claim_job()
    if not job:
        return False
    if job["attempt"] > 3:
        await finish_job(job, "failed", RuntimeError("Review interrupted repeatedly; retry after checking the provider."))
        return True
    token = active_lease.set((job["deal_id"], job["token"]))
    pulse = asyncio.create_task(heartbeat(job))
    outcome, error = "failed", None
    try:
        outcome = await execute_job(job)
    except asyncio.CancelledError:
        raise  # Lease expiry lets another process resume after shutdown/crash.
    except Exception as exc:
        log.exception("Review attempt failed for deal %s", job["deal_id"])
        error = exc
    finally:
        pulse.cancel()
        try:
            await pulse
        except asyncio.CancelledError:
            pass
        except Exception:
            log.exception("Review heartbeat failed; the lease will be checked before saving")
        active_lease.reset(token)
    await finish_job(job, outcome, error)
    return True


async def worker_loop():
    while True:
        try:
            if await process_one_job():
                continue
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Review queue scan failed")
        await asyncio.sleep(3)


def start_review_worker():
    return asyncio.create_task(worker_loop(), name="durable-document-review")


async def stop_review_worker(task):
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

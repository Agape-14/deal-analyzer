"""Exercise leases, coalescing, retry bounds and restart recovery without AI."""
from datetime import timedelta

import pytest
from sqlalchemy import select, update

pytestmark = pytest.mark.asyncio


async def setup_job(client):
    from app.database import async_session
    from app.models import ReviewJob
    from app.services.review_jobs import enqueue_review, utcnow
    deal_id = (await client.post("/api/deals", json={"project_name": "Queue fixture"})).json()["id"]
    async with async_session() as db:
        await enqueue_review(db, deal_id)
        await db.execute(update(ReviewJob).where(ReviewJob.deal_id == deal_id).values(next_attempt_at=utcnow() - timedelta(seconds=1)))
        await db.commit()
    return deal_id


async def make_due(deal_id):
    from app.database import async_session
    from app.models import ReviewJob
    from app.services.review_jobs import utcnow
    async with async_session() as db:
        await db.execute(update(ReviewJob).where(ReviewJob.deal_id == deal_id).values(next_attempt_at=utcnow() - timedelta(seconds=1)))
        await db.commit()


async def test_upload_burst_coalesces_and_only_one_worker_claims(client):
    from app.database import async_session
    from app.models import ReviewJob
    from app.services.review_jobs import enqueue_review, claim_job
    deal_id = await setup_job(client)
    async with async_session() as db:
        await enqueue_review(db, deal_id)
        await enqueue_review(db, deal_id)
        await db.commit()
        assert len((await db.execute(select(ReviewJob))).scalars().all()) == 1
    await make_due(deal_id)
    first = await claim_job()
    assert first["seq"] == 3
    assert await claim_job() is None


async def test_expired_worker_cannot_write_and_new_worker_recovers(client):
    from app.database import async_session
    from app.models import Deal, ReviewJob
    from app.services.review_jobs import active_lease, claim_job, utcnow
    from sqlalchemy.orm.exc import StaleDataError
    deal_id = await setup_job(client)
    old = await claim_job()
    async with async_session() as db:
        await db.execute(update(ReviewJob).where(ReviewJob.deal_id == deal_id).values(lease_until=utcnow() - timedelta(seconds=1)))
        await db.commit()
    new = await claim_job()
    assert new["token"] != old["token"]
    token = active_lease.set((deal_id, old["token"]))
    try:
        async with async_session() as db:
            deal = await db.get(Deal, deal_id)
            deal.metrics = {"target_returns": {"target_irr": 99}}
            with pytest.raises(StaleDataError):
                await db.commit()
            await db.rollback()
    finally:
        active_lease.reset(token)
    actual = (await client.get(f"/api/deals/{deal_id}")).json()
    assert actual["metrics"].get("target_returns", {}).get("target_irr") is None


async def test_new_request_during_run_is_not_lost_at_completion(client):
    from app.database import async_session
    from app.models import ReviewJob
    from app.services.review_jobs import claim_job, enqueue_review, finish_job
    deal_id = await setup_job(client)
    job = await claim_job()
    async with async_session() as db:
        await enqueue_review(db, deal_id)
        await db.commit()
    await finish_job(job, "complete")
    async with async_session() as db:
        row = await db.get(ReviewJob, deal_id)
        assert row.status == "queued"
        assert row.request_seq == 2


async def test_provider_failures_stop_after_three_attempts_and_notify_once(client, monkeypatch):
    from app.database import async_session
    from app.models import ReviewJob, Notification
    import app.services.review_jobs as jobs
    from unittest.mock import AsyncMock
    deal_id = await setup_job(client)
    execute = AsyncMock(side_effect=RuntimeError("Synthetic provider failure"))
    monkeypatch.setattr(jobs, "execute_job", execute)
    for _ in range(3):
        await make_due(deal_id)
        assert await jobs.process_one_job()
    assert execute.await_count == 3
    assert await jobs.process_one_job() is False
    async with async_session() as db:
        assert (await db.get(ReviewJob, deal_id)).status == "failed"
        notices = (await db.execute(select(Notification))).scalars().all()
        assert len(notices) == 1
        assert notices[0].kind == "error"


async def test_success_records_one_outcome_and_no_more_work(client, monkeypatch):
    from app.database import async_session
    from app.models import ReviewJob, Notification
    import app.services.review_jobs as jobs
    from app.services.notifications import emit
    deal_id = await setup_job(client)
    async def run(job):
        async with async_session() as db:
            await emit(db, "success", "Intermediate stage")
            await db.commit()
        return "questions"
    monkeypatch.setattr(jobs, "execute_job", run)
    assert await jobs.process_one_job()
    assert await jobs.process_one_job() is False
    async with async_session() as db:
        assert (await db.get(ReviewJob, deal_id)).status == "questions"
        assert len((await db.execute(select(Notification))).scalars().all()) == 1


async def test_upload_and_queue_are_saved_together_without_browser_handoff(client, monkeypatch):
    from app.database import async_session
    from app.models import DealDocument, ReviewJob
    from app.routers import deal_uploads
    monkeypatch.setattr(deal_uploads, "AUTO_REVIEW_AFTER_UPLOAD", True)
    deal_id = (await client.post("/api/deals", json={"project_name": "Durable upload"})).json()["id"]
    response = await client.post(f"/api/deals/{deal_id}/documents/upload", files={"file": ("synthetic.csv", b"label,value\ncost,100\n", "text/csv")})
    assert response.status_code == 200, response.text
    async with async_session() as db:
        doc = await db.get(DealDocument, response.json()["id"])
        job = await db.get(ReviewJob, deal_id)
        assert doc.extraction_quality["status"] == "queued"
        assert job.status == "queued"
        assert job.request_seq == 1

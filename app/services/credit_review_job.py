"""Persist a single paid attempt before contacting OpenAI."""
from sqlalchemy import update

from app.config import openai_review_configured
from app.database import async_session
from app.models import Deal, ReviewJob
from app.services.openai_review import review_with_credits
from app.services.review_drafts import (
    ATTEMPT_KEY, DRAFT_KEY, ReviewError, draft_record, load_documents, package_identity, review_packet,
)
from app.services.review_jobs import utcnow


async def _fence_request(db, job):
    # Uploads acquire the deal row before enqueuing. Keep the same lock order.
    await db.execute(update(Deal).where(Deal.id == job["deal_id"]).values(revision=Deal.revision))
    result = await db.execute(update(ReviewJob).where(
        ReviewJob.deal_id == job["deal_id"], ReviewJob.request_seq == job["seq"],
        ReviewJob.lease_token == job["token"], ReviewJob.lease_until >= utcnow(),
    ).values(lease_token=job["token"]).execution_options(synchronize_session=False))
    return result.rowcount == 1


async def run_credit_review(job):
    if not openai_review_configured():
        raise ReviewError("OpenAI review is unavailable. Check the API project key or use Review with Codex.")
    if job["attempt"] > 1:
        raise ReviewError("The prior API review was interrupted. Retry from Documents to start a new review.")
    async with async_session() as db:
        if not await _fence_request(db, job):
            return "cancelled"
        deal = await db.get(Deal, job["deal_id"])
        if not deal or deal.deleted_at is not None:
            return "cancelled"
        docs = await load_documents(db, deal.id)
        packet = review_packet(deal, docs)
        metrics = deal.metrics or {}
        previous = metrics.get(ATTEMPT_KEY) or {}
        if previous.get("package_id") == packet["package_id"]:
            if previous.get("completed"):
                return "complete"
            if not job["auto_correct"]:
                raise ReviewError("An earlier API attempt already used this package. Retry from Documents if you want another review.")
        draft_at_start = metrics.get(DRAFT_KEY)
        deal.metrics = {**metrics, ATTEMPT_KEY: {"package_id": packet["package_id"]}}
        await db.commit()

    result, usage = await review_with_credits(packet)
    if result.package_id != packet["package_id"]:
        raise ReviewError("OpenAI returned a result for a different source package.")
    async with async_session() as db:
        if not await _fence_request(db, job):
            return "cancelled"
        deal = await db.get(Deal, job["deal_id"])
        if not deal or deal.deleted_at is not None:
            return "cancelled"
        docs = await load_documents(db, deal.id)
        if package_identity(deal, docs) != result.package_id:
            raise ReviewError("The deal changed during review. Run a review on the current source package.")
        metrics = deal.metrics or {}
        if metrics.get(DRAFT_KEY) != draft_at_start:
            raise ReviewError("A newer review draft is already available in Documents.")
        deal.metrics = {
            **metrics, DRAFT_KEY: draft_record(result, "openai", usage),
            ATTEMPT_KEY: {"package_id": result.package_id, "completed": True},
        }
        await db.commit()
        return "complete"
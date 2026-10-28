"""A guarded release must not spend credits or block free document workflows."""
from datetime import timedelta
from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.asyncio


async def test_pause_is_reported_and_paid_routes_do_not_queue_or_change_deal(client, monkeypatch):
    from app.database import async_session
    from app.models import ReviewJob
    monkeypatch.setenv("ANTHROPIC_API_KEY", "synthetic-not-a-real-key")
    deal_id = (await client.post("/api/deals", json={"project_name": "Paused review"})).json()["id"]
    suffixes = ("cashflow", "waterfall", "analysis/history")
    baseline = {suffix: (await client.get(f"/api/deals/{deal_id}/{suffix}")).status_code for suffix in suffixes}
    monkeypatch.setenv("PAID_REVIEW_ENABLED", "0")
    health = (await client.get("/api/healthz")).json()["environment"]["anthropic"]
    assert health["configured"] is False and health["paused"] is True
    assert "paused" in health["message"]
    before = (await client.get(f"/api/deals/{deal_id}")).json()
    for action in ("review", "extract", "verify"):
        result = await client.post(f"/api/deals/{deal_id}/{action}")
        assert result.status_code == 503 and "paused" in result.json()["detail"]
    after = (await client.get(f"/api/deals/{deal_id}")).json()
    assert before["metrics"] == after["metrics"] and before["revision"] == after["revision"]
    async with async_session() as db:
        assert await db.get(ReviewJob, deal_id) is None
    for suffix in suffixes:
        assert (await client.get(f"/api/deals/{deal_id}/{suffix}")).status_code == baseline[suffix]
    assert (await client.get(f"/api/reports/deal/{deal_id}/pdf")).status_code == 200
    assert (await client.post("/api/chat", json={"deal_id": deal_id, "message": "What evidence is available?"})).status_code == 200


async def test_upload_is_read_without_paid_review_and_can_be_previewed(client, monkeypatch):
    monkeypatch.setenv("PAID_REVIEW_ENABLED", "0")
    deal_id = (await client.post("/api/deals", json={"project_name": "Readable"})).json()["id"]
    result = await client.post(f"/api/deals/{deal_id}/documents/upload",
        files={"file": ("terms.csv", b"Term,Value\nManagement fee,1%\n", "text/csv")})
    assert result.status_code == 200
    doc_id = result.json()["id"]
    docs = (await client.get(f"/api/deals/{deal_id}/documents")).json()
    assert docs and docs[0]["has_text"] and docs[0]["extraction_quality"]["status"] == "extracted"
    assert (await client.get(f"/api/deals/documents/{doc_id}/file")).content.startswith(b"Term,Value")
    assert (await client.get(f"/api/deals/documents/{doc_id}/excerpt")).status_code == 200


async def test_queued_paid_job_pauses_once_but_read_jobs_remain_usable(client, monkeypatch):
    from app.database import async_session
    from app.models import ReviewJob
    from app.services.review_jobs import enqueue_review, process_one_job, utcnow
    from app.services.pipeline_runner import process_pending_deals
    deal_id = (await client.post("/api/deals", json={"project_name": "Queued"})).json()["id"]
    async with async_session() as db:
        await enqueue_review(db, deal_id)
        row = await db.get(ReviewJob, deal_id)
        row.next_attempt_at = utcnow() - timedelta(seconds=1)
        await db.commit()
    monkeypatch.setenv("PAID_REVIEW_ENABLED", "0")
    assert await process_one_job()
    assert not await process_one_job()
    assert await process_pending_deals() == 0
    async with async_session() as db:
        row = await db.get(ReviewJob, deal_id)
        assert row.status == "paused" and row.attempts == 1 and "paused" in row.error
        with pytest.raises(ValueError, match="paused"):
            await enqueue_review(db, deal_id)
        await enqueue_review(db, deal_id, mode="read")
        row = await db.get(ReviewJob, deal_id, populate_existing=True)
        row.next_attempt_at = utcnow() - timedelta(seconds=1)
        await db.commit()
    assert await process_one_job()
    async with async_session() as db:
        assert (await db.get(ReviewJob, deal_id)).status == "complete"


async def test_all_provider_entry_points_stop_before_client_or_file_access(monkeypatch):
    monkeypatch.setenv("PAID_REVIEW_ENABLED", "0")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "synthetic-not-a-real-key")
    from app.services.deal_extractor import extract_metrics_from_docs
    from app.services.deal_extractor_cost_aware import extract_metrics_from_docs as cost_aware
    from app.services.deal_verifier import verify_deal_metrics
    for operation in (extract_metrics_from_docs([], ["/nonexistent.pdf"]),
                      cost_aware([], ["/nonexistent.pdf"]), verify_deal_metrics(SimpleNamespace(metrics={}, documents=[]), None)):
        with pytest.raises(ValueError, match="paused"):
            await operation

"""Exercise both review paths with synthetic documents and a mocked provider."""
import json
import re
from datetime import timedelta

import httpx
import pytest
from sqlalchemy import update

pytestmark = pytest.mark.asyncio

PATH = "deal_structure.minimum_investment"


async def upload_csv(client, deal_id=None, name="terms.csv", value=500000):
    if deal_id is None:
        response = await client.post("/api/deals", json={"project_name": "Synthetic review"})
        assert response.status_code == 200
        deal_id = response.json()["id"]
    response = await client.post(f"/api/deals/{deal_id}/documents/upload",
        files={"file": (name, f"Term,Value,Other\nMinimum Investment,{value},125\n".encode(), "text/csv")})
    assert response.status_code == 200, response.text
    return deal_id


def cited_result(packet, *, value=500000, **changes):
    source = packet["sources"][0]
    sheet = re.search(r"^--- Sheet: (.+) ---$", source["text"], re.M)[1]
    excerpt = next(line for line in source["text"].splitlines() if "B2=" in line)
    return {
        "package_id": packet["package_id"],
        "facts": [{"path": PATH, "value": value, "source_doc_id": source["id"], "source_sheet": sheet,
                   "source_cell": "B2", "source_excerpt": excerpt, "currency": "USD", **changes}],
    }


async def packet_for(client, base):
    download = await client.get(base + "/packet")
    assert download.status_code == 200, download.text
    assert "attachment" in download.headers["content-disposition"]
    assert "no-store" in download.headers["cache-control"]
    return download.json()["packet"]


def approval(draft):
    return {"draft_id": draft["draft"]["id"], "expected_revision": draft["revision"], "paths": [PATH]}


async def test_codex_import_uses_source_cell_and_saves_only_on_approval(client, monkeypatch):
    monkeypatch.setenv("PAID_REVIEW_ENABLED", "0")
    deal_id = await upload_csv(client)
    base = f"/api/deals/{deal_id}/review"
    packet = await packet_for(client, base)

    # 125 is in the verbatim quote but in the neighboring cell.
    wrong = await client.post(base + "/draft", json=cited_result(packet, value=125))
    assert wrong.status_code == 200
    assert wrong.json()["draft"]["rows"][0]["issue"]
    assert (await client.post(base + "/approve", json=approval(wrong.json()))).status_code == 422

    imported = await client.post(base + "/draft", json=cited_result(packet))
    assert imported.status_code == 200, imported.text
    view = imported.json()
    assert not view["draft"]["rows"][0]["issue"]
    before = (await client.get(f"/api/deals/{deal_id}")).json()
    assert PATH not in before["analysis"]["facts"]
    assert "_review_draft" not in before["metrics"]
    saved = await client.post(base + "/approve", json=approval(view))
    assert saved.status_code == 200, saved.text
    assert saved.json()["applied"] == 1
    after = (await client.get(f"/api/deals/{deal_id}")).json()
    assert after["analysis"]["facts"][PATH]["value"] == 500000
    assert after["analysis"]["facts"][PATH]["state"] == "checked"
    assert (await client.get(base + "/draft")).json()["draft"] is None


async def test_codex_result_is_bound_to_sources_and_does_not_replace_locked_values(client):
    from app.database import async_session
    from app.models import Deal

    deal_id = await upload_csv(client)
    base = f"/api/deals/{deal_id}/review"
    packet = await packet_for(client, base)
    result = cited_result(packet)
    async with async_session() as db:
        deal = await db.get(Deal, deal_id)
        deal.metrics = {"_locks": {PATH: True}, "deal_structure": {"minimum_investment": 100000}}
        await db.commit()
    assert (await client.post(base + "/draft", json=result)).status_code == 409

    result = cited_result(await packet_for(client, base))
    view = (await client.post(base + "/draft", json=result)).json()
    assert "locked" in view["draft"]["rows"][0]["issue"]
    await upload_csv(client, deal_id, "updated-terms.csv", value=600000)
    assert (await client.get(base + "/draft")).json()["draft"]["stale"] is True
    assert (await client.post(base + "/approve", json=approval(view))).status_code == 409


async def test_responses_preflight_limits_usage_and_preserves_wire_contract(client, monkeypatch):
    from app.services import openai_review
    from app.services.review_drafts import ReviewError

    monkeypatch.setenv("OPENAI_API_KEY", "fake-project-key")
    real_client = httpx.AsyncClient
    requests = []
    input_tokens = openai_review.MAX_INPUT_TOKENS + 1

    def handle(request):
        requests.append(request.url.path)
        data = json.loads(request.content)
        assert data["model"] == openai_review.MODEL
        assert data["text"]["format"]["strict"] is True
        if request.url.path.endswith("/input_tokens"):
            return httpx.Response(200, json={"input_tokens": input_tokens})
        assert data["store"] is False
        assert data["service_tier"] == "default"
        assert data["max_output_tokens"] == 12000
        return httpx.Response(200, json={"status": "completed",
            "output": [{"type": "message", "content": [{"type": "output_text",
                "text": json.dumps({"package_id": "a" * 64, "facts": []})}]}],
            "usage": {"input_tokens": 1000, "output_tokens": 200}})

    monkeypatch.setattr(openai_review.httpx, "AsyncClient",
        lambda **kwargs: real_client(**kwargs, transport=httpx.MockTransport(handle)))
    with pytest.raises(ReviewError, match="budget"):
        await openai_review.review_with_credits({"package_id": "a" * 64})
    assert requests == ["/v1/responses/input_tokens"]
    requests.clear()
    input_tokens = 1000
    result, usage = await openai_review.review_with_credits({"package_id": "a" * 64})
    assert result.package_id == "a" * 64
    assert requests == ["/v1/responses/input_tokens", "/v1/responses"]
    assert usage["estimated_cost_usd"] == 0.002


async def make_due(deal_id):
    from app.database import async_session
    from app.models import ReviewJob
    from app.services.review_jobs import utcnow
    async with async_session() as db:
        await db.execute(update(ReviewJob).where(ReviewJob.deal_id == deal_id)
            .values(next_attempt_at=utcnow() - timedelta(seconds=1)))
        await db.commit()


async def test_openai_upload_reviews_once_and_never_falls_back_to_anthropic(client, monkeypatch):
    from app.routers import deal_uploads
    from app.services import credit_review_job
    from app.services.review_drafts import ReviewResult
    from app.services.review_jobs import process_one_job

    monkeypatch.setenv("PAID_REVIEW_ENABLED", "0")
    monkeypatch.setenv("DEAL_REVIEW_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "fake-project-key")
    monkeypatch.setattr(deal_uploads, "AUTO_REVIEW_AFTER_UPLOAD", True)
    calls = []

    async def fake_provider(packet):
        calls.append(packet["package_id"])
        return ReviewResult.model_validate(cited_result(packet)), {"estimated_cost_usd": 0.01}

    monkeypatch.setattr(credit_review_job, "review_with_credits", fake_provider)
    deal_id = await upload_csv(client)
    base = f"/api/deals/{deal_id}"
    assert (await client.post(base + "/extract")).status_code == 503
    assert (await client.post(base + "/verify")).status_code == 503
    health = (await client.get("/api/healthz")).json()["environment"]
    assert health["openai"]["configured"] and health["anthropic"]["paused"]

    await make_due(deal_id)
    assert await process_one_job()
    view = (await client.get(base + "/review/draft")).json()
    assert view["job"]["status"] == "complete", view
    assert view["draft"]["provider"] == "openai"
    assert view["draft"]["usage"]["estimated_cost_usd"] == 0.01
    assert len(calls) == 1

    assert (await client.post(base + "/review")).status_code == 200
    await make_due(deal_id)
    assert await process_one_job()
    assert len(calls) == 1


async def test_api_credit_failure_is_not_retried_and_missing_key_is_safe(client, monkeypatch):
    from app.services import credit_review_job
    from app.services.review_drafts import ReviewError
    from app.services.review_jobs import process_one_job

    deal_id = await upload_csv(client)
    base = f"/api/deals/{deal_id}/review"
    monkeypatch.setenv("DEAL_REVIEW_PROVIDER", "openai")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-legacy-key")
    assert (await client.post(base)).status_code == 503
    monkeypatch.setenv("OPENAI_API_KEY", "fake-project-key")
    calls = []

    async def unavailable(packet):
        calls.append(packet["package_id"])
        raise ReviewError("OpenAI credits or rate limits blocked the review.")

    monkeypatch.setattr(credit_review_job, "review_with_credits", unavailable)
    assert (await client.post(base)).status_code == 200
    await make_due(deal_id)
    assert await process_one_job()
    await make_due(deal_id)
    assert not await process_one_job()
    view = (await client.get(base + "/draft")).json()
    assert view["draft"] is None
    assert "OpenAI credits" in view["job"]["error"]
    assert len(calls) == 1
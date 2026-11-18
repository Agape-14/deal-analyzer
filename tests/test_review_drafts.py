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
    monkeypatch.setenv("PAID_REVIEW_ENABLED", "1")
    monkeypatch.setenv("DEAL_REVIEW_PROVIDER", "codex")
    monkeypatch.setenv("OPENAI_API_KEY", "fake-project-key")
    assert (await client.get("/api/healthz")).json()["environment"]["codex"]["configured"] is True
    deal_id = await upload_csv(client)
    base = f"/api/deals/{deal_id}/review"
    assert (await client.post(base)).status_code == 503
    packet = await packet_for(client, base)

    # 125 is in the verbatim quote but in the neighboring cell.
    wrong = await client.post(base + "/draft", json=cited_result(packet, value=125))
    assert wrong.status_code == 200
    assert wrong.json()["draft"]["rows"][0]["issue"]
    assert (await client.post(base + "/approve", json=approval(wrong.json()))).status_code == 422

    proposal = cited_result(packet)
    deferred = {**proposal["facts"][0], "path": "project_details.unit_count", "source_cell": "C2", "value": 125}
    proposal["facts"].append(deferred)
    imported = await client.post(base + "/draft", json=proposal)
    assert imported.status_code == 200, imported.text
    view = imported.json()
    assert not view["draft"]["rows"][0]["issue"]
    before = (await client.get(f"/api/deals/{deal_id}")).json()
    assert before["analysis"]["facts"][PATH]["value"] is None
    assert "_review_draft" not in before["metrics"]
    saved = await client.post(base + "/approve", json=approval(view))
    assert saved.status_code == 200, saved.text
    assert saved.json()["applied"] == 1
    after = (await client.get(f"/api/deals/{deal_id}")).json()
    assert after["analysis"]["facts"][PATH]["value"] == 500000
    assert after["analysis"]["facts"][PATH]["state"] == "checked"
    remaining = (await client.get(base + "/draft")).json()["draft"]
    assert remaining and not remaining["stale"]
    assert [row["path"] for row in remaining["rows"]] == ["project_details.unit_count"]


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


async def test_workbook_outflows_import_as_positive_costs_with_signed_source_evidence(client):
    from app.database import async_session
    from app.models import Deal

    created = await client.post("/api/deals", json={"project_name": "Synthetic signed workbook costs"})
    deal_id = created.json()["id"]
    uploaded = await client.post(f"/api/deals/{deal_id}/documents/upload", files={
        "file": ("costs.csv", b"Description,Value\nProject cost outflow,-500000\nProject IRR,-12.5\n", "text/csv"),
    })
    assert uploaded.status_code == 200, uploaded.text
    base = f"/api/deals/{deal_id}/review"
    packet = await packet_for(client, base)
    cost_paths = [
        "construction_costs.hard_costs_total",
        "financial_projections.soft_costs",
        "deal_structure.total_project_cost",
    ]
    other_paths = ["deal_structure.debt_amount", "deal_structure.total_equity_required", "target_returns.total_project_profit"]
    template = cited_result(packet)["facts"][0]
    proposed = {"package_id": packet["package_id"], "facts": [
        {**template, "path": path, "value": -500000 if path == "financial_projections.soft_costs" else 500000}
        for path in [*cost_paths, *other_paths]
    ]}
    proposed["facts"].append({
        **template, "path": "target_returns.target_irr", "value": 12.5, "source_cell": "B3",
        "source_excerpt": next(line for line in packet["sources"][0]["text"].splitlines() if "B3=" in line),
    })
    imported = await client.post(base + "/draft", json=proposed)
    assert imported.status_code == 200, imported.text
    view = imported.json()
    rows = {row["path"]: row for row in view["draft"]["rows"]}
    assert all(rows[path]["value"] == 500000 and not rows[path]["issue"] for path in cost_paths)
    assert all(rows[path]["issue"] for path in other_paths)
    assert rows["target_returns.target_irr"]["issue"]
    assert all("-500000" in rows[path]["evidence"]["source_excerpt"] for path in cost_paths)
    saved = await client.post(base + "/approve", json={
        **approval(view), "paths": cost_paths,
    })
    assert saved.status_code == 200, saved.text
    async with async_session() as db:
        metrics = (await db.get(Deal, deal_id)).metrics
        for path in cost_paths:
            evidence = metrics["_provenance"][path]
            assert evidence["status"] == "confirmed"
            assert "-500000" in evidence["source_excerpt"]
            assert "positive magnitude" in evidence["source_value_note"]
    after = (await client.get(f"/api/deals/{deal_id}")).json()
    assert all(after["analysis"]["facts"][path]["value"] == 500000 for path in cost_paths)


async def test_pdf_cost_outflow_does_not_gain_workbook_magnitude_treatment(client):
    from app.database import async_session
    from app.models import DealDocument

    created = await client.post("/api/deals", json={"project_name": "Synthetic signed PDF cost"})
    deal_id = created.json()["id"]
    async with async_session() as db:
        doc = DealDocument(deal_id=deal_id, filename="cost.pdf", file_path="synthetic-cost.pdf",
                           file_sha256="b" * 64, page_count=1, extracted_text="--- Page 1 ---\nHard costs -500000")
        db.add(doc)
        await db.commit()
        doc_id = doc.id
    base = f"/api/deals/{deal_id}/review"
    packet = await packet_for(client, base)
    imported = await client.post(base + "/draft", json={
        "package_id": packet["package_id"], "facts": [{
            "path": "construction_costs.hard_costs_total", "value": 500000, "source_doc_id": doc_id,
            "source_page": 1, "source_excerpt": "Hard costs -500000", "currency": "USD",
        }],
    })
    assert imported.status_code == 200, imported.text
    row = imported.json()["draft"]["rows"][0]
    assert row["issue"] and "source_value_note" not in row["evidence"]


@pytest.mark.parametrize("page_source,quote,value,path,valid", [
    ("ocr_image", "Preconstruction soft costs (2,345.678)", 2345678, "construction_costs.preconstruction_soft_costs", True),
    ("ocr", "Financing expenses (7.654,321)", 7654321, "construction_costs.financing_costs", True),
    ("text", "Preconstruction soft costs (2,345.678)", 2345678, "construction_costs.preconstruction_soft_costs", False),
    ("other_page", "Preconstruction soft costs (2,345.678)", 2345678, "construction_costs.preconstruction_soft_costs", False),
    ("ocr_image", "Preconstruction soft costs (2,345.678)", 2345679, "construction_costs.preconstruction_soft_costs", False),
    ("ocr_image", "Preconstruction soft costs (2,345.67)", 234567, "construction_costs.preconstruction_soft_costs", False),
    ("ocr_image", "Preconstruction soft costs (2,345.678)%", 2345678, "construction_costs.preconstruction_soft_costs", False),
    ("ocr_image", "Construction debt (2,345.678)", 2345678, "deal_structure.debt_amount", False),
    ("ocr_image", "Interest only debt service (3.769.500)", 3769500, "financial_projections.interest_only_debt_service", True),
    ("ocr_image", "Amortizing debt service (2.468.135)", 2468135, "financial_projections.amortizing_debt_service", True),
    ("ocr_image", "Interest only debt service (3.769.500)", 3769501, "financial_projections.interest_only_debt_service", False),
    ("ocr_image", "Interest only debt service (3,769.50)", 376950, "financial_projections.interest_only_debt_service", False),
    ("ocr_image", "Construction debt (3.769.500)", 3769500, "deal_structure.debt_amount", False),
])
async def test_pdf_ocr_cost_grouping_requires_current_ocr_page_and_exact_integer(
    client, page_source, quote, value, path, valid,
):
    from app.database import async_session
    from app.models import Deal, DealDocument

    created = await client.post("/api/deals", json={"project_name": "Synthetic OCR currency grouping"})
    deal_id = created.json()["id"]
    async with async_session() as db:
        doc = DealDocument(
            deal_id=deal_id, filename="budget.pdf", file_path="synthetic-budget.pdf",
            file_sha256="c" * 64, page_count=2, extracted_text="--- Page 1 ---\n" + quote,
            extraction_quality={"status": "extracted", "ocr_pages": 1, "page_diagnostics": [{
                "page": 2 if page_source == "other_page" else 1,
                "source": "ocr_image" if page_source == "other_page" else page_source,
            }]},
        )
        db.add(doc)
        await db.commit()
        doc_id = doc.id
    base = f"/api/deals/{deal_id}/review"
    packet = await packet_for(client, base)
    imported = await client.post(base + "/draft", json={
        "package_id": packet["package_id"], "facts": [{
            "path": path, "value": value, "source_doc_id": doc_id, "source_page": 1,
            "source_excerpt": quote, "currency": "USD",
        }],
    })
    assert imported.status_code == 200, imported.text
    view = imported.json()
    row = view["draft"]["rows"][0]
    assert not row["issue"] if valid else row["issue"]
    saved = await client.post(base + "/approve", json={**approval(view), "paths": [path]})
    assert saved.status_code == (200 if valid else 422), saved.text
    if valid:
        async with async_session() as db:
            evidence = (await db.get(Deal, deal_id)).metrics["_provenance"][path]
            assert evidence["source_excerpt"] == quote
            assert "OCR currency grouping" in evidence["source_value_note"]
        fact = (await client.get(f"/api/deals/{deal_id}")).json()["analysis"]["facts"][path]
        assert fact["value"] == value and fact["state"] == "checked"


@pytest.mark.parametrize("suffix", ["X", "×"])
async def test_pdf_equity_multiple_suffix_keeps_exact_quote_and_rejects_wrong_multiple(client, suffix):
    from app.database import async_session
    from app.models import DealDocument

    created = await client.post("/api/deals", json={"project_name": "Synthetic multiple suffix"})
    deal_id = created.json()["id"]
    quote = f"Illustrative sale after 5 years: 2.4{suffix} equity multiple."
    async with async_session() as db:
        doc = DealDocument(
            deal_id=deal_id, filename="returns.pdf", file_path="synthetic-returns.pdf",
            file_sha256="d" * 64, page_count=1, extracted_text="--- Page 1 ---\n" + quote,
        )
        db.add(doc)
        await db.commit()
        doc_id = doc.id
    base = f"/api/deals/{deal_id}/review"
    packet = await packet_for(client, base)
    path = "target_returns.sale_scenario.sale_equity_multiple"
    proposal = {"package_id": packet["package_id"], "facts": [{
        "path": path, "value": 2.6, "source_doc_id": doc_id, "source_page": 1,
        "source_excerpt": quote, "scenario": "sale",
    }]}
    wrong = await client.post(base + "/draft", json=proposal)
    assert wrong.status_code == 200, wrong.text
    assert wrong.json()["draft"]["rows"][0]["issue"]
    proposal["facts"][0]["value"] = 2.4
    correct = await client.post(base + "/draft", json=proposal)
    assert correct.status_code == 200, correct.text
    row = correct.json()["draft"]["rows"][0]
    assert not row["issue"] and row["evidence"]["source_excerpt"] == quote


async def test_same_locked_value_can_be_source_checked_without_replacing_manual_decision(client):
    import copy

    from app.database import async_session
    from app.models import Deal
    from app.services.data_integrity import mark_manual_edit

    deal_id = await upload_csv(client)
    base = f"/api/deals/{deal_id}/review"
    async with async_session() as db:
        deal = await db.get(Deal, deal_id)
        metrics = mark_manual_edit(deal.metrics or {}, PATH, 500000)
        metrics["_provenance"][PATH].update({
            "verification_note": "Analyst selected this minimum from the sponsor confirmation.",
            "source_challenge": "An earlier source check could not read the value.",
            "last_source_check": {"status": "unverifiable"},
            "source_page": 99,
        })
        metrics["_fact_context"] = {PATH: {"currency": "USD"}}
        metrics["_field_history"] = [{"path": PATH, "action": "question_resolved", "new_value": 500000}]
        deal.metrics = metrics
        await db.commit()
        before = copy.deepcopy(deal.metrics)

    packet = await packet_for(client, base)
    for edits in (
        {"value": 500001},
        {"source_excerpt": "A2=An invented label | B2=500000"},
        {"currency": "EUR"},
    ):
        imported = await client.post(base + "/draft", json=cited_result(packet, **edits))
        assert imported.status_code == 200, imported.text
        view = imported.json()
        assert view["draft"]["rows"][0]["issue"]
        assert (await client.post(base + "/approve", json=approval(view))).status_code == 422
        async with async_session() as db:
            evidence = (await db.get(Deal, deal_id)).metrics["_provenance"][PATH]
            assert evidence["source_challenge"] == before["_provenance"][PATH]["source_challenge"]

    imported = await client.post(base + "/draft", json=cited_result(packet))
    assert imported.status_code == 200, imported.text
    view = imported.json()
    assert not view["draft"]["rows"][0]["issue"]
    saved = await client.post(base + "/approve", json=approval(view))
    assert saved.status_code == 200, saved.text
    async with async_session() as db:
        after = (await db.get(Deal, deal_id)).metrics
        evidence = after["_provenance"][PATH]
        previous = before["_provenance"][PATH]
        for key in ("source", "status", "locked", "verification_note", "extracted_at"):
            assert evidence[key] == previous[key]
        assert after["_locks"] == before["_locks"]
        assert after["_field_history"] == before["_field_history"]
        assert after["_fact_context"] == before["_fact_context"]
        assert after["deal_structure"]["minimum_investment"] == before["deal_structure"]["minimum_investment"]
        assert "source_challenge" not in evidence and "source_page" not in evidence
        assert evidence["source_cell"] == "B2"
        assert evidence["last_source_check"]["status"] == "confirmed"
        assert evidence["last_source_check"]["citation"]["source_cell"] == "B2"
    fact = (await client.get(f"/api/deals/{deal_id}")).json()["analysis"]["facts"][PATH]
    assert fact["state"] == "manual" and fact["locked"]


async def test_responses_preflight_limits_usage_and_preserves_wire_contract(client, monkeypatch):
    from app.services import openai_review
    from app.services.review_drafts import ReviewError

    monkeypatch.setenv("OPENAI_API_KEY", "fake-project-key")
    real_client = httpx.AsyncClient
    requests = []
    monkeypatch.delenv("DEAL_REVIEW_MAX_USD", raising=False)
    input_tokens = 420_000

    def handle(request):
        requests.append(request.url.path)
        data = json.loads(request.content)
        assert data["model"] == "gpt-6-astra"
        assert data["text"]["format"]["strict"] is True
        if request.url.path.endswith("/input_tokens"):
            return httpx.Response(200, json={"input_tokens": input_tokens})
        assert data["store"] is False
        assert data["service_tier"] == "default"
        assert data["reasoning"] == {"effort": "xhigh"}
        assert data["truncation"] == "disabled"
        assert data["max_output_tokens"] == openai_review.output_allowance(input_tokens, openai_review.review_budget_usd())
        return httpx.Response(200, json={"status": "completed",
            "output": [{"type": "message", "content": [{"type": "output_text",
                "text": json.dumps({"package_id": "a" * 64, "facts": []})}]}],
            "usage": {"input_tokens": input_tokens, "output_tokens": 200}})

    monkeypatch.setattr(openai_review.httpx, "AsyncClient",
        lambda **kwargs: real_client(**kwargs, transport=httpx.MockTransport(handle)))
    with pytest.raises(ReviewError, match=r"\$10 limit"):
        await openai_review.review_with_credits({"package_id": "a" * 64})
    assert requests == ["/v1/responses/input_tokens"]

    requests.clear()
    input_tokens = 300_000
    result, usage = await openai_review.review_with_credits({"package_id": "a" * 64})
    assert result.package_id == "a" * 64
    assert requests == ["/v1/responses/input_tokens", "/v1/responses"]
    assert usage["budget_usd"] == 10
    assert usage["estimated_cost_usd"] == 6.015
    allowance = openai_review.output_allowance(input_tokens, 10)
    assert openai_review.MIN_OUTPUT_TOKENS <= allowance < openai_review.MAX_OUTPUT_TOKENS
    buffered_input = input_tokens + openai_review.TOKEN_COUNT_BUFFER
    assert openai_review.estimated_microdollars(buffered_input, allowance) <= 10_000_000
    assert openai_review.estimated_microdollars(buffered_input, allowance + 1) > 10_000_000

    requests.clear()
    input_tokens = 420_000
    monkeypatch.setenv("DEAL_REVIEW_MAX_USD", "15")
    _, usage = await openai_review.review_with_credits({"package_id": "a" * 64})
    assert requests == ["/v1/responses/input_tokens", "/v1/responses"]
    assert usage["budget_usd"] == 15
    assert usage["estimated_cost_usd"] == 8.415
    assert openai_review.output_allowance(input_tokens, 15) > 64_000
    assert openai_review.output_allowance(10_000, 10) == 128_000
    assert openai_review.estimated_microdollars(272_000, 1_000) == 2_770_000
    assert openai_review.estimated_microdollars(272_001, 1_000) == 5_515_020

    requests.clear()
    monkeypatch.setenv("DEAL_REVIEW_MAX_USD", "invalid")
    with pytest.raises(ReviewError, match="positive whole dollar amount"):
        await openai_review.review_with_credits({"package_id": "a" * 64})
    assert requests == []


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

    current = (await client.get(base + "/review/draft")).json()
    assert (await client.post(base + "/review/approve", json=approval(current))).status_code == 200
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


async def test_group_assessments_need_explicit_approval_and_follow_source_changes(client):
    deal_id = await upload_csv(client)
    base = f"/api/deals/{deal_id}/review"
    packet = await packet_for(client, base)
    result = cited_result(packet)
    result["coverage"] = [{"group": "project_details", "status": "not_stated",
        "reason": "The complete terms-only source contains no additional project description or area.",
        "source_doc_ids": [source["id"] for source in packet["sources"]]}]
    imported = (await client.post(base + "/draft", json=result)).json()
    assert imported["draft"]["coverage"][0]["issue"] == ""
    assert "_review_group_coverage" not in (await client.get(f"/api/deals/{deal_id}")).json()["metrics"]
    facts_only = await client.post(base + "/approve", json=approval(imported))
    assert facts_only.status_code == 200, facts_only.text
    pending = facts_only.json()
    assert pending["coverage_applied"] == 0
    assert pending["draft"]["rows"] == []
    assert len(pending["draft"]["coverage"]) == 1
    saved = await client.post(base + "/approve", json={"draft_id": pending["draft"]["id"],
        "expected_revision": pending["revision"], "paths": [], "coverage_groups": ["project_details"]})
    assert saved.status_code == 200, saved.text
    assert saved.json()["applied"] == 0 and saved.json()["coverage_applied"] == 1
    deal = (await client.get(f"/api/deals/{deal_id}")).json()
    project = next(row for row in deal["analysis"]["review_coverage"]["groups"] if row["key"] == "project_details")
    assert project["status"] == "not_stated"
    assert deal["metrics"]["deal_structure"]["minimum_investment"] == 500000
    await upload_csv(client, deal_id, name="additional.csv", value=800000)
    updated = (await client.get(f"/api/deals/{deal_id}")).json()
    project = next(row for row in updated["analysis"]["review_coverage"]["groups"] if row["key"] == "project_details")
    assert project["status"] == "needs_review"
    assert updated["metrics"]["_review_group_coverage"]["project_details"]["status"] == "not_stated"


async def test_group_assessment_cannot_omit_an_active_source(client):
    deal_id = await upload_csv(client)
    await upload_csv(client, deal_id, name="second.csv", value=600000)
    base = f"/api/deals/{deal_id}/review"
    packet = await packet_for(client, base)
    result = {"package_id": packet["package_id"], "facts": [], "coverage": [{
        "group": "construction_budget", "status": "not_stated",
        "reason": "No construction component budget is stated in the sources.",
        "source_doc_ids": [packet["sources"][0]["id"]]}]}
    imported = await client.post(base + "/draft", json=result)
    assert imported.status_code == 200, imported.text
    draft = imported.json()
    assert "every active source" in draft["draft"]["coverage"][0]["issue"]
    response = await client.post(base + "/approve", json={"draft_id": draft["draft"]["id"],
        "expected_revision": draft["revision"], "coverage_groups": ["construction_budget"]})
    assert response.status_code == 422


async def test_analysis_schema_upgrade_preserves_existing_review_packets_and_drafts(client, monkeypatch):
    from app.services import analysis
    deal_id = await upload_csv(client)
    base = f"/api/deals/{deal_id}/review"
    packet = await packet_for(client, base)
    imported = await client.post(base + "/draft", json=cited_result(packet))
    assert imported.status_code == 200, imported.text
    draft = imported.json()
    monkeypatch.setattr(analysis, "SCHEMA_VERSION", analysis.SCHEMA_VERSION + 1)
    assert (await packet_for(client, base))["package_id"] == packet["package_id"]
    current = (await client.get(base + "/draft")).json()
    assert current["draft"]["id"] == draft["draft"]["id"] and not current["draft"]["stale"]
    approved = await client.post(base + "/approve", json=approval(draft))
    assert approved.status_code == 200, approved.text
    assert approved.json()["applied"] == 1

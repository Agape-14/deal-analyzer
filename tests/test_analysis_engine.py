"""Deterministic trust boundaries and transactional snapshot journeys."""
import copy

import pytest

from app.services.analysis import build_analysis, flatten


def manual_metrics():
    metrics = {
        "target_returns": {"primary_strategy": "hold", "hold_scenario": {"cash_on_cash_return": 8}},
        "deal_structure": {"total_project_cost": 1000000, "total_equity_required": 400000, "debt_amount": 600000, "minimum_investment": 25000},
        "project_details": {"unit_count": 10},
    }
    metrics["_provenance"] = {path: {"status": "manual"} for path in flatten(metrics)}
    return metrics


def test_unknown_fields_never_enter_accepted_inputs_and_optional_fields_are_not_chores():
    metrics = manual_metrics()
    metrics["market_location"] = {"walk_score": None, "invented_magic_score": 99}
    result = build_analysis(metrics)
    assert result["questions"] == []
    assert result["returns"]["cash_on_cash"] == 8
    assert "market_location" not in result["accepted_metrics"]
    assert "market_location.invented_magic_score" in result["unclassified_paths"]
    assert result["coverage"]["manual"] > 0


def test_confirmed_without_a_real_locator_is_still_reported():
    metrics = manual_metrics()
    path = "target_returns.hold_scenario.cash_on_cash_return"
    metrics["_provenance"][path] = {"status": "confirmed", "confidence": 100, "source_doc_name": "Memo.pdf"}
    docs = [{"id": 1, "filename": "Memo.pdf", "content_hash": "a", "page_count": 5}]
    result = build_analysis(metrics, docs)
    assert result["facts"][path]["state"] == "reported"
    assert result["returns"]["cash_on_cash"] is None
    metrics["_provenance"][path].update(source_page=3, source_document_hash="a")
    result = build_analysis(metrics, docs)
    assert result["facts"][path]["state"] == "checked"
    assert result["returns"]["cash_on_cash"] == 8
    docs[0]["content_hash"] = "b"
    assert build_analysis(metrics, docs)["returns"]["cash_on_cash"] is None
    assert build_analysis(metrics, [])["returns"]["cash_on_cash"] is None


def test_dotted_and_nested_disagreement_is_not_silently_collapsed():
    metrics = manual_metrics()
    metrics["target_returns"]["hold_scenario.cash_on_cash_return"] = 11
    result = build_analysis(metrics)
    assert result["facts"]["target_returns.hold_scenario.cash_on_cash_return"]["state"] == "disputed"
    assert result["returns"]["cash_on_cash"] is None


def test_derived_facts_recompute_and_withhold_when_dependency_is_challenged():
    metrics = manual_metrics()
    result = build_analysis(metrics)
    assert result["facts"]["deal_structure.loan_to_cost"]["value"] == 60
    metrics["deal_structure"]["total_project_cost"] = 2000000
    assert build_analysis(metrics)["facts"]["deal_structure.loan_to_cost"]["value"] == 30
    metrics["_provenance"]["deal_structure.total_project_cost"] = {"status": "wrong"}
    assert "loan_to_cost" not in build_analysis(metrics)["accepted_metrics"]["deal_structure"]


def test_explicit_different_investor_classes_do_not_mix():
    metrics = manual_metrics()
    metrics["target_returns"]["hold_scenario"]["target_irr"] = 14
    path = "target_returns.hold_scenario.target_irr"
    metrics["_provenance"][path] = {"status": "manual"}
    metrics["_fact_context"] = {path: {"investor_class": "Class B"}, "target_returns.hold_scenario.cash_on_cash_return": {"investor_class": "Class A"}}
    result = build_analysis(metrics)
    assert result["returns"]["target_irr"] is None
    assert result["returns"]["cash_on_cash"] is None
    metrics["_analysis_context"] = {"investor_class": "Class A"}
    result = build_analysis(metrics)
    assert result["returns"]["cash_on_cash"] == 8
    assert result["returns"]["target_irr"] is None


@pytest.mark.parametrize("value", [True, float("nan"), float("inf"), "8-12%"])
def test_non_numeric_point_values_cannot_become_headlines(value):
    metrics = manual_metrics()
    metrics["target_returns"]["hold_scenario"]["cash_on_cash_return"] = value
    assert build_analysis(metrics)["returns"]["cash_on_cash"] is None


@pytest.mark.asyncio
async def test_snapshot_history_resolution_and_stale_revision_are_atomic(client):
    deal_id = (await client.post("/api/deals", json={"project_name": "Snapshot test"})).json()["id"]
    await client.put(f"/api/deals/{deal_id}", json={"metrics": manual_metrics()})
    original = (await client.get(f"/api/deals/{deal_id}")).json()
    old_version = original["analysis"]["version"]
    assert original["analysis"]["facts"]["deal_structure.loan_to_cost"]["value"] == 60
    payload = {"expected_revision": original["revision"], "reason": "Updated signed budget", "fields": [{"path": "deal_structure.total_project_cost", "value": 2000000}]}
    saved = await client.post(f"/api/deals/{deal_id}/analysis/resolve", json=payload)
    assert saved.status_code == 200, saved.text
    assert saved.json()["analysis"]["facts"]["deal_structure.loan_to_cost"]["value"] == 30
    assert saved.json()["analysis"]["version"] > old_version
    assert (await client.post(f"/api/deals/{deal_id}/analysis/resolve", json=payload)).status_code == 409
    historic = (await client.get(f"/api/deals/{deal_id}/analysis/{old_version}")).json()
    assert historic == original["analysis"]
    current = (await client.get(f"/api/deals/{deal_id}")).json()
    assert current["metrics"]["_locks"]["deal_structure.total_project_cost"] is True
    before = current["analysis"]["version"]
    await client.put(f"/api/deals/{deal_id}", json={"notes": "An ordinary note"})
    assert (await client.get(f"/api/deals/{deal_id}")).json()["analysis"]["version"] == before


@pytest.mark.asyncio
async def test_concurrent_old_result_cannot_overwrite_manual_edit(client):
    from app.database import async_session
    from app.models import Deal
    from sqlalchemy.orm.exc import StaleDataError
    deal_id = (await client.post("/api/deals", json={"project_name": "Concurrent test"})).json()["id"]
    async with async_session() as slow, async_session() as fast:
        old = await slow.get(Deal, deal_id)
        fresh = await fast.get(Deal, deal_id)
        fresh.metrics = manual_metrics()
        await fast.commit()
        old.metrics = {"target_returns": {"target_irr": 99}}
        with pytest.raises(StaleDataError):
            await slow.commit()
        await slow.rollback()
    actual = (await client.get(f"/api/deals/{deal_id}")).json()
    assert actual["analysis"]["returns"]["cash_on_cash"] == 8
    assert "target_irr" not in actual["metrics"]["target_returns"]


@pytest.mark.asyncio
async def test_resolution_validation_rolls_back_all_fields(client):
    deal_id = (await client.post("/api/deals", json={"project_name": "Atomic validation"})).json()["id"]
    original = (await client.get(f"/api/deals/{deal_id}")).json()
    result = await client.post(f"/api/deals/{deal_id}/analysis/resolve", json={"expected_revision": original["revision"], "reason": "Reviewed source", "fields": [
        {"path": "deal_structure.debt_amount", "value": 1000}, {"path": "deal_structure.magic_score", "value": 100}]})
    assert result.status_code == 422
    actual = (await client.get(f"/api/deals/{deal_id}")).json()
    assert actual["analysis"] == original["analysis"]


@pytest.mark.asyncio
async def test_document_deletion_invalidates_source_supported_returns(client):
    from app.database import async_session
    from app.models import Deal, DealDocument
    deal_id = (await client.post("/api/deals", json={"project_name": "Source version"})).json()["id"]
    async with async_session() as db:
        doc = DealDocument(deal_id=deal_id, filename="Memo.pdf", file_path="", file_sha256="a", page_count=5)
        db.add(doc)
        await db.flush()
        deal = await db.get(Deal, deal_id)
        metrics = manual_metrics()
        metrics["_provenance"]["target_returns.hold_scenario.cash_on_cash_return"] = {"status": "confirmed", "source_doc_id": doc.id, "source_page": 2, "source_document_hash": "a"}
        deal.metrics = metrics
        await db.commit()
        assert deal.analysis_snapshot["returns"]["cash_on_cash"] == 8
        await db.delete(doc)
        await db.commit()
        assert deal.analysis_snapshot["returns"]["cash_on_cash"] is None

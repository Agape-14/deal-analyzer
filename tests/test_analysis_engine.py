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


def test_changed_document_package_rechecks_sources_without_erasing_manual_decisions():
    from app.services.analysis import digest
    metrics = manual_metrics()
    path = "target_returns.hold_scenario.cash_on_cash_return"
    docs = [{"id": 1, "filename": "Memo.pdf", "content_hash": "a", "page_count": 5}]
    metrics["_provenance"][path] = {"status": "confirmed", "source_doc_id": 1, "source_page": 2, "source_document_hash": "a"}
    metrics["_verified_document_set"] = digest(docs)
    assert build_analysis(metrics, docs)["returns"]["cash_on_cash"] == 8
    docs.append({"id": 2, "filename": "Update.pdf", "content_hash": "b", "page_count": 3})
    analysis = build_analysis(metrics, docs)
    assert analysis["returns"]["cash_on_cash"] is None
    assert analysis["facts"]["deal_structure.debt_amount"]["state"] == "manual"


@pytest.mark.parametrize("path,value", [("project_details.unit_count", 1.5), ("deal_structure.debt_amount", -1), ("deal_structure.ltv", 120)])
def test_invalid_units_and_bounds_cannot_be_accepted(path, value):
    from app.services.analysis import set_path
    metrics = manual_metrics()
    set_path(metrics, path, value)
    metrics["_provenance"][path] = {"status": "manual"}
    assert build_analysis(metrics)["facts"][path]["state"] == "missing"


def test_checked_sources_do_not_bypass_funding_or_ratio_reconciliation():
    metrics = manual_metrics()
    metrics["deal_structure"]["debt_amount"] = 700000
    metrics["deal_structure"]["loan_to_cost"] = 90
    metrics["_provenance"]["deal_structure.loan_to_cost"] = {"status": "manual", "locked": True}
    analysis = build_analysis(metrics)
    assert analysis["status"] == "questions"
    debt = next(q for q in analysis["questions"] if q["area"] == "Debt")
    assert {i["path"] for i in debt["issues"]} >= {"deal_structure.debt_amount", "deal_structure.total_equity_required", "deal_structure.total_project_cost"}
    assert analysis["facts"]["deal_structure.loan_to_cost"]["state"] == "disputed"
    assert "loan_to_cost" not in analysis["accepted_metrics"]["deal_structure"]
    assert metrics["deal_structure"]["loan_to_cost"] == 90  # raw locked record preserved


def test_scores_exclude_unknown_and_unsupported_source_fields():
    from types import SimpleNamespace
    from app.services.analysis import score_accepted_deal
    metrics = manual_metrics()
    deal = SimpleNamespace(property_type="multifamily", documents=[])
    baseline = score_accepted_deal(deal, metrics)
    metrics["market_location"] = {"walk_score": 100, "market_rent_growth": 99}
    metrics["sponsor_evaluation"] = {"alignment_score": 10, "full_cycle_deals": 100}
    metrics["target_returns"]["sale_scenario"] = {"sale_irr": 99}
    changed = score_accepted_deal(deal, metrics)
    assert changed["provisional_overall"] == baseline["provisional_overall"]
    assert changed["market"] == baseline["market"]
    assert changed["sponsor"] == baseline["sponsor"]
    assert changed["input_policy"] == "accepted-facts-v1"


@pytest.mark.asyncio
async def test_history_includes_removed_optional_facts(client):
    deal_id = (await client.post("/api/deals", json={"project_name": "Removed source fact"})).json()["id"]
    metrics = manual_metrics()
    metrics["project_details"]["construction_type"] = "Wood"
    await client.put(f"/api/deals/{deal_id}", json={"metrics": metrics})
    del metrics["project_details"]["construction_type"]
    await client.put(f"/api/deals/{deal_id}", json={"metrics": metrics})
    current = (await client.get(f"/api/deals/{deal_id}")).json()
    removed = next(c for c in current["analysis"]["changes"] if c["path"] == "project_details.construction_type")
    assert removed["state"] == "removed"
    assert removed["previous_value"] == "Wood"


@pytest.mark.asyncio
async def test_json_guard_forwards_scoped_verification_options(client, monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from app.services import deal_verifier, json_parser_guard
    verifier = AsyncMock(return_value={"verified_fields": []})
    verifier._metrics_object_guard = False
    monkeypatch.setattr(deal_verifier, "verify_deal_metrics", verifier)
    json_parser_guard.install_deal_verifier_json_guard()
    deal = SimpleNamespace(metrics={})
    await deal_verifier.verify_deal_metrics(deal, None, sections=["target_returns"])
    verifier.assert_awaited_once_with(deal, None, sections=["target_returns"])


def test_manual_resolution_replaces_conflicting_dotted_aliases():
    from app.services.data_integrity import mark_manual_edit
    metrics = manual_metrics()
    metrics["target_returns"]["hold_scenario.cash_on_cash_return"] = 11
    metrics["target_returns.hold_scenario"] = {"cash_on_cash_return": 12}
    mark_manual_edit(metrics, "target_returns.hold_scenario.cash_on_cash_return", 9)
    assert build_analysis(metrics)["returns"]["cash_on_cash"] == 9


def test_verification_preserves_manual_reason_but_surfaces_a_source_challenge():
    from app.services.data_integrity import mark_manual_edit, stamp_verification
    path = "target_returns.hold_scenario.cash_on_cash_return"
    metrics = mark_manual_edit(manual_metrics(), path, 8)
    metrics["_provenance"][path]["verification_note"] = "Analyst checked signed terms"
    row = {"section": "target_returns", "field": "hold_scenario.cash_on_cash_return", "status": "confirmed", "source": "Memo.pdf page 1"}
    stamp_verification(metrics, {"audit_results": [row]})
    assert build_analysis(metrics)["facts"][path]["state"] == "manual"
    assert metrics["_provenance"][path]["verification_note"] == "Analyst checked signed terms"
    row.update(status="wrong", note="Memo says 6 percent")
    stamp_verification(metrics, {"audit_results": [row]})
    assert build_analysis(metrics)["facts"][path]["state"] == "disputed"
    assert metrics["target_returns"]["hold_scenario"]["cash_on_cash_return"] == 8
    assert metrics["_locks"][path] is True


@pytest.mark.asyncio
async def test_legacy_preview_is_read_only_and_adoption_checks_revision(client):
    from sqlalchemy import delete, update
    from app.database import async_session
    from app.models import Deal, AnalysisSnapshot
    deal_id = (await client.post("/api/deals", json={"project_name": "Legacy migration"})).json()["id"]
    async with async_session() as db:
        await db.execute(delete(AnalysisSnapshot).where(AnalysisSnapshot.deal_id == deal_id))
        await db.execute(update(Deal).where(Deal.id == deal_id).values(metrics=manual_metrics(), analysis_snapshot=None, analysis_version=0))
        await db.commit()
    preview = (await client.get(f"/api/deals/{deal_id}/analysis/preview")).json()
    assert preview["candidate"]["returns"]["cash_on_cash"] == 8
    assert (await client.get(f"/api/deals/{deal_id}/analysis/history")).json() == []
    payload = {"expected_revision": preview["expected_revision"], "input_hash": preview["candidate"]["input_hash"]}
    assert (await client.post(f"/api/deals/{deal_id}/analysis/adopt", json={**payload, "input_hash": "0" * 64})).status_code == 409
    saved = await client.post(f"/api/deals/{deal_id}/analysis/adopt", json=payload)
    assert saved.status_code == 200, saved.text
    assert saved.json()["analysis"]["version"] == 1
    actual = (await client.get(f"/api/deals/{deal_id}")).json()
    assert actual["metrics"] == manual_metrics()


@pytest.mark.asyncio
async def test_restore_creates_new_revision_preserves_history_and_rechecks_current_sources(client):
    from app.database import async_session
    from app.models import Deal, DealDocument
    deal_id = (await client.post("/api/deals", json={"project_name": "Restorable source"})).json()["id"]
    async with async_session() as db:
        doc = DealDocument(deal_id=deal_id, filename="Memo.pdf", file_path="", file_sha256="a", page_count=5)
        db.add(doc)
        await db.flush()
        deal = await db.get(Deal, deal_id)
        metrics = manual_metrics()
        metrics["_provenance"]["target_returns.hold_scenario.cash_on_cash_return"] = {"status": "confirmed", "source_doc_id": doc.id, "source_page": 2, "source_document_hash": "a"}
        deal.metrics = metrics
        await db.commit()
        previous = copy.deepcopy(deal.analysis_snapshot)
        version = deal.analysis_version
        metrics = copy.deepcopy(metrics)
        metrics["deal_structure"]["total_project_cost"] = 2000000
        metrics["deal_structure"]["total_equity_required"] = 1400000
        deal.metrics = metrics
        await db.delete(doc)
        await db.commit()
    current = (await client.get(f"/api/deals/{deal_id}")).json()
    request = {"expected_revision": current["revision"], "reason": "Restore original funding inputs"}
    restored = await client.post(f"/api/deals/{deal_id}/analysis/{version}/restore", json=request)
    assert restored.status_code == 200, restored.text
    analysis = restored.json()["analysis"]
    assert analysis["version"] > current["analysis"]["version"]
    assert analysis["facts"]["deal_structure.total_project_cost"]["value"] == 1000000
    assert analysis["returns"]["cash_on_cash"] is None  # deleted evidence stays unavailable
    assert (await client.get(f"/api/deals/{deal_id}/analysis/{version}")).json() == previous
    assert (await client.post(f"/api/deals/{deal_id}/analysis/{version}/restore", json=request)).status_code == 409

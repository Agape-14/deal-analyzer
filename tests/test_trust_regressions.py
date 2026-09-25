"""Regression checks for facts, scenarios and the correction lifecycle."""
import copy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services.canonical_metrics import canonical_return_summary, primary_strategy
from app.services.deal_extractor import _post_process_metrics
from app.services.deal_verifier import apply_corrections
from app.services.data_integrity import stamp_verification
from app.services.math_checker import run_math_checks
from app.services.cashflow_projector import project_cash_flows, _periodic_irr


def test_post_processing_preserves_semantics_and_locked_source_values():
    metrics = {
        "target_returns": {"primary_strategy": "hold", "target_irr": 19, "target_cash_on_cash": 8},
        "deal_structure": {"total_project_cost": 1000, "debt_amount": 600, "ltv": 50,
                          "construction_loan_amount": 500, "permanent_loan_amount": 600,
                          "interest_rate": 5},
        "project_details": {"unit_count": 10, "price_per_unit": 75},
        "financial_projections": {"stabilized_noi": 100},
        "_locks": {"deal_structure.ltv": True},
    }
    before = copy.deepcopy(metrics)
    _post_process_metrics(metrics)
    assert metrics["target_returns"] == before["target_returns"]
    for field in before["deal_structure"]:
        assert metrics["deal_structure"][field] == before["deal_structure"][field]
    assert metrics["project_details"] == before["project_details"]
    assert metrics["deal_structure"]["loan_to_cost"] == 60
    assert metrics["underwriting_checks"].get("dscr") is None
    assert metrics["_provenance"]["deal_structure.loan_to_cost"]["status"] == "extracted"
    assert not any(c["check"] == "LTV = Debt / Total Cost" for c in run_math_checks(metrics))


def test_partial_capital_stack_is_not_a_total_cost():
    metrics = {"deal_structure": {"total_equity_required": 1000}}
    _post_process_metrics(metrics)
    assert metrics["deal_structure"].get("total_project_cost") is None


@pytest.mark.parametrize("status", ["wrong", "unverifiable", "stale", "math_failed"])
def test_rejected_return_never_becomes_headline(status):
    metrics = {"target_returns": {"target_irr": 23},
               "_provenance": {"target_returns.target_irr": {"status": status}}}
    assert canonical_return_summary(metrics)["target_irr"] is None


def test_hypothetical_sale_is_not_hold_multiple_or_irr():
    metrics = {"target_returns": {"primary_strategy": "hold", "net_irr": 21,
        "sale_scenario": {"is_hypothetical": True, "sale_irr": 21, "sale_equity_multiple": 2.4},
        "hold_scenario": {"cash_on_cash_return": 8}}}
    summary = canonical_return_summary(metrics)
    assert summary["target_irr"] is None
    assert summary["target_equity_multiple"] is None
    assert summary["cash_on_cash"] == 8


def test_generic_base_case_does_not_imply_hold():
    assert primary_strategy({"deal_structure": {"business_plan": "Base case is sell in year 3"}}) == "unknown"


@pytest.mark.parametrize("lock", ["_locks", "_provenance"])
def test_correction_respects_both_lock_formats(lock):
    metrics = {"deal_structure": {"ltv": 55}}
    metrics[lock] = {"deal_structure.ltv": True if lock == "_locks" else {"locked": True}}
    result, changes = apply_corrections(metrics, {"audit_results": [{
        "section": "deal_structure", "field": "ltv", "status": "wrong",
        "extracted_value": 55, "correct_value": 60, "source": "Memo.pdf Page 3",
    }]})
    assert result["deal_structure"]["ltv"] == 55
    assert changes == []


def test_corrections_require_evidence_preserve_zero_and_support_nested_paths():
    metrics = {"deal_structure": {"debt_amount": 0}, "target_returns": {"hold_scenario": {"cash_on_cash_return": 7}}}
    result, changes = apply_corrections(metrics, {
        "audit_results": [
            {"section": "deal_structure", "field": "debt_amount", "status": "wrong", "correct_value": 99},
            {"section": "target_returns", "field": "hold_scenario.cash_on_cash_return",
             "status": "wrong", "correct_value": 8, "source": "Memo Page 4"},
        ],
        "missing_data": [{"section": "deal_structure", "field": "debt_amount", "found_value": 50, "source": "Memo Page 4"}],
    })
    assert result["deal_structure"]["debt_amount"] == 0
    assert result["target_returns"]["hold_scenario"]["cash_on_cash_return"] == 8
    assert "hold_scenario.cash_on_cash_return" not in result["target_returns"]
    assert len(changes) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("final_status", ["confirmed", "wrong"])
async def test_corrections_get_one_independent_followup(monkeypatch, final_status):
    import app.services.deal_verifier as verifier
    row = {"section": "deal_structure", "field": "ltv", "status": "wrong",
           "extracted_value": 50, "correct_value": 60, "source": "Memo.pdf Page 3"}
    first = {"audit_results": [row], "summary": {"confidence_score": 85}}
    second = {"audit_results": [{**row, "extracted_value": 60, "correct_value": 65,
                                "status": final_status}]}
    mock = AsyncMock(side_effect=[first, second])
    monkeypatch.setattr(verifier, "verify_deal_metrics", mock)
    deal = SimpleNamespace(metrics={"deal_structure": {"ltv": 50}})
    metrics, audit, changes = await verifier.verify_with_corrections(deal, None)
    metrics = stamp_verification(metrics, audit)
    assert mock.await_count == 2
    assert mock.await_args.kwargs["sections"] == {"deal_structure"}
    assert metrics["deal_structure"]["ltv"] == 60  # No endless correction loop to 65.
    assert metrics["_provenance"]["deal_structure.ltv"]["status"] == final_status
    assert len(changes) == 1


@pytest.mark.asyncio
async def test_failed_followup_is_not_silently_accepted(monkeypatch):
    import app.services.deal_verifier as verifier
    audit = {"audit_results": [{"section": "deal_structure", "field": "ltv",
        "status": "wrong", "correct_value": 60, "source": "Memo Page 3"}]}
    monkeypatch.setattr(verifier, "verify_deal_metrics", AsyncMock(side_effect=[audit, RuntimeError("provider unavailable")]))
    with pytest.raises(RuntimeError, match="provider unavailable"):
        await verifier.verify_with_corrections(SimpleNamespace(metrics={"deal_structure": {"ltv": 50}}), None)


def test_cashflows_withhold_missing_or_disputed_assumptions():
    result = project_cash_flows({})
    assert result["status"] == "unavailable"
    assert result["project_level"] == []
    assert "financial_projections.avg_rent_per_unit" in result["missing_inputs"]


def test_irr_uses_timing_not_multiple_cagr():
    assert _periodic_irr([-100, 10, 110]) == 10
    assert _periodic_irr([-100, 0, 121]) == 10
    assert _periodic_irr([-100, 50, -20, 100]) is None


def test_cashflow_includes_invested_capital_and_does_not_double_discount_gp_share():
    metrics = {
        "project_details": {"unit_count": 10},
        "financial_projections": {"avg_rent_per_unit": 1000, "occupancy_assumption": 100,
            "operating_expense_ratio": 50, "rent_growth_assumption": 0, "exit_cap_rate": 5},
        "deal_structure": {"debt_amount": 0, "hold_period_years": 2,
            "total_equity_required": 1000000, "preferred_return": 8, "gp_equity_coinvest_pct": 10},
    }
    project = project_cash_flows(metrics)
    assert project["summary"]["invested_equity"] == 1000000
    investor = project_cash_flows(metrics, 100000)
    assert investor["lp_level"][1]["amount"] == 6000
    assert investor["summary"]["exit_proceeds"] == 120000
    assert investor["status"] == "illustrative"


def test_unsure_is_not_resolved():
    from app.routers.field_edits import _mark_review_resolved
    metrics = {}
    _mark_review_resolved(metrics, "source:deal_structure.ltv", "unsure")
    assert metrics["_review_resolutions"]["source:deal_structure.ltv"]["resolved"] is False

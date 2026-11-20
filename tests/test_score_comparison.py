"""Scores should only rank against the same evidence and calculation basis."""

from app.services.score_comparison import comparison_basis


def test_partial_scores_can_compare_only_when_all_scored_criteria_match():
    scores = {
        "input_policy": "accepted-facts-v1", "score_policy": "observed-categories-v1",
        "risk": {"score": 7, "weight": 15, "supported_inputs": ["deal_structure.ltv"]},
    }
    facts = {
        "deal_structure.ltv": {"label": "Loan to value", "identity": {"unit": "percent", "debt_phase": "permanent"}},
        "project_details.entitlement_status": {"label": "Approval status", "identity": {"unit": "text"}},
    }
    initial = comparison_basis(scores, facts)["risk"]
    scores["risk"]["score"] = 8
    assert comparison_basis(scores, facts)["risk"] == initial
    scores["risk"]["supported_inputs"].append("project_details.entitlement_status")
    expanded = comparison_basis(scores, facts)["risk"]
    assert expanded["signature"] != initial["signature"]
    assert expanded["inputs"] == ["Loan to value", "Approval status"]


def test_return_score_requires_a_known_period_and_investor_scope():
    path = "target_returns.hold_scenario.cash_on_cash_return"
    scores = {
        "input_policy": "accepted-facts-v1", "score_policy": "observed-categories-v1",
        "returns": {"score": 7, "weight": 20, "supported_inputs": [path]},
    }
    fact = {"unit": "percent", "scenario": "hold", "investor_class": "LP", "basis": "net"}
    limited = comparison_basis(scores, {path: {"identity": fact}})
    assert limited["returns"]["signature"] is None
    early = comparison_basis(scores, {path: {"identity": {**fact, "period": "Annual after stabilization"}}})
    later = comparison_basis(scores, {path: {"identity": {**fact, "period": "Year 5"}}})
    assert early["returns"]["signature"] and later["returns"]["signature"]
    assert early["returns"]["signature"] != later["returns"]["signature"]

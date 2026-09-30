import copy
import pytest
from app.services.analysis import build_analysis, flatten
from app.services.cashflow_projector import project_cash_flows, _timed_irr
from app.services.waterfall_calculator import waterfall_from_deal


def simple_sale():
    metrics = {"target_returns": {"primary_strategy": "sale", "total_project_profit": 1000000},
        "project_details": {"unit_count": 10},
        "financial_projections": {"avg_rent_per_unit": 1000, "occupancy_assumption": 100,
            "operating_expense_ratio": 50, "rent_growth_assumption": 0, "exit_cap_rate": 5},
        "deal_structure": {"debt_amount": 0, "hold_period_years": 2.5, "total_equity_required": 1000000,
            "gp_equity_coinvest_pct": 10, "preferred_return": 8, "waterfall_hurdle_basis": "simple_annual_return",
            "preferred_return_allocation": "pro_rata", "promote_tiers": [{"threshold": 8, "lp_split": 80, "gp_split": 20}]}}
    metrics["_provenance"] = {path: {"status": "manual"} for path in flatten(metrics)}
    return metrics


def test_partial_period_with_growth_uses_annual_noi_at_exit():
    metrics = simple_sale()
    metrics["financial_projections"]["rent_growth_assumption"] = 10
    result = project_cash_flows(metrics)
    assert result["status"] == "illustrative"
    assert [row["gross_revenue"] for row in result["project_level"]] == [120000, 132000, 72600]
    assert result["summary"]["exit_value"] == 1452000
    assert result["summary"]["years_modeled"] == 2.5
    assert _timed_irr([-100, 100 * 1.1 ** 2.5], [0, 2.5]) == 10


def test_subyear_hold_has_one_prorated_period():
    metrics = simple_sale()
    metrics["deal_structure"]["hold_period_years"] = .5
    result = project_cash_flows(metrics)
    assert result["project_level"][0]["year"] == .5
    assert result["project_level"][0]["noi"] == 30000
    assert result["summary"]["exit_value"] == 1200000


@pytest.mark.parametrize("field,value,model", [
    ("refinance_year", 3, "cashflow"), ("refinance_year", 3, "waterfall"),
    ("amortization_years", 30, "cashflow"), ("construction_loan_amount", 500000, "cashflow"),
    ("investor_classes", ["Class A", "Class B"], "waterfall"),
    ("catch_up", "100% GP catch-up", "waterfall"),
])
def test_unsupported_terms_survive_projection_into_accepted_inputs(field, value, model):
    metrics = simple_sale()
    metrics["deal_structure"][field] = value
    accepted = build_analysis(metrics)["accepted_metrics"]
    calculate = project_cash_flows if model == "cashflow" else waterfall_from_deal
    result = calculate(accepted)
    assert result["status"] == "unavailable", result
    assert accepted["_model_limits"][model]


def test_hold_strategy_never_silently_becomes_a_sale_projection():
    metrics = simple_sale()
    metrics["target_returns"]["primary_strategy"] = "hold"
    result = project_cash_flows(metrics)
    assert result["status"] == "unavailable" and "Hold strategies" in result["message"]


def test_missing_class_waterfall_never_becomes_an_lp_forecast():
    result = project_cash_flows(simple_sale(), 10000)
    assert result["status"] == "unavailable" and "actual timed waterfall" in result["message"]

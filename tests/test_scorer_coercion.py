"""Regression tests for numeric coercion in the deal scorer.

The AI extraction prompt asks Claude to emit numeric fields as numbers,
but Claude occasionally returns them as strings (e.g. "12.5", "$50,000",
"5%"). Bare `>=` / `<=` comparisons against those raised
"'>=' not supported between instances of 'str' and 'int'" inside
`_run_extract_background`, which surfaced as the "Document review
incomplete" failure on the deal hero card. Every numeric input to the
scorer must be coerced through `_num` so the pipeline can finish.
"""

from app.services.deal_scorer import _num, _score_range, score_deal


def test_num_handles_common_string_shapes():
    assert _num(12) == 12.0
    assert _num(12.5) == 12.5
    assert _num("12.5") == 12.5
    assert _num("12.5%") == 12.5
    assert _num("$50,000") == 50000.0
    assert _num("  4 ") == 4.0
    assert _num(None) is None
    assert _num("") is None
    assert _num("n/a") is None
    assert _num(True) is None  # bool is not a meaningful metric


def test_score_range_coerces_string_value():
    # Pre-fix: this raised TypeError on the >= comparison
    assert _score_range("8.5", [(10, 10), (8, 8), (6, 5), (0, 2)]) == 8


def test_score_deal_survives_string_encoded_numerics():
    metrics = {
        "deal_structure": {
            "ltv": "65",
            "preferred_return": "8.0",
            "fees_asset_mgmt": "1.5",
            "fees_acquisition": "1.0",
            "gp_equity_coinvest_pct": "6",
        },
        "target_returns": {
            "primary_strategy": "hold",
            "target_irr": "12.5",
            "target_equity_multiple": "1.8",
            "target_cash_on_cash": "8",
            "total_fee_drag": "7",
        },
        "market_location": {
            "market_rent_growth": "2.5",
            "market_job_growth": "2",
            "market_vacancy_rate": "5",
            "walk_score": "70",
        },
        "project_details": {"unit_count": "120", "entitlement_status": "entitled"},
        "financial_projections": {
            "entry_cap_rate": "4.5",
            "exit_cap_rate": "5.0",
            "occupancy_assumption": "95",
            "rent_growth_assumption": "2.5",
            "operating_expense_ratio": "35",
        },
        "underwriting_checks": {
            "break_even_occupancy": "78",
            "dscr": "1.45",
            "yield_on_cost": "6.0",
        },
        "sponsor_evaluation": {
            "sponsor_full_cycle_deals": "5",
            "alignment_score": "7",
        },
    }
    scores = score_deal(metrics, require_verified=False)
    # We do not pin the exact score (it depends on weighting tweaks),
    # just that scoring completes and produces sensible integers.
    assert isinstance(scores["provisional_overall"], (int, float))
    assert 0 <= scores["returns"]["score"] <= 10
    assert 0 <= scores["underwriting"]["score"] <= 10

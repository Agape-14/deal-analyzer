"""Regression tests for the metrics-tree value coercion boundary.

The fundamental fix for the recurring "Document review incomplete"
failures (`'str' object has no attribute 'keys'`,
`'>=' not supported between instances of 'str' and 'int'`, etc.) is to
normalize Claude's loose JSON shape *once* at the trust boundary so
every downstream consumer can rely on the contract.

If anyone ever loosens these tests, the next stringy value from Claude
will crash the pipeline again.
"""

from app.services.json_parser_guard import (
    coerce_metric_values,
    normalize_metrics_tree,
    _coerce_numeric_string,
)


def test_numeric_strings_coerce_to_float():
    assert _coerce_numeric_string("12.5") == 12.5
    assert _coerce_numeric_string("12.5%") == 12.5
    assert _coerce_numeric_string("$50,000") == 50000.0
    assert _coerce_numeric_string("1,234,567.89") == 1234567.89
    assert _coerce_numeric_string("-5") == -5.0
    assert _coerce_numeric_string("  4 ") == 4.0


def test_non_numeric_strings_are_preserved():
    # If we coerced these, downstream display/parse code would break.
    assert _coerce_numeric_string("5 acres") == "5 acres"
    assert _coerce_numeric_string("1BR") == "1BR"
    assert _coerce_numeric_string("Class A") == "Class A"
    assert _coerce_numeric_string("2026-05-15") == "2026-05-15"
    assert _coerce_numeric_string("GP/LP") == "GP/LP"
    assert _coerce_numeric_string("") == ""


def test_coerce_metric_values_recurses_into_nested_dicts_and_lists():
    raw = {
        "deal_structure": {"ltv": "65", "investment_class": "GP/LP"},
        "target_returns": {
            "hold_scenario": {"cash_on_cash_return": "8.5%"},
            "audit_results": [{"extracted_value": "120", "section": "x"}],
        },
    }
    out = coerce_metric_values(raw)
    assert out["deal_structure"]["ltv"] == 65.0
    assert out["deal_structure"]["investment_class"] == "GP/LP"
    assert out["target_returns"]["hold_scenario"]["cash_on_cash_return"] == 8.5
    assert out["target_returns"]["audit_results"][0]["extracted_value"] == 120.0


def test_normalize_metrics_tree_coerces_numeric_strings_inside_sections():
    messy = {
        "deal_structure": {
            "ltv": "65",
            "preferred_return": "8%",
            "investment_class": "GP/LP",
        },
        "project_details": {"unit_count": "120", "unit_mix": "80 1BR, 40 2BR"},
        "financial_projections": {"stabilized_noi": "$2,400,000"},
    }
    clean = normalize_metrics_tree(messy)
    assert clean["deal_structure"]["ltv"] == 65.0
    assert clean["deal_structure"]["preferred_return"] == 8.0
    assert clean["deal_structure"]["investment_class"] == "GP/LP"
    assert clean["project_details"]["unit_count"] == 120.0
    assert clean["project_details"]["unit_mix"] == "80 1BR, 40 2BR"
    assert clean["financial_projections"]["stabilized_noi"] == 2_400_000.0


def test_normalize_does_not_touch_provenance_meta_strings():
    # ISO timestamps in _provenance look numeric to a sloppy regex but
    # are dates. Ensure the boundary leaves meta sections alone so
    # status/audit payloads survive a round trip.
    messy = {
        "_provenance": {
            "deal_structure.ltv": {
                "extracted_at": "2026-05-15T20:11:41Z",
                "source": "extraction",
                "confidence": 86,
            }
        },
        "deal_structure": {"ltv": "65"},
    }
    clean = normalize_metrics_tree(messy)
    prov = clean["_provenance"]["deal_structure.ltv"]
    assert prov["extracted_at"] == "2026-05-15T20:11:41Z"
    assert prov["source"] == "extraction"
    # And the metric section still gets coerced
    assert clean["deal_structure"]["ltv"] == 65.0


def test_full_pipeline_survives_string_encoded_numerics():
    """Inversion check: every downstream consumer should be able to
    process metrics emitted with stringy numbers, without per-consumer
    defensive coercion. The boundary should be enough."""
    from app.services.deal_scorer import score_deal
    from app.services.deal_validator import validate_deal_metrics

    messy = {
        "deal_structure": {
            "ltv": "65",
            "preferred_return": "8%",
            "fees_asset_mgmt": "1.5%",
            "fees_acquisition": "1.0%",
            "gp_equity_coinvest_pct": "6%",
        },
        "target_returns": {
            "primary_strategy": "hold",
            "target_irr": "12.5%",
            "target_cash_on_cash": "8%",
        },
        "underwriting_checks": {
            "dscr": "1.45",
            "break_even_occupancy": "78%",
            "yield_on_cost": "6.0%",
        },
        "financial_projections": {
            "entry_cap_rate": "4.5%",
            "exit_cap_rate": "5.0%",
        },
        "sponsor_evaluation": {
            "alignment_score": "7",
            "sponsor_full_cycle_deals": "5",
        },
    }
    clean = normalize_metrics_tree(messy)
    scores = score_deal(clean, require_verified=False)
    flags = validate_deal_metrics(clean)
    assert isinstance(scores["provisional_overall"], (int, float))
    assert isinstance(flags, list)

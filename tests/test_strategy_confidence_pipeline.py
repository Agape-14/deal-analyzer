import math

from app.routers.deal_pipeline import _pipeline_error_message
from app.services.canonical_metrics import canonical_return_summary, primary_strategy


def _json_safe(value):
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_safe(v) for v in value]
    if isinstance(value, tuple):
        return [_json_safe(v) for v in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def test_hypothetical_sale_does_not_override_preferred_hold_strategy():
    metrics = {
        "target_returns": {
            "hold_scenario": {
                "description": "Preferred plan is a long-term hold after refinance.",
                "cash_on_cash_return": 13.0,
            },
            "sale_scenario": {
                "description": "Theoretical sale scenario for illustrative purposes only.",
                "sale_irr": 22.0,
                "sale_equity_multiple": 2.4,
            },
            "target_irr": 22.0,
        },
        "deal_structure": {
            "exit_strategies": "Base plan is to hold. Sale model is a theoretical downside/upside case.",
        },
    }

    assert primary_strategy(metrics) == "hold_with_sale_option"
    summary = canonical_return_summary(metrics)
    assert summary["primary_strategy"] == "hold_with_sale_option"
    assert summary["target_irr"] is None
    assert summary["target_irr_path"] is None
    assert summary["cash_on_cash"] == 13.0
    assert summary["cash_on_cash_path"] == "target_returns.hold_scenario.cash_on_cash_return"


def test_pipeline_rate_limit_errors_are_user_readable():
    message = _pipeline_error_message(Exception("Anthropic API error 429: rate limit exceeded"))

    assert "rate limit" in message.lower()
    assert "review documents again" in message.lower()


def test_json_safe_removes_non_finite_numbers_from_metrics():
    clean = _json_safe({"good": 1.2, "bad": math.nan, "nested": [math.inf]})

    assert clean == {"good": 1.2, "bad": None, "nested": [None]}

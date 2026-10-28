from datetime import date
from types import SimpleNamespace as Row

from app.services.portfolio_analytics import investment_performance, portfolio_analytics


def position(**changes):
    values = dict(id=1, investment_date=date(2024, 1, 1), amount_invested=1000,
                  distributions=[], status="active", exit_amount=None, exit_date=None,
                  residual_value=None, valuation_date=None, projected_irr=None,
                  projected_equity_multiple=None, sponsor_name="Before", developer=Row(name="Renamed"))
    return Row(**(values | changes))


def test_active_position_without_nav_has_cash_measures_only():
    p = investment_performance(position(distributions=[Row(date=date(2025, 1, 1), amount=100, dist_type="cash_flow")]))
    assert p["dpi"] == p["multiple"] == 0.1
    assert p["tvpi"] is None and p["irr"] is None


def test_dated_nav_produces_total_value_without_changing_cash():
    p = investment_performance(position(residual_value=1100, valuation_date=date(2025, 1, 1)))
    assert p["dpi"] == 0 and p["tvpi"] == 1.1
    assert 9 < p["irr"] < 11


def test_exit_sale_distributions_count_once_in_all_totals():
    inv = position(status="exited", exit_date=date(2025, 1, 1), exit_amount=1200,
                   distributions=[Row(date=date(2024, 6, 1), amount=100, dist_type="cash_flow"),
                                  Row(date=date(2025, 1, 1), amount=1200, dist_type="sale_proceeds")])
    p, summary = investment_performance(inv), portfolio_analytics([inv])["summary"]
    assert p["total_returned"] == summary["total_returned"] == 1300
    assert p["dpi"] == p["tvpi"] == summary["tvpi"] == 1.3
    assert p["cumulative_timeseries"][-1]["cumulative_distributions"] == 1300
    assert p["irr"] is not None


def test_portfolio_requires_aligned_complete_valuations_and_uses_stable_sponsor():
    first = position(residual_value=1100, valuation_date=date(2025, 1, 1))
    second = position(id=2, residual_value=900, valuation_date=date(2025, 2, 1))
    result = portfolio_analytics([first, second])
    assert not result["summary"]["valuation_complete"] and result["summary"]["tvpi"] is None
    assert result["summary"]["overall_irr_pct"] is None
    assert result["top_performers"] == []  # Active NAV is not a realized track record.
    assert result["by_sponsor"][0]["name"] == "Renamed"
    second.valuation_date = first.valuation_date
    assert portfolio_analytics([first, second])["summary"]["tvpi"] == 1


def test_missing_cashflow_date_or_stale_nav_withholds_total_value_irr():
    inv = position(residual_value=1000, valuation_date=date(2025, 1, 1),
                   distributions=[Row(date=None, amount=100, dist_type="cash_flow")])
    assert investment_performance(inv)["irr"] is None
    inv.distributions[0].date = date(2025, 2, 1)
    assert investment_performance(inv)["tvpi"] is None

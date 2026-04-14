"""Tests for the xirr() overflow bug we fixed in phase 4 and the
portfolio analytics aggregator."""

from datetime import date, timedelta

from app.services.portfolio_analytics import xirr


def test_xirr_basic():
    # Classic 10% return over 1 year: -1000 -> 1100
    r = xirr([(date(2024, 1, 1), -1000), (date(2025, 1, 1), 1100)])
    assert r is not None
    assert 0.09 < r < 0.11


def test_xirr_all_positive_returns_none():
    # Degenerate: no investment.
    assert xirr([(date(2024, 1, 1), 100), (date(2024, 6, 1), 200)]) is None


def test_xirr_all_negative_returns_none():
    assert xirr([(date(2024, 1, 1), -100), (date(2024, 6, 1), -50)]) is None


def test_xirr_does_not_overflow_on_extreme_jcurve():
    """Regression test for the bug we fixed in phase 4.

    Deep J-curve portfolios used to trigger OverflowError in Newton's
    method. The limiter + safe_pow fix should either return a sane rate
    or None — never raise.
    """
    flows = [(date(2022, 1, 1), -1_000_000)]
    for i in range(10):
        # Tiny distributions against a huge investment — model is
        # underwater and Newton's method will chase unrealistic rates.
        flows.append((date(2022, 1, 1) + timedelta(days=90 * (i + 1)), 1500))
    r = xirr(flows)
    # Either None (no convergence) or a number — no exception.
    assert r is None or isinstance(r, float)


def test_xirr_clamps_rate_to_reasonable_band():
    """Even on pathological inputs the final rate should be in (-1, ~100]."""
    flows = [
        (date(2024, 1, 1), -100_000),
        (date(2024, 2, 1), 50_000_000),  # absurdly positive
    ]
    r = xirr(flows)
    if r is not None:
        assert -1 < r <= 100

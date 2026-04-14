"""Portfolio analytics.

Computes performance metrics and time-series data from investments &
distributions for the Portfolio page.

Everything here is deterministic — zero AI. Functions accept plain dicts /
model instances and return JSON-safe dicts.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Iterable


def xirr(flows: list[tuple[date, float]], guess: float = 0.1) -> float | None:
    """Compute IRR for irregular cash flows using Newton's method.

    Each flow is (date, amount). Negative amounts are outflows (investment),
    positive amounts are inflows (distribution, exit). Returns the annualized
    IRR as a decimal (e.g. 0.12 == 12%), or None if it doesn't converge or
    there are fewer than two flows of opposite sign.
    """
    if len(flows) < 2:
        return None
    if not any(f[1] > 0 for f in flows) or not any(f[1] < 0 for f in flows):
        return None

    flows = sorted(flows, key=lambda f: f[0])
    t0 = flows[0][0]

    def years_from_start(d: date) -> float:
        return (d - t0).days / 365.25

    def safe_pow(base: float, exp: float) -> float | None:
        # (1 + rate) ** years can overflow for large rates * long horizons.
        # Return None to signal "too big" so callers can fall through.
        try:
            return base ** exp
        except OverflowError:
            return None

    def npv(rate: float) -> float:
        # Avoid division by zero / domain errors
        if rate <= -1:
            return float("inf")
        total = 0.0
        for d, amt in flows:
            p = safe_pow(1 + rate, years_from_start(d))
            if p is None:
                # At very high rates, terms discount to ~0; treat as 0
                continue
            total += amt / p
        return total

    def dnpv(rate: float) -> float:
        if rate <= -1:
            return float("inf")
        total = 0.0
        for d, amt in flows:
            t = years_from_start(d)
            if t == 0:
                continue
            p = safe_pow(1 + rate, t + 1)
            if p is None:
                continue
            total -= t * amt / p
        return total

    rate = guess
    for _ in range(80):
        f = npv(rate)
        if abs(f) < 1e-7:
            return round(rate, 6)
        df = dnpv(rate)
        if df == 0:
            break
        new_rate = rate - f / df
        # Guard against divergence — clamp to a sane band.
        if new_rate <= -0.999:
            new_rate = (rate - 0.999) / 2
        if new_rate > 100:
            new_rate = min(100.0, rate + 1.0)
        if abs(new_rate - rate) < 1e-9:
            return round(new_rate, 6)
        rate = new_rate

    # Fall back to a bisection search over a reasonable range if Newton failed
    lo, hi = -0.99, 10.0
    f_lo, f_hi = npv(lo), npv(hi)
    if f_lo * f_hi > 0:
        return None
    for _ in range(80):
        mid = (lo + hi) / 2
        f_mid = npv(mid)
        if abs(f_mid) < 1e-7:
            return round(mid, 6)
        if f_lo * f_mid < 0:
            hi, f_hi = mid, f_mid
        else:
            lo, f_lo = mid, f_mid
    return None


def investment_cashflows(inv) -> list[tuple[date, float]]:
    """Build the ordered cash-flow list for a single Investment.

    Negative = money in (our investment). Positive = money out (distributions,
    exit proceeds).
    """
    flows: list[tuple[date, float]] = []
    if inv.investment_date and inv.amount_invested:
        flows.append((inv.investment_date, -float(inv.amount_invested)))
    for d in inv.distributions or []:
        if d.date and d.amount:
            flows.append((d.date, float(d.amount)))
    if inv.exit_date and inv.exit_amount:
        flows.append((inv.exit_date, float(inv.exit_amount)))
    return flows


def investment_performance(inv) -> dict:
    """Compute performance metrics and time-series for a single investment."""
    invested = float(inv.amount_invested or 0)
    distributions = sorted(inv.distributions or [], key=lambda d: d.date or date.min)
    total_dist = sum(float(d.amount) for d in distributions if d.amount)
    exit_amount = float(inv.exit_amount or 0)
    total_returned = total_dist + exit_amount

    multiple = round(total_returned / invested, 4) if invested > 0 else 0.0
    dpi = round(total_dist / invested, 4) if invested > 0 else 0.0  # Distributions / Paid-In
    tvpi = multiple  # Same thing when we don't track unrealized NAV separately

    flows = investment_cashflows(inv)
    irr = xirr(flows)

    # Cumulative distribution timeseries (for charts)
    cumulative = []
    running = 0.0
    for d in distributions:
        if not d.date:
            continue
        running += float(d.amount or 0)
        cumulative.append({
            "date": d.date.isoformat(),
            "cumulative_distributions": round(running, 2),
            "cumulative_multiple": round(running / invested, 4) if invested > 0 else 0,
        })
    if inv.exit_date and exit_amount:
        running += exit_amount
        cumulative.append({
            "date": inv.exit_date.isoformat(),
            "cumulative_distributions": round(running, 2),
            "cumulative_multiple": round(running / invested, 4) if invested > 0 else 0,
            "is_exit": True,
        })

    # Years held
    years_held = None
    if inv.investment_date:
        end_date = inv.exit_date or date.today()
        years_held = round((end_date - inv.investment_date).days / 365.25, 2)

    # Projected vs actual
    projected_irr = float(inv.projected_irr) if inv.projected_irr is not None else None
    projected_multiple = (
        float(inv.projected_equity_multiple)
        if inv.projected_equity_multiple is not None
        else None
    )
    actual_irr_pct = round(irr * 100, 2) if irr is not None else None
    irr_vs_projected = (
        round(actual_irr_pct - projected_irr, 2)
        if actual_irr_pct is not None and projected_irr is not None
        else None
    )

    return {
        "investment_id": inv.id,
        "invested": invested,
        "total_distributions": round(total_dist, 2),
        "exit_amount": exit_amount,
        "total_returned": round(total_returned, 2),
        "net_profit": round(total_returned - invested, 2),
        "multiple": multiple,
        "dpi": dpi,
        "tvpi": tvpi,
        "irr": actual_irr_pct,
        "years_held": years_held,
        "projected_irr": projected_irr,
        "projected_multiple": projected_multiple,
        "irr_vs_projected": irr_vs_projected,
        "cashflow_count": len(flows),
        "cumulative_timeseries": cumulative,
    }


def portfolio_analytics(investments: Iterable) -> dict:
    """Aggregate analytics for the whole portfolio."""
    investments = list(investments)

    total_invested = 0.0
    total_distributions = 0.0
    total_exit_proceeds = 0.0
    per_investment = []
    by_status: dict[str, dict] = {}
    by_sponsor: dict[str, dict] = {}
    all_flows: list[tuple[date, float]] = []

    for inv in investments:
        perf = investment_performance(inv)
        per_investment.append(perf)

        invested = float(inv.amount_invested or 0)
        total_invested += invested
        total_distributions += perf["total_distributions"]
        total_exit_proceeds += perf["exit_amount"]
        all_flows.extend(investment_cashflows(inv))

        # Group by status
        s = inv.status or "active"
        bucket = by_status.setdefault(s, {"count": 0, "invested": 0.0, "returned": 0.0})
        bucket["count"] += 1
        bucket["invested"] += invested
        bucket["returned"] += perf["total_returned"]

        # Group by sponsor
        sp = (inv.sponsor_name or "Unknown").strip() or "Unknown"
        sb = by_sponsor.setdefault(sp, {"count": 0, "invested": 0.0, "returned": 0.0})
        sb["count"] += 1
        sb["invested"] += invested
        sb["returned"] += perf["total_returned"]

    total_returned = total_distributions + total_exit_proceeds
    overall_multiple = round(total_returned / total_invested, 4) if total_invested > 0 else 0.0
    overall_irr = xirr(all_flows)

    # Build timeseries: cumulative invested vs cumulative returned over time
    events: list[tuple[date, float, float]] = []  # (date, invested_delta, returned_delta)
    for inv in investments:
        if inv.investment_date and inv.amount_invested:
            events.append((inv.investment_date, float(inv.amount_invested), 0.0))
        for d in inv.distributions or []:
            if d.date and d.amount:
                events.append((d.date, 0.0, float(d.amount)))
        if inv.exit_date and inv.exit_amount:
            events.append((inv.exit_date, 0.0, float(inv.exit_amount)))
    events.sort(key=lambda e: e[0])

    timeseries = []
    inv_cum = 0.0
    ret_cum = 0.0
    for d, inv_delta, ret_delta in events:
        inv_cum += inv_delta
        ret_cum += ret_delta
        timeseries.append({
            "date": d.isoformat(),
            "cumulative_invested": round(inv_cum, 2),
            "cumulative_returned": round(ret_cum, 2),
            "net_position": round(ret_cum - inv_cum, 2),
            "multiple": round(ret_cum / inv_cum, 4) if inv_cum > 0 else 0,
        })

    # Normalize group data — compute shares
    def _finalize_groups(groups: dict[str, dict]) -> list[dict]:
        rows = []
        for name, g in groups.items():
            rows.append({
                "name": name,
                "count": g["count"],
                "invested": round(g["invested"], 2),
                "returned": round(g["returned"], 2),
                "share_pct": round(g["invested"] / total_invested * 100, 2)
                    if total_invested > 0 else 0,
                "multiple": round(g["returned"] / g["invested"], 4)
                    if g["invested"] > 0 else 0,
            })
        rows.sort(key=lambda r: -r["invested"])
        return rows

    # Top / bottom performers
    with_irr = [p for p in per_investment if p["irr"] is not None]
    top_performers = sorted(with_irr, key=lambda p: -p["irr"])[:5]
    bottom_performers = sorted(with_irr, key=lambda p: p["irr"])[:5]

    return {
        "summary": {
            "total_invested": round(total_invested, 2),
            "total_distributions": round(total_distributions, 2),
            "total_exit_proceeds": round(total_exit_proceeds, 2),
            "total_returned": round(total_returned, 2),
            "net_profit": round(total_returned - total_invested, 2),
            "overall_multiple": overall_multiple,
            "overall_irr_pct": round(overall_irr * 100, 2) if overall_irr is not None else None,
            "investment_count": len(investments),
        },
        "per_investment": per_investment,
        "by_status": _finalize_groups(by_status),
        "by_sponsor": _finalize_groups(by_sponsor),
        "timeseries": timeseries,
        "top_performers": top_performers,
        "bottom_performers": bottom_performers,
    }

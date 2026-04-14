"""Waterfall Distribution Calculator — computes tiered LP/GP splits."""

import os
import json
from typing import Optional


def _safe_float(val, default=0.0):
    if val is None:
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def parse_promote_tiers(promote_text: str) -> list[dict]:
    """Parse promote structure text into tiers.
    
    Common formats:
    - "80/20 split above 8% pref, 50/50 above 15%"
    - "8% preferred return, then 80/20 to 15% IRR, then 50/50"
    - Just returns a default if parsing fails
    """
    tiers = []
    if not promote_text:
        return [
            {"threshold": 8, "lp_split": 80, "gp_split": 20},
            {"threshold": 15, "lp_split": 50, "gp_split": 50},
        ]

    text = promote_text.lower()

    # Try to find patterns like "80/20" or "70/30"
    import re
    splits = re.findall(r'(\d+)\s*/\s*(\d+)', text)
    thresholds = re.findall(r'(\d+(?:\.\d+)?)\s*%', text)

    if splits and thresholds:
        # Match splits to thresholds
        used_thresholds = []
        for t in thresholds:
            tv = float(t)
            if tv <= 30:  # Likely a return threshold, not a split
                used_thresholds.append(tv)

        for i, (lp, gp) in enumerate(splits):
            lp_val, gp_val = int(lp), int(gp)
            # Ensure LP is the larger number
            if gp_val > lp_val:
                lp_val, gp_val = gp_val, lp_val
            threshold = used_thresholds[i] if i < len(used_thresholds) else (8 + i * 7)
            tiers.append({"threshold": threshold, "lp_split": lp_val, "gp_split": gp_val})

    if not tiers:
        # Default waterfall
        tiers = [
            {"threshold": 8, "lp_split": 80, "gp_split": 20},
            {"threshold": 15, "lp_split": 50, "gp_split": 50},
        ]

    return sorted(tiers, key=lambda t: t["threshold"])


def calculate_waterfall(
    total_equity: float,
    lp_equity: float,
    gp_equity: float,
    preferred_return: float,
    promote_tiers: list[dict],
    hold_years: float,
    total_profit: float,
    investment_amount: float = None,
) -> dict:
    """
    Calculate waterfall distributions step by step.
    
    Args:
        total_equity: Total equity raised
        lp_equity: LP portion of equity
        gp_equity: GP portion of equity
        preferred_return: Annual preferred return %
        promote_tiers: List of {"threshold": %, "lp_split": %, "gp_split": %}
        hold_years: Number of years held
        total_profit: Total distributable cash above return of capital
        investment_amount: Individual LP investment (optional)
    """
    if total_equity <= 0:
        return {"tiers": [], "totals": {}}

    lp_pct_of_equity = lp_equity / total_equity if total_equity > 0 else 0.95
    gp_pct_of_equity = gp_equity / total_equity if total_equity > 0 else 0.05
    investor_pct = (investment_amount / lp_equity) if (investment_amount and lp_equity > 0) else 0

    tiers_result = []
    remaining_profit = total_profit

    # Tier 0: Return of Capital
    roc_total = total_equity
    roc_lp = lp_equity
    roc_gp = gp_equity

    tiers_result.append({
        "name": "Return of Capital",
        "total": round(roc_total),
        "lp_amount": round(roc_lp),
        "gp_amount": round(roc_gp),
        "lp_pct": round(lp_pct_of_equity * 100, 1),
        "gp_pct": round(gp_pct_of_equity * 100, 1),
        "your_amount": round(investment_amount) if investment_amount else None,
    })

    # Tier 1: Preferred Return
    pref_rate = preferred_return / 100.0
    pref_total = total_equity * pref_rate * hold_years
    pref_actual = min(pref_total, remaining_profit)
    remaining_profit -= pref_actual

    pref_lp = pref_actual * lp_pct_of_equity
    pref_gp = pref_actual * gp_pct_of_equity

    tiers_result.append({
        "name": f"Preferred Return ({preferred_return}%)",
        "total": round(pref_actual),
        "lp_amount": round(pref_lp),
        "gp_amount": round(pref_gp),
        "lp_pct": round(lp_pct_of_equity * 100, 1),
        "gp_pct": round(gp_pct_of_equity * 100, 1),
        "your_amount": round(pref_actual * investor_pct) if investment_amount else None,
    })

    # Promote tiers
    sorted_tiers = sorted(promote_tiers, key=lambda t: t["threshold"])
    prev_threshold = preferred_return

    for i, tier in enumerate(sorted_tiers):
        if remaining_profit <= 0:
            break

        threshold = tier["threshold"]
        lp_split = tier["lp_split"] / 100.0
        gp_split = tier["gp_split"] / 100.0

        # Calculate how much profit falls in this tier
        if i < len(sorted_tiers) - 1:
            next_threshold = sorted_tiers[i + 1]["threshold"]
            # Profit needed to reach next threshold from current
            tier_target = total_equity * ((next_threshold - prev_threshold) / 100.0) * hold_years
            tier_profit = min(tier_target, remaining_profit)
        else:
            # Last tier gets all remaining
            tier_profit = remaining_profit

        remaining_profit -= tier_profit

        tier_lp = tier_profit * lp_split
        tier_gp = tier_profit * gp_split

        tier_name = f"Profit Split Tier {i + 1} ({tier['lp_split']}/{tier['gp_split']}"
        if i < len(sorted_tiers) - 1:
            tier_name += f" to {sorted_tiers[i + 1]['threshold']}% IRR)"
        else:
            tier_name += f" above {threshold}%)"

        tiers_result.append({
            "name": tier_name,
            "total": round(tier_profit),
            "lp_amount": round(tier_lp),
            "gp_amount": round(tier_gp),
            "lp_pct": tier["lp_split"],
            "gp_pct": tier["gp_split"],
            "your_amount": round(tier_lp * investor_pct) if investment_amount else None,
        })

        prev_threshold = threshold

    # Totals
    total_distributed = sum(t["total"] for t in tiers_result)
    lp_total = sum(t["lp_amount"] for t in tiers_result)
    gp_total = sum(t["gp_amount"] for t in tiers_result)

    totals = {
        "total_distributed": round(total_distributed),
        "lp_total": round(lp_total),
        "gp_total": round(gp_total),
        "lp_pct": round(lp_total / total_distributed * 100, 1) if total_distributed > 0 else 0,
        "gp_pct": round(gp_total / total_distributed * 100, 1) if total_distributed > 0 else 0,
    }

    if investment_amount and investment_amount > 0:
        your_total = sum(t["your_amount"] for t in tiers_result if t["your_amount"] is not None)
        your_profit = your_total - investment_amount
        your_multiple = round(your_total / investment_amount, 2) if investment_amount > 0 else 0

        # Approximate IRR
        if your_multiple > 0 and hold_years > 0:
            your_irr = round((your_multiple ** (1 / hold_years) - 1) * 100, 1)
        else:
            your_irr = 0

        # Project-level IRR estimate
        proj_multiple = round(total_distributed / total_equity, 2) if total_equity > 0 else 0
        if proj_multiple > 0 and hold_years > 0:
            proj_irr = round((proj_multiple ** (1 / hold_years) - 1) * 100, 1)
        else:
            proj_irr = 0

        fee_drag = round(proj_irr - your_irr, 1) if proj_irr > 0 else 0

        totals.update({
            "your_total": round(your_total),
            "your_profit": round(your_profit),
            "your_multiple": your_multiple,
            "your_irr_estimate": your_irr,
            "project_irr_estimate": proj_irr,
            "fee_drag_pct": max(fee_drag, 0),
        })

    return {"tiers": tiers_result, "totals": totals}


def waterfall_from_deal(metrics: dict, investment_amount: float = None) -> dict:
    """Build waterfall from deal metrics, parsing promote structure as needed."""
    ds = metrics.get("deal_structure", {}) or {}
    tr = metrics.get("target_returns", {}) or {}
    fp = metrics.get("financial_projections", {}) or {}

    total_equity = _safe_float(ds.get("total_equity_required"), 10000000)
    gp_coinvest_pct = _safe_float(ds.get("gp_equity_coinvest_pct"), 5) / 100.0
    gp_equity = total_equity * gp_coinvest_pct
    lp_equity = total_equity - gp_equity

    preferred_return = _safe_float(ds.get("preferred_return"), 8.0)
    hold_years = _safe_float(ds.get("hold_period_years") or ds.get("investment_term_years"), 5)

    # Parse promote tiers
    promote_text = tr.get("profit_split_above_pref", "") or ""
    tier2_text = tr.get("profit_split_above_tier2", "") or ""
    combined_text = f"{promote_text} {tier2_text}".strip()
    promote_tiers = parse_promote_tiers(combined_text)

    # Estimate total profit from equity multiple
    equity_multiple = _safe_float(tr.get("target_equity_multiple"), 2.0)
    total_return = total_equity * equity_multiple
    total_profit = total_return - total_equity  # Profit above return of capital

    return calculate_waterfall(
        total_equity=total_equity,
        lp_equity=lp_equity,
        gp_equity=gp_equity,
        preferred_return=preferred_return,
        promote_tiers=promote_tiers,
        hold_years=hold_years,
        total_profit=total_profit,
        investment_amount=investment_amount,
    )

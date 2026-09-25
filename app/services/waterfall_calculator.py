"""Waterfall Distribution Calculator — computes tiered LP/GP splits."""

import os
import json


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
        "your_amount": round(pref_lp * investor_pct) if investment_amount else None,
    })

    # Promote tiers
    sorted_tiers = sorted(promote_tiers, key=lambda t: t["threshold"])

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
            tier_target = total_equity * ((next_threshold - threshold) / 100.0) * hold_years
            tier_profit = min(tier_target, remaining_profit)
        else:
            # Last tier gets all remaining
            tier_profit = remaining_profit

        remaining_profit -= tier_profit

        tier_lp = tier_profit * lp_split
        tier_gp = tier_profit * gp_split

        tier_name = f"Profit Split Tier {i + 1} ({tier['lp_split']}/{tier['gp_split']}"
        if i < len(sorted_tiers) - 1:
            tier_name += f" to {sorted_tiers[i + 1]['threshold']}% simple annual hurdle)"
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
    """Use explicit structured terms; never invent or guess a sponsor waterfall."""
    import math
    from app.services.canonical_metrics import get_path, bad_source

    def unavailable(message):
        return {"status": "unavailable", "message": message, "tiers": [], "totals": {}}

    if (get_path(metrics, "deal_structure.waterfall_hurdle_basis") != "simple_annual_return"
            or get_path(metrics, "deal_structure.preferred_return_allocation") != "pro_rata"):
        return unavailable("Waterfall unavailable: the current model requires explicit simple annual hurdles and pro-rata preferred distributions. IRR hurdles, LP-only preferences and catch-up terms require a more complete model.")

    required = {
        "deal_structure.total_equity_required": (1, float("inf")),
        "deal_structure.gp_equity_coinvest_pct": (0, 100),
        "deal_structure.preferred_return": (0, 100),
        "deal_structure.hold_period_years": (0.01, 50),
        "target_returns.total_project_profit": (0, float("inf")),
    }
    values = {}
    for path, (lower, upper) in required.items():
        value = _safe_float(get_path(metrics, path), None)
        if (value is None or not math.isfinite(value) or not lower <= value <= upper
                or bad_source((metrics.get("_provenance") or {}).get(path))):
            return unavailable("Waterfall unavailable: explicit project profit, capitalization and distribution terms are required. No default splits or returns were assumed.")
        values[path] = value
    tiers = get_path(metrics, "deal_structure.promote_tiers")
    if not isinstance(tiers, list) or not tiers:
        return unavailable("Waterfall unavailable: the source terms have not been mapped to structured LP/GP tiers. Free-text terms are not reliable enough to calculate investor distributions.")
    provenance = metrics.get("_provenance") or {}
    for path in ("deal_structure.promote_tiers", "deal_structure.waterfall_hurdle_basis", "deal_structure.preferred_return_allocation"):
        if any(bad_source(entry) for key, entry in provenance.items() if key == path or key.startswith(path + ".")):
            return unavailable("Waterfall terms have an unresolved source check.")
    previous = values["deal_structure.preferred_return"]
    normalized_tiers = []
    for tier in tiers:
        if not isinstance(tier, dict):
            return unavailable("Waterfall tiers need source review.")
        numbers = [_safe_float(tier.get(key), None) for key in ("threshold", "lp_split", "gp_split")]
        if any(v is None or not math.isfinite(v) for v in numbers):
            return unavailable("Waterfall tiers need source review.")
        threshold, lp, gp = numbers
        if threshold < previous or not (0 <= lp <= 100 and 0 <= gp <= 100) or abs(lp + gp - 100) > 0.01:
            return unavailable("Waterfall tiers need source review.")
        previous = threshold
        normalized_tiers.append({"threshold": threshold, "lp_split": lp, "gp_split": gp})
    if normalized_tiers[0]["threshold"] != values["deal_structure.preferred_return"]:
        return unavailable("Waterfall tiers must explicitly cover distributions immediately above the preferred return.")
    equity = values["deal_structure.total_equity_required"]
    gp_equity = equity * values["deal_structure.gp_equity_coinvest_pct"] / 100
    if investment_amount is not None:
        investment_amount = _safe_float(investment_amount, None)
        if investment_amount is None or not math.isfinite(investment_amount) or not 0 < investment_amount <= equity - gp_equity:
            return unavailable("Investment amount must be positive and no greater than the LP equity.")
    result = calculate_waterfall(
        total_equity=equity, lp_equity=equity - gp_equity, gp_equity=gp_equity,
        preferred_return=values["deal_structure.preferred_return"], promote_tiers=normalized_tiers,
        hold_years=values["deal_structure.hold_period_years"],
        total_profit=values["target_returns.total_project_profit"],
        investment_amount=investment_amount,
    )
    result["status"] = "illustrative"
    result["message"] = "Illustrative end-of-hold allocation using simple annual hurdles and pro-rata preferred distributions. This model excludes interim timing, IRR hurdles, compounding, catch-up provisions and tax allocations."
    return result

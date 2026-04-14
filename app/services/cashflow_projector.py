"""Cash Flow Projector — generates year-by-year projections from deal metrics."""


def _safe_float(val, default=0.0):
    """Safely convert to float."""
    if val is None:
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def project_cash_flows(metrics: dict, investment_amount: float = None) -> dict:
    """
    Project cash flows for the deal and optionally for an individual LP investment.
    """
    ds = metrics.get("deal_structure", {}) or {}
    fp = metrics.get("financial_projections", {}) or {}
    tr = metrics.get("target_returns", {}) or {}
    pd = metrics.get("project_details", {}) or {}

    # Core inputs
    unit_count = _safe_float(pd.get("unit_count"), 100)
    avg_rent = _safe_float(fp.get("avg_rent_per_unit") or pd.get("current_avg_rent"), 1500)
    occupancy = _safe_float(fp.get("occupancy_assumption"), 93) / 100.0
    expense_ratio = _safe_float(fp.get("operating_expense_ratio"), 45) / 100.0
    rent_growth = _safe_float(fp.get("rent_growth_assumption"), 3.0) / 100.0

    debt_amount = _safe_float(ds.get("debt_amount"), 0)
    interest_rate = _safe_float(ds.get("interest_rate"), 5.0) / 100.0
    hold_period = int(_safe_float(ds.get("hold_period_years") or ds.get("investment_term_years"), 5))
    total_equity = _safe_float(ds.get("total_equity_required"), 0)
    preferred_return = _safe_float(ds.get("preferred_return"), 8.0) / 100.0
    exit_cap = _safe_float(fp.get("exit_cap_rate"), 5.0) / 100.0

    # Estimate annual debt service (interest-only for simplicity; common in syndications)
    annual_debt_service = debt_amount * interest_rate if debt_amount > 0 else 0

    # Project-level cash flows
    project_level = []
    current_rent = avg_rent

    for year in range(1, hold_period + 1):
        if year > 1:
            current_rent *= (1 + rent_growth)

        gross_revenue = current_rent * unit_count * 12 * occupancy
        expenses = gross_revenue * expense_ratio
        noi = gross_revenue - expenses
        cash_flow = noi - annual_debt_service

        project_level.append({
            "year": year,
            "gross_revenue": round(gross_revenue),
            "expenses": round(expenses),
            "noi": round(noi),
            "debt_service": round(annual_debt_service),
            "cash_flow": round(cash_flow),
        })

    # Exit value based on final year NOI / exit cap rate
    final_noi = project_level[-1]["noi"] if project_level else 0
    exit_value = round(final_noi / exit_cap) if exit_cap > 0 else 0
    exit_equity = exit_value - debt_amount  # Net to equity after debt payoff

    # Total cash flow to equity holders during hold
    total_operating_cf = sum(y["cash_flow"] for y in project_level)

    # LP-level projections
    lp_level = []
    summary = {}

    # LP's share of equity (assume pro-rata)
    lp_equity_share = 0.95 if total_equity > 0 else 1.0  # Default 95% LP / 5% GP

    if investment_amount and investment_amount > 0 and total_equity > 0:
        investor_pct = investment_amount / total_equity

        # Year 0: Investment
        cumulative = -investment_amount
        lp_level.append({
            "year": 0,
            "type": "investment",
            "amount": round(-investment_amount),
            "cumulative": round(cumulative),
        })

        # Annual distributions (preferred return on remaining capital)
        for year_data in project_level[:-1]:  # All years except final
            # Distribution = preferred return on invested capital (common syndication model)
            annual_dist = round(investment_amount * preferred_return)
            # Cap at available cash flow to this investor
            max_dist = round(year_data["cash_flow"] * investor_pct * lp_equity_share)
            annual_dist = min(annual_dist, max(max_dist, 0))

            cumulative += annual_dist
            lp_level.append({
                "year": year_data["year"],
                "type": "distribution",
                "amount": round(annual_dist),
                "cumulative": round(cumulative),
            })

        # Final year: distribution + exit proceeds
        last_year = project_level[-1] if project_level else {"year": hold_period, "cash_flow": 0}
        annual_dist = round(investment_amount * preferred_return)
        max_dist = round(last_year["cash_flow"] * investor_pct * lp_equity_share)
        annual_dist = min(annual_dist, max(max_dist, 0))

        # Exit proceeds for this investor
        exit_proceeds_investor = round(exit_equity * investor_pct * lp_equity_share)

        total_final = annual_dist + exit_proceeds_investor
        cumulative += total_final

        lp_level.append({
            "year": last_year["year"],
            "type": "exit",
            "amount": round(total_final),
            "cumulative": round(cumulative),
        })

        total_distributions = sum(e["amount"] for e in lp_level if e["type"] == "distribution")
        total_returned = total_distributions + total_final

        # Find payback year
        payback_year = None
        for entry in lp_level:
            if entry["cumulative"] >= 0 and entry["year"] > 0:
                payback_year = entry["year"]
                break

        # Simple IRR estimate
        net_profit = cumulative
        equity_multiple = round(total_returned / investment_amount, 2) if investment_amount > 0 else 0

        # Approximate IRR using equity multiple and hold period
        if equity_multiple > 0 and hold_period > 0:
            irr_estimate = round((equity_multiple ** (1 / hold_period) - 1) * 100, 1)
        else:
            irr_estimate = 0

        summary = {
            "total_distributions": round(total_distributions),
            "exit_proceeds": round(exit_proceeds_investor),
            "total_returned": round(total_returned),
            "net_profit": round(net_profit),
            "irr_estimate": irr_estimate,
            "equity_multiple": equity_multiple,
            "payback_year": payback_year,
            "years_modeled": hold_period,
        }
    else:
        # Project-level summary only
        equity_multiple_proj = 0
        if total_equity > 0:
            total_return_proj = total_operating_cf + exit_equity
            equity_multiple_proj = round(total_return_proj / total_equity, 2)

        summary = {
            "total_operating_cashflow": round(total_operating_cf),
            "exit_value": exit_value,
            "exit_equity": round(exit_equity),
            "total_return_to_equity": round(total_operating_cf + exit_equity),
            "equity_multiple": equity_multiple_proj,
            "years_modeled": hold_period,
        }

    return {
        "project_level": project_level,
        "lp_level": lp_level,
        "summary": summary,
        "assumptions": {
            "unit_count": int(unit_count),
            "avg_rent": round(avg_rent),
            "occupancy": round(occupancy * 100, 1),
            "expense_ratio": round(expense_ratio * 100, 1),
            "rent_growth": round(rent_growth * 100, 1),
            "interest_rate": round(interest_rate * 100, 2),
            "exit_cap_rate": round(exit_cap * 100, 2),
            "hold_period": hold_period,
        },
    }

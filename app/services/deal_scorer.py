"""Score a deal based on extracted metrics. Returns category scores and overall weighted score."""


def _safe_get(metrics: dict, *keys, default=None):
    """Safely navigate nested dict."""
    current = metrics
    for key in keys:
        if isinstance(current, dict):
            current = current.get(key, default)
        else:
            return default
    return current


def _score_range(value, ranges: list[tuple]) -> int:
    """Score a value based on ranges. ranges = [(threshold, score), ...] sorted desc."""
    if value is None:
        return 5  # neutral if unknown
    for threshold, score in ranges:
        if value >= threshold:
            return score
    return ranges[-1][1] if ranges else 5


def score_returns(metrics: dict) -> tuple[int, str]:
    """Score based on IRR, equity multiple, cash-on-cash. Weight: 20%"""
    # Prefer net returns over gross
    net_irr = _safe_get(metrics, "target_returns", "net_irr")
    gross_irr = _safe_get(metrics, "target_returns", "gross_irr")
    irr = net_irr or _safe_get(metrics, "target_returns", "target_irr")

    net_em = _safe_get(metrics, "target_returns", "net_equity_multiple")
    em = net_em or _safe_get(metrics, "target_returns", "target_equity_multiple")
    coc = _safe_get(metrics, "target_returns", "target_cash_on_cash")
    dist_yield = _safe_get(metrics, "target_returns", "distribution_yield")

    irr_score = _score_range(irr, [(20, 10), (18, 9), (16, 8), (15, 7), (13, 6), (12, 5), (10, 4), (8, 3)])
    em_score = _score_range(em, [(2.5, 10), (2.2, 9), (2.0, 8), (1.8, 7), (1.6, 6), (1.5, 5), (1.3, 4)])
    coc_score = _score_range(coc, [(12, 10), (10, 9), (8, 7), (6, 5), (4, 3)])

    scores = [s for s in [irr_score, em_score, coc_score] if s is not None]
    avg = round(sum(scores) / len(scores)) if scores else 5

    notes = []
    if irr:
        label = "Net IRR" if net_irr else "IRR"
        notes.append(f"{label} {irr}% → {irr_score}/10")
    if gross_irr and net_irr:
        fee_drag = gross_irr - net_irr
        notes.append(f"Fee drag: {fee_drag:.1f}%")
    if em:
        label = "Net Equity Multiple" if net_em else "Equity Multiple"
        notes.append(f"{label} {em}x → {em_score}/10")
    if coc:
        notes.append(f"Cash-on-Cash {coc}% → {coc_score}/10")
    if dist_yield:
        notes.append(f"Distribution yield {dist_yield}%")
    if not notes:
        notes.append("No return metrics found — scored neutral")

    return avg, "; ".join(notes)


def score_market(metrics: dict) -> tuple[int, str]:
    """Score market quality. Weight: 15%"""
    rent_growth = _safe_get(metrics, "market_location", "market_rent_growth")
    job_growth = _safe_get(metrics, "market_location", "market_job_growth")
    vacancy = _safe_get(metrics, "market_location", "market_vacancy_rate")
    walk = _safe_get(metrics, "market_location", "walk_score")

    scores = []
    notes = []

    if rent_growth is not None:
        s = _score_range(rent_growth, [(5, 10), (4, 9), (3, 7), (2, 5), (1, 3)])
        scores.append(s)
        notes.append(f"Rent growth {rent_growth}% → {s}/10")

    if job_growth is not None:
        s = _score_range(job_growth, [(4, 10), (3, 8), (2, 6), (1, 4), (0, 2)])
        scores.append(s)
        notes.append(f"Job growth {job_growth}% → {s}/10")

    if vacancy is not None:
        s = _score_range(100 - vacancy, [(97, 10), (95, 8), (93, 6), (90, 4)])
        scores.append(s)
        notes.append(f"Vacancy {vacancy}% → {s}/10")

    if walk is not None:
        s = _score_range(walk, [(90, 10), (70, 8), (50, 6), (30, 4)])
        scores.append(s)
        notes.append(f"Walk score {walk} → {s}/10")

    avg = round(sum(scores) / len(scores)) if scores else 5
    if not notes:
        notes.append("Limited market data — scored neutral")
    return avg, "; ".join(notes)


def score_structure(metrics: dict) -> tuple[int, str]:
    """Score deal structure (fees, waterfall, alignment). Weight: 15%"""
    pref = _safe_get(metrics, "deal_structure", "preferred_return")
    asset_mgmt = _safe_get(metrics, "deal_structure", "fees_asset_mgmt")
    acq_fee = _safe_get(metrics, "deal_structure", "fees_acquisition")
    gp_coinvest_pct = _safe_get(metrics, "deal_structure", "gp_equity_coinvest_pct")
    gp_co = _safe_get(metrics, "deal_structure", "gp_coinvest")
    total_fee_drag = _safe_get(metrics, "target_returns", "total_fee_drag")

    scores = []
    notes = []

    if pref is not None:
        s = _score_range(pref, [(10, 10), (8, 8), (7, 6), (6, 4), (0, 2)])
        scores.append(s)
        notes.append(f"Pref return {pref}% → {s}/10")

    if asset_mgmt is not None:
        if asset_mgmt <= 1.0:
            s = 9
        elif asset_mgmt <= 1.5:
            s = 7
        elif asset_mgmt <= 2.0:
            s = 5
        else:
            s = 3
        scores.append(s)
        notes.append(f"Asset mgmt fee {asset_mgmt}% → {s}/10")

    if acq_fee is not None:
        if acq_fee <= 1.0:
            s = 9
        elif acq_fee <= 2.0:
            s = 7
        elif acq_fee <= 3.0:
            s = 5
        else:
            s = 3
        scores.append(s)
        notes.append(f"Acquisition fee {acq_fee}% → {s}/10")

    # GP co-invest scoring (prefer gp_equity_coinvest_pct)
    gp_val = gp_coinvest_pct
    if gp_val is None and gp_co is not None:
        try:
            gp_val = float(str(gp_co).replace("%", "").replace("$", "").replace(",", ""))
        except (ValueError, TypeError):
            gp_val = None

    gp_is_rollover = _safe_get(metrics, "deal_structure", "gp_coinvest_is_rollover")
    gp_cash = _safe_get(metrics, "deal_structure", "gp_cash_at_risk")
    total_equity = _safe_get(metrics, "deal_structure", "total_equity_required")

    if gp_val is not None:
        if gp_is_rollover is True:
            # Rolled equity — score based on actual GP cash at risk if known
            if gp_cash and total_equity and total_equity > 0:
                real_pct = gp_cash / total_equity * 100
                if real_pct >= 5:
                    s = 7
                elif real_pct >= 2:
                    s = 5
                else:
                    s = 3
                notes.append(f"GP co-invest {gp_val}% (rolled equity) but ${gp_cash:,.0f} actual cash ({real_pct:.1f}%) → {s}/10")
            else:
                s = 4
                notes.append(f"GP co-invest {gp_val}% (rolled equity, not new GP cash) → {s}/10")
        elif gp_val > 20 and gp_is_rollover is None:
            # Suspiciously high, unconfirmed — moderate score
            s = 6
            notes.append(f"GP co-invest {gp_val}% (unconfirmed source — may be rolled equity) → {s}/10")
        elif gp_val >= 10:
            s = 10
        elif gp_val >= 5:
            s = 8
        elif gp_val >= 2:
            s = 6
        else:
            s = 4
        if gp_is_rollover is not True and not (gp_val > 20 and gp_is_rollover is None):
            notes.append(f"GP co-invest {gp_val}% → {s}/10")
        scores.append(s)

    if total_fee_drag is not None:
        if total_fee_drag <= 5:
            s = 10
        elif total_fee_drag <= 8:
            s = 7
        elif total_fee_drag <= 12:
            s = 5
        else:
            s = 3
        scores.append(s)
        notes.append(f"Total fee drag {total_fee_drag}% → {s}/10")

    avg = round(sum(scores) / len(scores)) if scores else 5
    if not notes:
        notes.append("Limited structure data — scored neutral")
    return avg, "; ".join(notes)


def score_risk(metrics: dict) -> tuple[int, str]:
    """Score risk factors. Weight: 15%"""
    ltv = _safe_get(metrics, "deal_structure", "ltv")
    entitlement = _safe_get(metrics, "project_details", "entitlement_status")

    # Also check AI-provided risk scores
    ai_risk = _safe_get(metrics, "risk_assessment", "overall_risk_score")

    scores = []
    notes = []

    if ltv is not None:
        if ltv <= 55:
            s = 10
        elif ltv <= 60:
            s = 8
        elif ltv <= 65:
            s = 7
        elif ltv <= 70:
            s = 5
        elif ltv <= 75:
            s = 4
        else:
            s = 2
        scores.append(s)
        notes.append(f"LTV {ltv}% → {s}/10")

    if entitlement:
        ent_str = str(entitlement).lower()
        if "entitled" in ent_str and "not" not in ent_str:
            s = 9
        elif "in-process" in ent_str or "in process" in ent_str:
            s = 5
        else:
            s = 3
        scores.append(s)
        notes.append(f"Entitlements: {entitlement} → {s}/10")

    if ai_risk is not None:
        try:
            scores.append(int(ai_risk))
            notes.append(f"AI risk assessment → {ai_risk}/10")
        except (ValueError, TypeError):
            pass

    avg = round(sum(scores) / len(scores)) if scores else 5
    if not notes:
        notes.append("Limited risk data — scored neutral")
    return avg, "; ".join(notes)


def score_financials(metrics: dict) -> tuple[int, str]:
    """Score financial assumptions. Weight: 15%"""
    entry_cap = _safe_get(metrics, "financial_projections", "entry_cap_rate")
    exit_cap = _safe_get(metrics, "financial_projections", "exit_cap_rate")
    occupancy = _safe_get(metrics, "financial_projections", "occupancy_assumption")
    rent_growth = _safe_get(metrics, "financial_projections", "rent_growth_assumption")
    expense_ratio = _safe_get(metrics, "financial_projections", "operating_expense_ratio")

    scores = []
    notes = []

    # Cap rate spread (exit > entry is conservative = good)
    if entry_cap is not None and exit_cap is not None:
        spread = exit_cap - entry_cap
        if spread >= 0.5:
            s = 9
        elif spread >= 0:
            s = 7
        elif spread >= -0.25:
            s = 5
        else:
            s = 3
        scores.append(s)
        notes.append(f"Cap rate spread {spread:+.1f}% → {s}/10")

    if occupancy is not None:
        if occupancy <= 92:
            s = 9  # Conservative
        elif occupancy <= 94:
            s = 7
        elif occupancy <= 96:
            s = 5
        else:
            s = 3  # Aggressive
        scores.append(s)
        notes.append(f"Occupancy assumption {occupancy}% → {s}/10")

    if rent_growth is not None:
        if rent_growth <= 2:
            s = 9
        elif rent_growth <= 3:
            s = 7
        elif rent_growth <= 4:
            s = 5
        else:
            s = 3
        scores.append(s)
        notes.append(f"Rent growth assumption {rent_growth}% → {s}/10")

    if expense_ratio is not None:
        if 40 <= expense_ratio <= 55:
            s = 8
        elif 35 <= expense_ratio < 40:
            s = 5  # Might be understating expenses
        elif expense_ratio < 35:
            s = 3  # Suspiciously low
        else:
            s = 6
        scores.append(s)
        notes.append(f"Expense ratio {expense_ratio}% → {s}/10")

    avg = round(sum(scores) / len(scores)) if scores else 5
    if not notes:
        notes.append("Limited financial data — scored neutral")
    return avg, "; ".join(notes)


def score_underwriting(metrics: dict) -> tuple[int, str]:
    """Score underwriting quality (Burke's metrics). Weight: 10%"""
    beo = _safe_get(metrics, "underwriting_checks", "break_even_occupancy")
    dscr = _safe_get(metrics, "underwriting_checks", "dscr")
    yoc = _safe_get(metrics, "underwriting_checks", "yield_on_cost")
    entry_cap = _safe_get(metrics, "financial_projections", "entry_cap_rate")

    scores = []
    notes = []

    if beo is not None:
        if beo <= 75:
            s = 10
        elif beo <= 80:
            s = 8
        elif beo <= 85:
            s = 6
        elif beo <= 90:
            s = 4
        else:
            s = 2
        scores.append(s)
        notes.append(f"Break-even occupancy {beo}% → {s}/10")

    if dscr is not None:
        if dscr >= 1.5:
            s = 10
        elif dscr >= 1.4:
            s = 8
        elif dscr >= 1.25:
            s = 6
        elif dscr >= 1.1:
            s = 4
        else:
            s = 2
        scores.append(s)
        notes.append(f"DSCR {dscr}x → {s}/10")

    if yoc is not None and entry_cap is not None:
        spread = yoc - entry_cap
        if spread >= 1.5:
            s = 10
        elif spread >= 1.0:
            s = 8
        elif spread >= 0.5:
            s = 6
        elif spread >= 0:
            s = 4
        else:
            s = 2
        scores.append(s)
        notes.append(f"Yield on cost {yoc}% vs entry cap {entry_cap}% → {s}/10")

    avg = round(sum(scores) / len(scores)) if scores else 5
    if not notes:
        notes.append("Limited underwriting data — scored neutral")
    return avg, "; ".join(notes)


def score_sponsor(metrics: dict) -> tuple[int, str]:
    """Score sponsor quality (Burke's sponsor evaluation). Weight: 10%"""
    full_cycle = _safe_get(metrics, "sponsor_evaluation", "sponsor_full_cycle_deals")
    alignment = _safe_get(metrics, "sponsor_evaluation", "alignment_score")
    gp_coinvest = _safe_get(metrics, "deal_structure", "gp_equity_coinvest_pct")

    scores = []
    notes = []

    if full_cycle is not None:
        try:
            fc = int(full_cycle)
            if fc >= 10:
                s = 10
            elif fc >= 5:
                s = 8
            elif fc >= 3:
                s = 6
            elif fc >= 1:
                s = 4
            else:
                s = 2
            scores.append(s)
            notes.append(f"Full-cycle deals: {fc} → {s}/10")
        except (ValueError, TypeError):
            pass

    if alignment is not None:
        try:
            a = int(alignment)
            scores.append(a)
            notes.append(f"Alignment score: {a}/10")
        except (ValueError, TypeError):
            pass

    gp_is_rollover = _safe_get(metrics, "deal_structure", "gp_coinvest_is_rollover")

    if gp_coinvest is not None:
        if gp_is_rollover is True:
            s = 3
            notes.append(f"GP co-invest {gp_coinvest}% (rolled equity, not new GP cash) → {s}/10")
        elif gp_coinvest >= 10:
            s = 10
        elif gp_coinvest >= 5:
            s = 8
        elif gp_coinvest >= 2:
            s = 5
        else:
            s = 3
        if gp_is_rollover is not True:
            notes.append(f"GP co-invest {gp_coinvest}% → {s}/10")
        scores.append(s)

    avg = round(sum(scores) / len(scores)) if scores else 5
    if not notes:
        notes.append("Limited sponsor data — scored neutral")
    return avg, "; ".join(notes)


def score_deal(metrics: dict) -> dict:
    """Score a deal across all categories. Returns scores dict."""
    returns_score, returns_notes = score_returns(metrics)
    market_score, market_notes = score_market(metrics)
    structure_score, structure_notes = score_structure(metrics)
    risk_score, risk_notes = score_risk(metrics)
    financials_score, financials_notes = score_financials(metrics)
    underwriting_score, underwriting_notes = score_underwriting(metrics)
    sponsor_score, sponsor_notes = score_sponsor(metrics)

    # Weighted average (weights sum to 100)
    overall = round(
        returns_score * 0.20
        + market_score * 0.15
        + structure_score * 0.15
        + risk_score * 0.15
        + financials_score * 0.15
        + underwriting_score * 0.10
        + sponsor_score * 0.10,
        1
    )

    return {
        "overall": overall,
        "returns": {"score": returns_score, "weight": 20, "notes": returns_notes},
        "market": {"score": market_score, "weight": 15, "notes": market_notes},
        "structure": {"score": structure_score, "weight": 15, "notes": structure_notes},
        "risk": {"score": risk_score, "weight": 15, "notes": risk_notes},
        "financials": {"score": financials_score, "weight": 15, "notes": financials_notes},
        "underwriting": {"score": underwriting_score, "weight": 10, "notes": underwriting_notes},
        "sponsor": {"score": sponsor_score, "weight": 10, "notes": sponsor_notes},
    }

"""Burke-inspired deal validation checks for LP due diligence."""


def validate_deal_metrics(metrics: dict) -> list[dict]:
    """
    Run Burke-inspired validation checks on extracted metrics.
    Returns list of {severity: 'red'|'yellow'|'green', category: str, message: str}
    """
    flags = []

    ds = metrics.get('deal_structure', {}) or {}
    tr = metrics.get('target_returns', {}) or {}
    pd = metrics.get('project_details', {}) or {}
    fp = metrics.get('financial_projections', {}) or {}
    uc = metrics.get('underwriting_checks', {}) or {}
    se = metrics.get('sponsor_evaluation', {}) or {}

    # === RETURNS CHECKS ===
    gross_irr = _num(tr.get('gross_irr'))
    net_irr = _num(tr.get('net_irr'))
    target_irr = _num(tr.get('target_irr'))
    if gross_irr and net_irr:
        fee_drag = gross_irr - net_irr
        if fee_drag > 5:
            flags.append({'severity': 'red', 'category': 'Returns',
                          'message': f'Fee drag is {fee_drag:.1f}% (gross {gross_irr}% vs net {net_irr}%). Sponsor fees are eating too much.'})
    if target_irr and not net_irr:
        flags.append({'severity': 'yellow', 'category': 'Returns',
                      'message': 'Cannot determine if quoted IRR is gross or net. Always ask for NET (to investor) returns.'})

    # IRR reasonableness
    irr = net_irr or target_irr
    if irr and irr > 25:
        flags.append({'severity': 'yellow', 'category': 'Returns',
                      'message': f'Target IRR of {irr}% is very aggressive. Few deals actually achieve >25%.'})

    # Equity multiple check
    em = _num(tr.get('net_equity_multiple') or tr.get('target_equity_multiple'))
    hold = _num(ds.get('hold_period_years'))
    if em and hold and hold > 0:
        implied_annual = ((em - 1) / hold) * 100
        if irr and abs(implied_annual - irr) > 5:
            flags.append({'severity': 'yellow', 'category': 'Returns',
                          'message': f'Equity multiple implies ~{implied_annual:.1f}% annual return but IRR shows {irr}%. Numbers may be inconsistent.'})

    # Preferred return check
    pref = _num(ds.get('preferred_return'))
    if pref and pref < 6:
        flags.append({'severity': 'yellow', 'category': 'Structure',
                      'message': f'Preferred return of {pref}% is below market standard (7-8%). LP protection is weak.'})
    elif pref and pref > 10:
        flags.append({'severity': 'yellow', 'category': 'Structure',
                      'message': f'Preferred return of {pref}% is unusually high. Verify it is actually achievable.'})

    # === STRUCTURE CHECKS ===
    gp_coinvest = _num(ds.get('gp_equity_coinvest_pct'))
    if gp_coinvest is not None and gp_coinvest < 5:
        flags.append({'severity': 'red', 'category': 'Alignment',
                      'message': f'GP co-invest is only {gp_coinvest}%. Strong sponsors invest 5-10%+ alongside LPs.'})
    elif gp_coinvest and gp_coinvest >= 10:
        flags.append({'severity': 'green', 'category': 'Alignment',
                      'message': f'GP co-invest of {gp_coinvest}% shows strong alignment. Sponsor has skin in the game.'})

    # Fee analysis
    acq_fee = _num(ds.get('fees_acquisition'))
    am_fee = _num(ds.get('fees_asset_mgmt'))
    if acq_fee and acq_fee > 3:
        flags.append({'severity': 'red', 'category': 'Fees',
                      'message': f'Acquisition fee of {acq_fee}% is above market (1-2% typical).'})
    if am_fee and am_fee > 2:
        flags.append({'severity': 'yellow', 'category': 'Fees',
                      'message': f'Asset management fee of {am_fee}% is above market (1-1.5% typical).'})

    # LTV check
    ltv = _num(ds.get('ltv'))
    if ltv and ltv > 75:
        flags.append({'severity': 'red', 'category': 'Leverage',
                      'message': f'LTV of {ltv}% is high. Increases risk significantly. Prefer <70%.'})
    elif ltv and ltv > 65:
        flags.append({'severity': 'yellow', 'category': 'Leverage',
                      'message': f'LTV of {ltv}% is moderate. Not alarming but watch debt service.'})

    # === UNDERWRITING CHECKS ===
    beo = _num(uc.get('break_even_occupancy'))
    if beo and beo > 85:
        flags.append({'severity': 'red', 'category': 'Underwriting',
                      'message': f'Break-even occupancy of {beo}% is dangerously tight. One bad quarter could mean cash calls.'})
    elif beo and beo > 80:
        flags.append({'severity': 'yellow', 'category': 'Underwriting',
                      'message': f'Break-even occupancy of {beo}% is acceptable but leaves thin margin.'})
    elif beo and beo <= 75:
        flags.append({'severity': 'green', 'category': 'Underwriting',
                      'message': f'Break-even occupancy of {beo}% provides good downside protection.'})

    # DSCR
    dscr = _num(uc.get('dscr'))
    if dscr and dscr < 1.2:
        flags.append({'severity': 'red', 'category': 'Underwriting',
                      'message': f'DSCR of {dscr}x is too thin. Minimum should be 1.25x.'})
    elif dscr and dscr < 1.35:
        flags.append({'severity': 'yellow', 'category': 'Underwriting',
                      'message': f'DSCR of {dscr}x is adequate but not comfortable. Prefer >1.4x.'})
    elif dscr and dscr >= 1.5:
        flags.append({'severity': 'green', 'category': 'Underwriting',
                      'message': f'DSCR of {dscr}x is strong. Good debt service coverage.'})

    # Rent growth assumption
    rg = _num(fp.get('rent_growth_assumption'))
    mrg = _num(metrics.get('market_location', {}).get('market_rent_growth'))
    if rg and rg > 4:
        flags.append({'severity': 'red', 'category': 'Underwriting',
                      'message': f'Rent growth assumption of {rg}% is aggressive. Historical averages are 2-3%.'})
    if rg and mrg and rg > mrg + 2:
        flags.append({'severity': 'red', 'category': 'Underwriting',
                      'message': f'Rent growth assumption ({rg}%) exceeds market growth ({mrg}%) by >{rg - mrg:.1f}%. Sponsor may be overly optimistic.'})

    # Cap rate spread
    entry_cap = _num(fp.get('entry_cap_rate'))
    exit_cap = _num(fp.get('exit_cap_rate'))
    if entry_cap and exit_cap:
        spread = exit_cap - entry_cap
        if spread < 0:
            flags.append({'severity': 'red', 'category': 'Underwriting',
                          'message': f'Exit cap ({exit_cap}%) is BELOW entry cap ({entry_cap}%). Sponsor assumes cap rate compression — very risky.'})
        elif spread < 0.25:
            flags.append({'severity': 'yellow', 'category': 'Underwriting',
                          'message': f'Exit cap ({exit_cap}%) is only {spread * 100:.0f}bps above entry ({entry_cap}%). Conservative sponsors add 50-100bps.'})
        elif spread >= 0.5:
            flags.append({'severity': 'green', 'category': 'Underwriting',
                          'message': f'Exit cap ({exit_cap}%) is {spread * 100:.0f}bps above entry ({entry_cap}%). Conservative underwriting.'})

    # Expense ratio
    exp_ratio = _num(fp.get('operating_expense_ratio'))
    if exp_ratio and exp_ratio < 35:
        flags.append({'severity': 'yellow', 'category': 'Underwriting',
                      'message': f'Expense ratio of {exp_ratio}% seems low. Typical multifamily is 40-50%. Expenses may be understated.'})

    # Occupancy assumption
    occ = _num(fp.get('occupancy_assumption'))
    if occ and occ > 97:
        flags.append({'severity': 'red', 'category': 'Underwriting',
                      'message': f'Occupancy assumption of {occ}% is unrealistic. 93-95% is more achievable.'})
    elif occ and occ > 95:
        flags.append({'severity': 'yellow', 'category': 'Underwriting',
                      'message': f'Occupancy assumption of {occ}% is optimistic. Budget for some vacancy.'})

    # Yield on cost
    yoc = _num(uc.get('yield_on_cost'))
    if yoc and entry_cap:
        if yoc <= entry_cap:
            flags.append({'severity': 'red', 'category': 'Underwriting',
                          'message': f'Yield on cost ({yoc}%) does not exceed entry cap rate ({entry_cap}%). No value creation.'})
        elif yoc > entry_cap + 1.5:
            flags.append({'severity': 'green', 'category': 'Underwriting',
                          'message': f'Yield on cost ({yoc}%) exceeds entry cap ({entry_cap}%) by {yoc - entry_cap:.1f}%. Strong value creation.'})

    # Interest rate sensitivity
    irs = uc.get('interest_rate_sensitivity')
    if irs and isinstance(irs, str) and 'negative' in irs.lower():
        flags.append({'severity': 'yellow', 'category': 'Underwriting',
                      'message': 'Interest rate sensitivity shows negative returns under stress. Review floating rate risk.'})

    # === SPONSOR CHECKS ===
    full_cycle = _num(se.get('sponsor_full_cycle_deals'))
    if full_cycle is not None and full_cycle < 3:
        flags.append({'severity': 'red', 'category': 'Sponsor',
                      'message': f'Sponsor has only {int(full_cycle)} full-cycle deals. Look for sponsors with 5+ completed deals.'})
    elif full_cycle and full_cycle >= 5:
        flags.append({'severity': 'green', 'category': 'Sponsor',
                      'message': f'Sponsor has {int(full_cycle)} full-cycle deals. Good experience.'})

    default_hist = se.get('sponsor_default_history')
    if default_hist and isinstance(default_hist, str) and default_hist.lower() not in ('none', 'no', 'null', 'n/a', ''):
        flags.append({'severity': 'red', 'category': 'Sponsor',
                      'message': f'Sponsor has default/loss history: {default_hist}'})

    alignment = _num(se.get('alignment_score'))
    if alignment and alignment <= 4:
        flags.append({'severity': 'red', 'category': 'Alignment',
                      'message': f'Alignment score is {alignment}/10. Fee structure and co-invest suggest poor LP alignment.'})
    elif alignment and alignment >= 8:
        flags.append({'severity': 'green', 'category': 'Alignment',
                      'message': f'Alignment score is {alignment}/10. Strong sponsor-LP alignment.'})

    # Distribution yield check
    dist_yield = _num(tr.get('distribution_yield'))
    if dist_yield and dist_yield > 0 and pref:
        if dist_yield < pref:
            flags.append({'severity': 'yellow', 'category': 'Returns',
                          'message': f'Distribution yield ({dist_yield}%) is below preferred return ({pref}%). Distributions may accrue rather than pay current.'})

    # Total fee drag
    total_fee = _num(tr.get('total_fee_drag'))
    if total_fee and total_fee > 15:
        flags.append({'severity': 'red', 'category': 'Fees',
                      'message': f'Total fee drag is {total_fee}% of equity. That is very high — industry standard is 5-10%.'})
    elif total_fee and total_fee > 10:
        flags.append({'severity': 'yellow', 'category': 'Fees',
                      'message': f'Total fee drag is {total_fee}% of equity. Above average but may be acceptable for complex deals.'})

    return flags


def _num(val):
    """Safely convert to float."""
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None

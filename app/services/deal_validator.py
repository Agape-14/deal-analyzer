"""Burke-inspired deal validation checks for LP due diligence."""


# Asset-class-aware thresholds. Stabilized income properties accept lower
# IRR and higher occupancy; development/value-add deals justifiably show
# higher IRR and wider underwriting bands. Defaults match stabilized
# multifamily, which was the original hardcoded baseline.
DEFAULT_PROFILE = {
    "irr_aggressive": 25,        # yellow flag above this %
    "rent_growth_red": 4,        # red flag above this %
    "opex_low": 35,              # yellow flag below this %
    "occ_red": 97,               # red flag above this %
    "occ_yellow": 95,            # yellow flag above this %
    "dscr_red": 1.2,             # red flag below this
    "dscr_green": 1.5,           # green flag at/above this
    "ltv_red": 75,               # red flag above this %
    "ltv_yellow": 65,            # yellow flag above this %
    "beo_red": 85,               # red flag above this %
    "beo_yellow": 80,            # yellow flag above this %
}

ASSET_CLASS_PROFILES: dict[str, dict] = {
    # Stabilized income, relatively tight band
    "multifamily":  {**DEFAULT_PROFILE},
    "office":       {**DEFAULT_PROFILE, "opex_low": 30, "occ_red": 93, "occ_yellow": 88, "dscr_green": 1.4},
    "retail":       {**DEFAULT_PROFILE, "opex_low": 25, "occ_red": 95, "occ_yellow": 92},
    "industrial":   {**DEFAULT_PROFILE, "opex_low": 20, "occ_red": 98, "occ_yellow": 95},
    "hospitality":  {**DEFAULT_PROFILE, "irr_aggressive": 30, "occ_red": 85, "occ_yellow": 80},
    # Higher risk / reward
    "development":  {**DEFAULT_PROFILE, "irr_aggressive": 35, "ltv_yellow": 70, "ltv_red": 80, "beo_yellow": 82, "beo_red": 88},
    "land":         {**DEFAULT_PROFILE, "irr_aggressive": 40, "dscr_red": 1.0, "dscr_green": 1.3},
    "mixed-use":    {**DEFAULT_PROFILE, "irr_aggressive": 28, "opex_low": 30},
    "other":        {**DEFAULT_PROFILE},
}


def _profile_for(property_type: str | None) -> dict:
    key = (property_type or "").strip().lower()
    return ASSET_CLASS_PROFILES.get(key, DEFAULT_PROFILE)


def validate_deal_metrics(metrics: dict, property_type: str | None = None) -> list[dict]:
    """
    Run Burke-inspired validation checks on extracted metrics.
    Returns list of {severity: 'red'|'yellow'|'green', category: str, message: str}

    ``property_type`` adjusts the thresholds that vary by asset class
    (IRR aggressive cutoff, expense ratio floor, occupancy cap, DSCR band,
    LTV band, BEO band). When not provided, defaults to stabilized
    multifamily — which matches the original hardcoded behavior.
    """
    flags = []
    profile = _profile_for(property_type)

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

    # Fee drag only makes sense when gross and net are computed on the
    # SAME scenario (e.g. both sale-scenario IRRs, or both hold-
    # scenario cash-on-cash). OMs commonly quote "Gross IRR 21%"
    # (hypothetical sale) alongside "Net cash-on-cash 12%" (hold),
    # and blindly subtracting them produces a nonsense "fee drag"
    # number that accuses the sponsor of eating returns. Only emit
    # the flag when we can prove we're comparing like-for-like:
    #
    # 1. primary_strategy is "sale" (both IRRs are sale-scenario), or
    # 2. sale_scenario has its own gross/net pair, or
    # 3. hold_scenario has its own gross/net pair.
    primary_strategy = (tr.get('primary_strategy') or '').lower()
    sale_scenario = tr.get('sale_scenario') or {}
    hold_scenario = tr.get('hold_scenario') or {}

    scenario_gross = None
    scenario_net = None
    scenario_label = None
    if primary_strategy == 'sale' and gross_irr and net_irr:
        scenario_gross, scenario_net, scenario_label = gross_irr, net_irr, 'sale IRR'
    else:
        s_gross = _num(sale_scenario.get('sale_gross_irr'))
        s_net = _num(sale_scenario.get('sale_irr'))
        if s_gross and s_net:
            scenario_gross, scenario_net, scenario_label = s_gross, s_net, 'sale IRR'
        else:
            h_gross = _num(hold_scenario.get('gross_cash_on_cash'))
            h_net = _num(hold_scenario.get('cash_on_cash_return'))
            if h_gross and h_net:
                scenario_gross, scenario_net, scenario_label = h_gross, h_net, 'hold cash-on-cash'

    if scenario_gross and scenario_net:
        fee_drag = scenario_gross - scenario_net
        if fee_drag > 5:
            flags.append({'severity': 'red', 'category': 'Returns',
                          'message': f'Fee drag is {fee_drag:.1f}% ({scenario_label}: gross {scenario_gross}% vs net {scenario_net}%). Sponsor fees are eating too much.'})
    elif gross_irr and net_irr:
        # We have both but can't confirm they're the same scenario.
        # Mention the spread as context, not as an accusation.
        spread = gross_irr - net_irr
        if spread > 5:
            flags.append({'severity': 'yellow', 'category': 'Returns',
                          'message': f'Gross IRR ({gross_irr}%) and Net IRR ({net_irr}%) differ by {spread:.1f}%, but they may be from different scenarios (e.g. hypothetical sale vs hold). Confirm they are apples-to-apples before calling this fee drag.'})

    if target_irr and not net_irr:
        flags.append({'severity': 'yellow', 'category': 'Returns',
                      'message': 'Cannot determine if quoted IRR is gross or net. Always ask for NET (to investor) returns.'})

    # IRR reasonableness (threshold varies by asset class)
    irr = net_irr or target_irr
    irr_cap = profile["irr_aggressive"]
    if irr and irr > irr_cap:
        flags.append({'severity': 'yellow', 'category': 'Returns',
                      'message': f'Target IRR of {irr}% is very aggressive for this asset class (typical cap {irr_cap}%).'})

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
    gp_is_rollover = ds.get('gp_coinvest_is_rollover')

    if gp_is_rollover is True:
        flags.append({'severity': 'yellow', 'category': 'Alignment',
                      'message': f'GP co-invest of {gp_coinvest or "?"}% appears to be rolled-over equity from a prior phase — not new cash from the sponsor. '
                                 'True GP alignment requires the sponsor\'s own capital at risk. Verify what portion is actual GP money.'})
    elif gp_coinvest is not None and gp_coinvest < 5:
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

    # LTV check (asset-class aware)
    ltv = _num(ds.get('ltv'))
    if ltv and ltv > profile["ltv_red"]:
        flags.append({'severity': 'red', 'category': 'Leverage',
                      'message': f'LTV of {ltv}% is high for this asset class (threshold {profile["ltv_red"]}%). Increases risk significantly.'})
    elif ltv and ltv > profile["ltv_yellow"]:
        flags.append({'severity': 'yellow', 'category': 'Leverage',
                      'message': f'LTV of {ltv}% is moderate for this asset class. Watch debt service.'})

    # === UNDERWRITING CHECKS ===
    beo = _num(uc.get('break_even_occupancy'))
    if beo and beo > profile["beo_red"]:
        flags.append({'severity': 'red', 'category': 'Underwriting',
                      'message': f'Break-even occupancy of {beo}% is dangerously tight for this asset class (threshold {profile["beo_red"]}%). One bad quarter could mean cash calls.'})
    elif beo and beo > profile["beo_yellow"]:
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
    elif dscr and dscr < profile["dscr_green"] - 0.1:
        flags.append({'severity': 'yellow', 'category': 'Underwriting',
                      'message': f'DSCR of {dscr}x is adequate but not comfortable. Prefer ≥{profile["dscr_green"]}x for this asset class.'})
    elif dscr and dscr >= profile["dscr_green"]:
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

    # Expense ratio (asset-class aware)
    exp_ratio = _num(fp.get('operating_expense_ratio'))
    if exp_ratio and exp_ratio < profile["opex_low"]:
        flags.append({'severity': 'yellow', 'category': 'Underwriting',
                      'message': f'Expense ratio of {exp_ratio}% is below the typical floor for this asset class (~{profile["opex_low"]}%). Expenses may be understated.'})

    # Occupancy assumption (asset-class aware)
    occ = _num(fp.get('occupancy_assumption'))
    if occ and occ > profile["occ_red"]:
        flags.append({'severity': 'red', 'category': 'Underwriting',
                      'message': f'Occupancy assumption of {occ}% is unrealistic for this asset class (cap {profile["occ_red"]}%).'})
    elif occ and occ > profile["occ_yellow"]:
        flags.append({'severity': 'yellow', 'category': 'Underwriting',
                      'message': f'Occupancy assumption of {occ}% is optimistic for this asset class. Budget for some vacancy.'})

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

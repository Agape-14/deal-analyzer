"""Burke-inspired deal validation checks for LP due diligence."""


from app.services.canonical_metrics import is_hold_strategy


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

BENCHMARK_RANGES: dict[str, dict[str, tuple[float, float, str]]] = {
    "multifamily": {
        "total_project_cost_per_unit": (150_000, 750_000, "$/unit"),
        "hard_costs_per_unit": (100_000, 550_000, "$/unit"),
        "land_cost_per_unit": (10_000, 180_000, "$/unit"),
        "avg_rent_per_unit": (800, 6_000, "$/mo"),
        "entry_cap_rate": (3.0, 8.5, "%"),
        "exit_cap_rate": (3.25, 9.5, "%"),
        "interest_rate": (4.0, 12.0, "%"),
    },
    "development": {
        "total_project_cost_per_unit": (200_000, 950_000, "$/unit"),
        "hard_costs_per_unit": (125_000, 700_000, "$/unit"),
        "land_cost_per_unit": (15_000, 250_000, "$/unit"),
        "avg_rent_per_unit": (900, 7_500, "$/mo"),
        "entry_cap_rate": (3.0, 8.5, "%"),
        "exit_cap_rate": (3.25, 9.5, "%"),
        "interest_rate": (4.0, 12.0, "%"),
    },
    "office": {
        "entry_cap_rate": (4.5, 11.0, "%"),
        "exit_cap_rate": (5.0, 12.0, "%"),
        "interest_rate": (4.0, 12.0, "%"),
    },
    "retail": {
        "entry_cap_rate": (4.5, 10.5, "%"),
        "exit_cap_rate": (5.0, 11.5, "%"),
        "interest_rate": (4.0, 12.0, "%"),
    },
    "industrial": {
        "entry_cap_rate": (3.5, 8.5, "%"),
        "exit_cap_rate": (4.0, 9.5, "%"),
        "interest_rate": (4.0, 12.0, "%"),
    },
    "hospitality": {
        "entry_cap_rate": (6.0, 13.0, "%"),
        "exit_cap_rate": (6.5, 14.0, "%"),
        "interest_rate": (4.0, 12.5, "%"),
    },
    "land": {
        "interest_rate": (4.0, 14.0, "%"),
    },
    "mixed-use": {
        "total_project_cost_per_unit": (175_000, 900_000, "$/unit"),
        "hard_costs_per_unit": (115_000, 650_000, "$/unit"),
        "land_cost_per_unit": (15_000, 230_000, "$/unit"),
        "avg_rent_per_unit": (850, 7_000, "$/mo"),
        "entry_cap_rate": (3.5, 9.5, "%"),
        "exit_cap_rate": (4.0, 10.5, "%"),
        "interest_rate": (4.0, 12.0, "%"),
    },
    "other": {
        "entry_cap_rate": (3.0, 12.0, "%"),
        "exit_cap_rate": (3.0, 13.0, "%"),
        "interest_rate": (4.0, 13.0, "%"),
    },
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
    multifamily - which matches the original hardcoded behavior.
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
    net_equity_multiple = _num(tr.get('net_equity_multiple'))
    target_equity_multiple = _num(tr.get('target_equity_multiple'))
    target_cash_on_cash = _num(tr.get('target_cash_on_cash'))
    distribution_yield = _num(tr.get('distribution_yield'))

    primary_strategy = (tr.get('primary_strategy') or '').lower()
    hold_strategy = is_hold_strategy(metrics)
    sale_scenario = tr.get('sale_scenario') or {}
    hold_scenario = tr.get('hold_scenario') or {}

    if not hold_strategy:
        _add_canonical_alias_flags(flags, [
            {
                "label": "Target IRR",
                "canonical_label": "Net IRR",
                "canonical_path": "target_returns.net_irr",
                "alias_path": "target_returns.target_irr",
                "canonical_value": net_irr,
                "alias_value": target_irr,
                "unit": "%",
                "tolerance": 0.25,
                "message": "Target IRR must match investor Net IRR. Cash-on-cash or distribution yield should remain separate.",
            },
            {
                "label": "Equity multiple",
                "canonical_label": "Net equity multiple",
                "canonical_path": "target_returns.net_equity_multiple",
                "alias_path": "target_returns.target_equity_multiple",
                "canonical_value": net_equity_multiple,
                "alias_value": target_equity_multiple,
                "unit": "x",
                "tolerance": 0.02,
                "message": "Target equity multiple must match investor Net Equity Multiple when both are present.",
            },
        ])
    _add_canonical_alias_flags(flags, [
        {
            "label": "Cash-on-cash",
            "canonical_label": "Distribution yield",
            "canonical_path": "target_returns.target_cash_on_cash",
            "alias_path": "target_returns.distribution_yield",
            "canonical_value": target_cash_on_cash,
            "alias_value": distribution_yield,
            "unit": "%",
            "tolerance": 0.25,
            "message": "Cash-on-cash and distribution yield are the same periodic yield concept unless the source explicitly separates scenarios.",
        },
    ])

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
        spread = gross_irr - net_irr
        if spread > 5:
            flags.append({'severity': 'yellow', 'category': 'Returns',
                          'message': f'Gross IRR ({gross_irr}%) and Net IRR ({net_irr}%) differ by {spread:.1f}%, but they may be from different scenarios (e.g. hypothetical sale vs hold). Confirm they are apples-to-apples before calling this fee drag.'})

    if target_irr and not net_irr:
        flags.append({'severity': 'yellow', 'category': 'Returns',
                      'message': 'Cannot determine if quoted IRR is gross or net. Always ask for NET (to investor) returns.'})

    irr = net_irr or target_irr
    irr_cap = profile["irr_aggressive"]
    if irr and irr > irr_cap:
        flags.append({'severity': 'yellow', 'category': 'Returns',
                      'message': f'Target IRR of {irr}% is very aggressive for this asset class (typical cap {irr_cap}%).'})

    em = net_equity_multiple or target_equity_multiple
    hold = _num(ds.get('hold_period_years'))
    if em and hold and hold > 0 and not hold_strategy:
        implied_annual = ((em - 1) / hold) * 100
        if irr and abs(implied_annual - irr) > 5:
            flags.append({'severity': 'yellow', 'category': 'Returns',
                          'message': f'Equity multiple implies ~{implied_annual:.1f}% annual return but IRR shows {irr}%. Numbers may be inconsistent.'})

    pref = _num(ds.get('preferred_return'))
    if pref and pref < 6:
        flags.append({'severity': 'yellow', 'category': 'Structure',
                      'message': f'Preferred return of {pref}% is below market standard (7-8%). LP protection is weak.'})
    elif pref and pref > 10:
        flags.append({'severity': 'yellow', 'category': 'Structure',
                      'message': f'Preferred return of {pref}% is unusually high. Verify it is actually achievable.'})

    gp_coinvest = _num(ds.get('gp_equity_coinvest_pct'))
    gp_is_rollover = ds.get('gp_coinvest_is_rollover')
    gp_cash = _num(ds.get('gp_cash_at_risk'))

    if gp_is_rollover is True:
        cash_note = f' GP cash at risk: ${gp_cash:,.0f}.' if gp_cash else ' GP actual cash at risk: unknown.'
        flags.append({'severity': 'yellow', 'category': 'Alignment',
                      'message': f'GP co-invest of {gp_coinvest or "?"}% appears to be rolled-over equity / land basis / deferred fees - not new cash from the sponsor.{cash_note} True alignment requires the sponsor\'s own capital at risk.'})
    elif gp_coinvest is not None and gp_coinvest > 20 and gp_is_rollover is None:
        flags.append({'severity': 'yellow', 'category': 'Alignment',
                      'message': f'GP co-invest of {gp_coinvest}% is unusually high. Verify this is actual GP cash - not rolled equity from a prior phase, land contribution, or deferred fees.'})
    elif gp_coinvest is not None and gp_coinvest < 5:
        flags.append({'severity': 'red', 'category': 'Alignment',
                      'message': f'GP co-invest is only {gp_coinvest}%. Strong sponsors invest 5-10%+ alongside LPs.'})
    elif gp_coinvest and gp_coinvest >= 10 and gp_is_rollover is False:
        flags.append({'severity': 'green', 'category': 'Alignment',
                      'message': f'GP co-invest of {gp_coinvest}% shows strong alignment. Sponsor has skin in the game.'})

    acq_fee = _num(ds.get('fees_acquisition'))
    am_fee = _num(ds.get('fees_asset_mgmt'))
    if acq_fee and acq_fee > 3:
        flags.append({'severity': 'red', 'category': 'Fees',
                      'message': f'Acquisition fee of {acq_fee}% is above market (1-2% typical).'})
    if am_fee and am_fee > 2:
        flags.append({'severity': 'yellow', 'category': 'Fees',
                      'message': f'Asset management fee of {am_fee}% is above market (1-1.5% typical).'})

    ltv = _num(ds.get('ltv'))
    if ltv and ltv > profile["ltv_red"]:
        flags.append({'severity': 'red', 'category': 'Leverage',
                      'message': f'LTV of {ltv}% is high for this asset class (threshold {profile["ltv_red"]}%). Increases risk significantly.'})
    elif ltv and ltv > profile["ltv_yellow"]:
        flags.append({'severity': 'yellow', 'category': 'Leverage',
                      'message': f'LTV of {ltv}% is moderate for this asset class. Watch debt service.'})

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

    dscr = _num(uc.get('dscr'))
    if dscr and dscr < 1.2:
        flags.append({'severity': 'yellow', 'category': 'Underwriting',
                      'message': f'DSCR of {dscr}x is below the usual 1.25x target. Confirm annual debt service before treating this as a hard issue.'})
    elif dscr and dscr < profile["dscr_green"] - 0.1:
        flags.append({'severity': 'yellow', 'category': 'Underwriting',
                      'message': f'DSCR of {dscr}x is adequate but not comfortable. Prefer >={profile["dscr_green"]}x for this asset class.'})
    elif dscr and dscr >= profile["dscr_green"]:
        flags.append({'severity': 'green', 'category': 'Underwriting',
                      'message': f'DSCR of {dscr}x is strong. Good debt service coverage.'})

    rg = _num(fp.get('rent_growth_assumption'))
    mrg = _num(metrics.get('market_location', {}).get('market_rent_growth'))
    if rg and rg > 4:
        flags.append({'severity': 'red', 'category': 'Underwriting',
                      'message': f'Rent growth assumption of {rg}% is aggressive. Historical averages are 2-3%.'})
    if rg and mrg and rg > mrg + 2:
        flags.append({'severity': 'red', 'category': 'Underwriting',
                      'message': f'Rent growth assumption ({rg}%) exceeds market growth ({mrg}%) by >{rg - mrg:.1f}%. Sponsor may be overly optimistic.'})

    entry_cap = _num(fp.get('entry_cap_rate'))
    exit_cap = _num(fp.get('exit_cap_rate'))
    if entry_cap and exit_cap:
        spread = exit_cap - entry_cap
        if spread < 0:
            if hold_strategy:
                flags.append({'severity': 'yellow', 'category': 'Underwriting',
                              'message': f'Optional sale scenario exit cap ({exit_cap}%) is below entry cap ({entry_cap}%). Treat sale returns as hypothetical; hold cash-flow metrics remain primary.'})
            else:
                flags.append({'severity': 'red', 'category': 'Underwriting',
                              'message': f'Exit cap ({exit_cap}%) is BELOW entry cap ({entry_cap}%). Sponsor assumes cap rate compression - very risky.'})
        elif spread < 0.25:
            flags.append({'severity': 'yellow', 'category': 'Underwriting',
                          'message': f'Exit cap ({exit_cap}%) is only {spread * 100:.0f}bps above entry ({entry_cap}%). Conservative sponsors add 50-100bps.'})
        elif spread >= 0.5:
            flags.append({'severity': 'green', 'category': 'Underwriting',
                          'message': f'Exit cap ({exit_cap}%) is {spread * 100:.0f}bps above entry ({entry_cap}%). Conservative underwriting.'})

    exp_ratio = _num(fp.get('operating_expense_ratio'))
    if exp_ratio and exp_ratio < profile["opex_low"]:
        flags.append({'severity': 'yellow', 'category': 'Underwriting',
                      'message': f'Expense ratio of {exp_ratio}% is below the typical floor for this asset class (~{profile["opex_low"]}%). Expenses may be understated.'})

    occ = _num(fp.get('occupancy_assumption'))
    if occ and occ > profile["occ_red"]:
        flags.append({'severity': 'red', 'category': 'Underwriting',
                      'message': f'Occupancy assumption of {occ}% is unrealistic for this asset class (cap {profile["occ_red"]}%).'})
    elif occ and occ > profile["occ_yellow"]:
        flags.append({'severity': 'yellow', 'category': 'Underwriting',
                      'message': f'Occupancy assumption of {occ}% is optimistic for this asset class. Budget for some vacancy.'})

    yoc = _num(uc.get('yield_on_cost'))
    if yoc and entry_cap:
        if yoc <= entry_cap:
            flags.append({'severity': 'yellow', 'category': 'Underwriting',
                          'message': f'Yield on cost ({yoc}%) does not exceed entry cap rate ({entry_cap}%). This is a value-creation caution, not a source-data failure.'})
        elif yoc > entry_cap + 1.5:
            flags.append({'severity': 'green', 'category': 'Underwriting',
                          'message': f'Yield on cost ({yoc}%) exceeds entry cap ({entry_cap}%) by {yoc - entry_cap:.1f}%. Strong value creation.'})

    irs = uc.get('interest_rate_sensitivity')
    if irs and isinstance(irs, str) and 'negative' in irs.lower():
        flags.append({'severity': 'yellow', 'category': 'Underwriting',
                      'message': 'Interest rate sensitivity shows negative returns under stress. Review floating rate risk.'})

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

    dist_yield = distribution_yield
    if dist_yield and dist_yield > 0 and pref:
        if dist_yield < pref:
            flags.append({'severity': 'yellow', 'category': 'Returns',
                          'message': f'Distribution yield ({dist_yield}%) is below preferred return ({pref}%). Distributions may accrue rather than pay current.'})

    total_fee = _num(tr.get('total_fee_drag'))
    if total_fee and total_fee > 15:
        flags.append({'severity': 'red', 'category': 'Fees',
                      'message': f'Total fee drag is {total_fee}% of equity. That is very high - industry standard is 5-10%.'})
    elif total_fee and total_fee > 10:
        flags.append({'severity': 'yellow', 'category': 'Fees',
                      'message': f'Total fee drag is {total_fee}% of equity. Above average but may be acceptable for complex deals.'})

    _add_benchmark_flags(flags, metrics, property_type)

    return flags


def _num(val):
    """Safely convert to float."""
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _add_canonical_alias_flags(flags: list[dict], rules: list[dict]) -> None:
    """Flag same-calculation fields that disagree before scoring relies on them."""
    for rule in rules:
        canonical = rule.get("canonical_value")
        alias = rule.get("alias_value")
        if canonical is None or alias is None:
            continue
        diff = abs(canonical - alias)
        tolerance = float(rule.get("tolerance") or 0)
        if diff <= tolerance:
            continue
        unit = rule.get("unit", "")
        flags.append({
            "severity": "red",
            "category": "Data integrity",
            "message": (
                f"{rule['label']} conflict: {rule['canonical_label']} "
                f"({rule['canonical_path']} = {_fmt_alias_value(canonical, unit)}) does not match "
                f"{rule['alias_path']} ({_fmt_alias_value(alias, unit)}). "
                f"{rule['message']}"
            ),
        })


def _fmt_alias_value(value: float, unit: str) -> str:
    if unit == "%":
        return f"{value:.1f}%"
    if unit == "x":
        return f"{value:.2f}x"
    return f"{value:g}{unit}"


def _add_benchmark_flags(flags: list[dict], metrics: dict, property_type: str | None) -> None:
    """Add market sanity checks for extracted values that are often misread."""
    asset_key = (property_type or "").strip().lower()
    ranges = {**BENCHMARK_RANGES["other"], **BENCHMARK_RANGES.get(asset_key, BENCHMARK_RANGES["multifamily"])}

    sections = {
        "deal_structure": metrics.get("deal_structure", {}) or {},
        "construction_costs": metrics.get("construction_costs", {}) or {},
        "financial_projections": metrics.get("financial_projections", {}) or {},
        "underwriting_checks": metrics.get("underwriting_checks", {}) or {},
    }

    checks = [
        ("construction_costs", "total_project_cost_per_unit", "Total project cost per unit"),
        ("construction_costs", "hard_costs_per_unit", "Hard cost per unit"),
        ("construction_costs", "land_cost_per_unit", "Land cost per unit"),
        ("financial_projections", "avg_rent_per_unit", "Average rent per unit"),
        ("financial_projections", "entry_cap_rate", "Entry cap rate"),
        ("financial_projections", "exit_cap_rate", "Exit cap rate"),
        ("deal_structure", "interest_rate", "Interest rate"),
    ]

    for section, key, label in checks:
        value = _num(sections.get(section, {}).get(key))
        bounds = ranges.get(key)
        if value is None or bounds is None:
            continue
        low, high, unit = bounds
        if value < low or value > high:
            flags.append({
                "severity": _benchmark_severity(value, low, high),
                "category": "Benchmark",
                "message": (
                    f"{label} of {_fmt_benchmark(value, unit)} is outside the expected "
                    f"{asset_key or 'deal'} benchmark range ({_fmt_benchmark(low, unit)}-"
                    f"{_fmt_benchmark(high, unit)}). Verify the source page and units."
                ),
            })

    cc = sections["construction_costs"]
    fp = sections["financial_projections"]
    uc = sections["underwriting_checks"]
    ds = sections["deal_structure"]

    total_cost = _num(cc.get("total_project_cost_per_unit"))
    hard_cost = _num(cc.get("hard_costs_per_unit"))
    land_cost = _num(cc.get("land_cost_per_unit"))
    if total_cost and hard_cost and hard_cost > total_cost:
        flags.append({
            "severity": "red",
            "category": "Benchmark",
            "message": (
                f"Hard cost per unit (${hard_cost:,.0f}) exceeds total project cost per unit "
                f"(${total_cost:,.0f}). This is likely a unit or extraction error."
            ),
        })
    if total_cost and land_cost and land_cost > total_cost * 0.6:
        flags.append({
            "severity": "yellow",
            "category": "Benchmark",
            "message": (
                f"Land cost per unit (${land_cost:,.0f}) is more than 60% of total project "
                f"cost per unit (${total_cost:,.0f}). Confirm land basis and total cost units."
            ),
        })

    entry_cap = _num(fp.get("entry_cap_rate"))
    yoc = _num(uc.get("yield_on_cost"))
    if entry_cap and yoc and yoc - entry_cap > 4:
        flags.append({
            "severity": "yellow",
            "category": "Benchmark",
            "message": (
                f"Yield on cost ({yoc}%) is {yoc - entry_cap:.1f}% above entry cap "
                f"({entry_cap}%). That may be possible, but should be traced to NOI and cost assumptions."
            ),
        })

    ltv = _num(ds.get("ltv"))
    dscr = _num(uc.get("dscr"))
    if ltv and dscr and ltv >= 70 and dscr < 1.35:
        flags.append({
            "severity": "red",
            "category": "Benchmark",
            "message": (
                f"LTV ({ltv}%) and DSCR ({dscr}x) are both tight. Recheck loan amount, NOI, "
                "interest rate, and amortization before relying on the score."
            ),
        })


def _benchmark_severity(value: float, low: float, high: float) -> str:
    span = max(high - low, 1)
    if value < low - span * 0.35 or value > high + span * 0.35:
        return "red"
    return "yellow"


def _fmt_benchmark(value: float, unit: str) -> str:
    if unit.startswith("$"):
        return f"${value:,.0f}{unit[1:]}"
    if unit == "%":
        return f"{value:.1f}%"
    return f"{value:g}{unit}"

"""
Deterministic Math Checker — Zero AI, pure arithmetic verification.

Independently recalculates every derived metric and cross-checks
internal consistency. Catches errors that AI verification might miss.
"""


def run_math_checks(metrics: dict) -> list[dict]:
    """
    Run deterministic math checks on all extracted metrics.
    Returns list of check results.
    
    Each result: {
        check: str,           # What was checked
        status: 'pass'|'fail'|'warn'|'info',
        expected: any,        # What math says it should be
        actual: any,          # What's in the metrics
        difference: str,      # How far off
        formula: str,         # The calculation shown
    }
    """
    results = []
    
    ds = metrics.get('deal_structure', {}) or {}
    tr = metrics.get('target_returns', {}) or {}
    pd = metrics.get('project_details', {}) or {}
    fp = metrics.get('financial_projections', {}) or {}
    uc = metrics.get('underwriting_checks', {}) or {}
    ml = metrics.get('market_location', {}) or {}
    
    # ============================================
    # 1. CAPITAL STRUCTURE CHECKS
    # ============================================
    
    total_cost = _n(ds.get('total_project_cost'))
    equity = _n(ds.get('total_equity_required'))
    debt = _n(ds.get('debt_amount'))
    construction_loan = _n(ds.get('construction_loan_amount'))
    permanent_loan = _n(ds.get('permanent_loan_amount'))
    pref_equity = _n(ds.get('preferred_equity_amount'))
    
    # Check construction vs perm loan consistency
    if construction_loan and permanent_loan:
        if construction_loan > permanent_loan:
            results.append({
                'check': 'Construction Loan ≤ Permanent Loan',
                'status': 'fail',
                'expected': f'Construction ≤ Perm',
                'actual': f'Construction ${construction_loan:,.0f} > Perm ${permanent_loan:,.0f}',
                'difference': 'Construction loan should not exceed permanent loan',
                'formula': f'${construction_loan:,.0f} vs ${permanent_loan:,.0f}',
            })
        else:
            results.append({
                'check': 'Construction Loan ≤ Permanent Loan',
                'status': 'pass',
                'expected': f'Construction ≤ Perm',
                'actual': f'${construction_loan:,.0f} → ${permanent_loan:,.0f}',
                'difference': f'Perm is ${permanent_loan - construction_loan:,.0f} higher',
                'formula': f'Construction ${construction_loan:,.0f} → Perm takeout ${permanent_loan:,.0f}',
            })
    
    # Debt used for LTV should be construction loan (current phase), not perm
    if debt and construction_loan and permanent_loan:
        if debt == permanent_loan and debt != construction_loan:
            results.append({
                'check': 'Debt Amount = Construction Loan (not Perm)',
                'status': 'warn',
                'expected': f'${construction_loan:,.0f} (construction)',
                'actual': f'${debt:,.0f} (permanent)',
                'difference': 'Using perm loan for LTV may overstate leverage during construction',
                'formula': f'debt_amount should be ${construction_loan:,.0f} during development phase',
            })
    
    # Total cost should = equity + debt + pref equity (approximately)
    if equity and debt and total_cost:
        calc_total = equity + debt + (pref_equity or 0)
        diff_pct = abs(calc_total - total_cost) / total_cost * 100
        components = f'${equity:,.0f} + ${debt:,.0f}'
        if pref_equity:
            components += f' + ${pref_equity:,.0f} (pref equity)'
        results.append({
            'check': 'Total Project Cost = Equity + Debt' + (' + Pref Equity' if pref_equity else ''),
            'status': 'pass' if diff_pct < 1 else ('warn' if diff_pct < 5 else 'fail'),
            'expected': _fmt_dollar(calc_total),
            'actual': _fmt_dollar(total_cost),
            'difference': f'{diff_pct:.1f}% off' if diff_pct > 0.1 else 'exact match',
            'formula': f'{components} = ${calc_total:,.0f}',
        })
    
    # LTV = debt / total cost
    ltv = _n(ds.get('ltv'))
    if debt and total_cost and total_cost > 0:
        calc_ltv = round(debt / total_cost * 100, 1)
        if ltv:
            diff = abs(calc_ltv - ltv)
            results.append({
                'check': 'LTV = Debt / Total Cost',
                'status': 'pass' if diff < 0.5 else ('warn' if diff < 2 else 'fail'),
                'expected': f'{calc_ltv}%',
                'actual': f'{ltv}%',
                'difference': f'{diff:.1f}pp off' if diff > 0.1 else 'match',
                'formula': f'${debt:,.0f} / ${total_cost:,.0f} × 100 = {calc_ltv}%',
            })
    
    # Equity as % of total
    if equity and total_cost and total_cost > 0:
        equity_pct = round(equity / total_cost * 100, 1)
        results.append({
            'check': 'Equity % of Total',
            'status': 'info',
            'expected': f'{equity_pct}%',
            'actual': f'{equity_pct}%',
            'difference': 'reference',
            'formula': f'${equity:,.0f} / ${total_cost:,.0f} = {equity_pct}%',
        })
    
    # GP Co-invest % check
    gp_coinvest_pct = _n(ds.get('gp_equity_coinvest_pct'))
    gp_coinvest_str = str(ds.get('gp_coinvest', ''))
    # Try to extract dollar amount from gp_coinvest
    gp_dollars = _extract_dollar(gp_coinvest_str)
    if gp_dollars and equity and equity > 0 and gp_coinvest_pct:
        calc_pct = round(gp_dollars / equity * 100, 1)
        diff = abs(calc_pct - gp_coinvest_pct)
        results.append({
            'check': 'GP Co-invest % = GP $ / Total Equity',
            'status': 'pass' if diff < 1 else ('warn' if diff < 3 else 'fail'),
            'expected': f'{calc_pct}%',
            'actual': f'{gp_coinvest_pct}%',
            'difference': f'{diff:.1f}pp off' if diff > 0.1 else 'match',
            'formula': f'${gp_dollars:,.0f} / ${equity:,.0f} = {calc_pct}%',
        })
    
    # ============================================
    # 2. PER-UNIT CALCULATIONS
    # ============================================
    
    units = _n(pd.get('unit_count'))
    sqft = _n(pd.get('total_sqft'))
    ppu = _n(pd.get('price_per_unit'))
    ppsf = _n(pd.get('price_per_sqft'))
    
    if total_cost and units and units > 0:
        calc_ppu = round(total_cost / units)
        if ppu:
            diff_pct = abs(calc_ppu - ppu) / ppu * 100
            results.append({
                'check': 'Price/Unit = Total Cost / Units',
                'status': 'pass' if diff_pct < 1 else ('warn' if diff_pct < 3 else 'fail'),
                'expected': _fmt_dollar(calc_ppu),
                'actual': _fmt_dollar(ppu),
                'difference': f'{diff_pct:.1f}% off' if diff_pct > 0.1 else 'match',
                'formula': f'${total_cost:,.0f} / {units:.0f} units = ${calc_ppu:,.0f}',
            })
    
    if total_cost and sqft and sqft > 0:
        calc_ppsf = round(total_cost / sqft)
        if ppsf:
            diff_pct = abs(calc_ppsf - ppsf) / ppsf * 100
            results.append({
                'check': 'Price/SF = Total Cost / Total SF',
                'status': 'pass' if diff_pct < 1 else ('warn' if diff_pct < 3 else 'fail'),
                'expected': _fmt_dollar(calc_ppsf),
                'actual': _fmt_dollar(ppsf),
                'difference': f'{diff_pct:.1f}% off' if diff_pct > 0.1 else 'match',
                'formula': f'${total_cost:,.0f} / {sqft:,.0f} SF = ${calc_ppsf:,.0f}',
            })
    
    # Avg SF per unit
    if sqft and units and units > 0:
        calc_avg_sf = round(sqft / units)
        results.append({
            'check': 'Average SF per Unit',
            'status': 'info',
            'expected': f'{calc_avg_sf} SF',
            'actual': f'{calc_avg_sf} SF',
            'difference': 'reference',
            'formula': f'{sqft:,.0f} / {units:.0f} = {calc_avg_sf} SF/unit',
        })
    
    # ============================================
    # 3. RETURN METRICS CROSS-CHECKS
    # ============================================
    
    irr = _n(tr.get('net_irr') or tr.get('target_irr'))
    em = _n(tr.get('net_equity_multiple') or tr.get('target_equity_multiple'))
    hold = _n(ds.get('hold_period_years'))
    coc = _n(tr.get('target_cash_on_cash'))
    pref = _n(ds.get('preferred_return'))
    min_invest = _n(ds.get('minimum_investment'))
    projected_profit = _n(tr.get('projected_profit'))
    
    # Equity multiple vs hold period consistency
    if em and hold and hold > 0:
        # Simple annual return from EM
        simple_annual = ((em - 1) / hold) * 100
        if irr:
            diff = abs(simple_annual - irr)
            results.append({
                'check': 'IRR vs Equity Multiple Consistency',
                'status': 'pass' if diff < 5 else ('warn' if diff < 10 else 'fail'),
                'expected': f'~{simple_annual:.1f}% implied annual',
                'actual': f'{irr}% IRR',
                'difference': f'{diff:.1f}pp gap (normal if distributions vary by year)',
                'formula': f'({em}x - 1) / {hold} years = {simple_annual:.1f}% simple annual',
            })
    
    # Profit per share check
    if projected_profit and min_invest and min_invest > 0:
        profit_multiple = round(projected_profit / min_invest, 2)
        total_return_pct = round(profit_multiple * 100, 1)
        results.append({
            'check': 'Profit as % of Investment (per share)',
            'status': 'info',
            'expected': f'{total_return_pct}%',
            'actual': f'${projected_profit:,.0f} on ${min_invest:,.0f}',
            'difference': 'reference',
            'formula': f'${projected_profit:,.0f} / ${min_invest:,.0f} = {total_return_pct}% total profit',
        })
    
    # Cash-on-cash vs preferred return
    if coc and pref:
        diff = abs(coc - pref)
        results.append({
            'check': 'Cash-on-Cash vs Preferred Return',
            'status': 'info' if diff < 3 else 'warn',
            'expected': f'{pref}% pref',
            'actual': f'{coc}% CoC',
            'difference': f'CoC is {coc - pref:+.1f}pp vs pref return',
            'formula': f'CoC {coc}% should be ≥ pref {pref}% for LP alignment',
        })
    
    # ============================================
    # 4. REVENUE / EXPENSE CHECKS
    # ============================================
    
    avg_rent = _n(fp.get('avg_rent_per_unit'))
    occupancy = _n(fp.get('occupancy_assumption'))
    noi = _n(fp.get('stabilized_noi'))
    exp_ratio = _n(fp.get('operating_expense_ratio'))
    
    # Revenue calculation
    if avg_rent and units and units > 0:
        annual_gpi = avg_rent * 12 * units
        results.append({
            'check': 'Gross Potential Income',
            'status': 'info',
            'expected': _fmt_dollar(annual_gpi),
            'actual': _fmt_dollar(annual_gpi),
            'difference': 'calculated',
            'formula': f'${avg_rent:,.0f}/unit × 12 months × {units:.0f} units = ${annual_gpi:,.0f}',
        })
        
        if occupancy:
            egi = annual_gpi * (occupancy / 100)
            results.append({
                'check': 'Effective Gross Income (at stated occupancy)',
                'status': 'info',
                'expected': _fmt_dollar(egi),
                'actual': _fmt_dollar(egi),
                'difference': 'calculated',
                'formula': f'${annual_gpi:,.0f} × {occupancy}% = ${egi:,.0f}',
            })
            
            # If we have expense ratio, calculate NOI
            if exp_ratio:
                calc_noi = egi * (1 - exp_ratio / 100)
                if noi:
                    diff_pct = abs(calc_noi - noi) / noi * 100
                    results.append({
                        'check': 'NOI = EGI × (1 - Expense Ratio)',
                        'status': 'pass' if diff_pct < 5 else ('warn' if diff_pct < 15 else 'fail'),
                        'expected': _fmt_dollar(calc_noi),
                        'actual': _fmt_dollar(noi),
                        'difference': f'{diff_pct:.1f}% off',
                        'formula': f'${egi:,.0f} × (1 - {exp_ratio}%) = ${calc_noi:,.0f}',
                    })
                else:
                    results.append({
                        'check': 'Estimated NOI (calculated)',
                        'status': 'info',
                        'expected': _fmt_dollar(calc_noi),
                        'actual': 'not extracted',
                        'difference': 'estimated from available data',
                        'formula': f'${egi:,.0f} × (1 - {exp_ratio}%) = ${calc_noi:,.0f}',
                    })
    
    # Revenue per unit check
    rev_per_unit = _n(uc.get('revenue_per_unit'))
    if avg_rent and rev_per_unit:
        calc_annual = avg_rent * 12
        diff_pct = abs(calc_annual - rev_per_unit) / rev_per_unit * 100
        results.append({
            'check': 'Revenue/Unit = Avg Rent × 12',
            'status': 'pass' if diff_pct < 1 else ('warn' if diff_pct < 5 else 'fail'),
            'expected': _fmt_dollar(calc_annual),
            'actual': _fmt_dollar(rev_per_unit),
            'difference': f'{diff_pct:.1f}% off' if diff_pct > 0.1 else 'match',
            'formula': f'${avg_rent:,.0f} × 12 = ${calc_annual:,.0f}',
        })
    
    # ============================================
    # 5. YIELD & COVERAGE CHECKS
    # ============================================
    
    yield_on_cost = _n(uc.get('yield_on_cost'))
    entry_cap = _n(fp.get('entry_cap_rate'))
    exit_cap = _n(fp.get('exit_cap_rate'))
    interest_rate = _n(ds.get('interest_rate'))
    
    # Yield on cost vs cap rate
    if yield_on_cost and entry_cap:
        spread = yield_on_cost - entry_cap
        results.append({
            'check': 'Yield on Cost vs Entry Cap Rate',
            'status': 'pass' if spread > 0.5 else ('warn' if spread > 0 else 'fail'),
            'expected': f'YoC ({yield_on_cost}%) > Cap ({entry_cap}%)',
            'actual': f'{spread:+.2f}% spread',
            'difference': 'positive = creating value' if spread > 0 else 'negative = overpaying',
            'formula': f'{yield_on_cost}% - {entry_cap}% = {spread:+.2f}% spread',
        })
    
    # DSCR independent calc
    dscr = _n(uc.get('dscr'))
    if noi and debt and interest_rate and interest_rate > 0:
        # Interest-only approximation
        annual_ds = debt * (interest_rate / 100)
        calc_dscr = round(noi / annual_ds, 2)
        if dscr:
            diff = abs(calc_dscr - dscr)
            results.append({
                'check': 'DSCR = NOI / Annual Debt Service',
                'status': 'pass' if diff < 0.05 else ('warn' if diff < 0.2 else 'fail'),
                'expected': f'{calc_dscr}x',
                'actual': f'{dscr}x',
                'difference': f'{diff:.2f}x off' if diff > 0.01 else 'match',
                'formula': f'${noi:,.0f} / ${annual_ds:,.0f} = {calc_dscr}x',
            })
    
    # Break-even occupancy independent calc
    beo = _n(uc.get('break_even_occupancy'))
    if avg_rent and units and debt and interest_rate and exp_ratio:
        annual_gpi = avg_rent * 12 * units
        annual_ds = debt * (interest_rate / 100)
        # BEO = (Operating Expenses + Debt Service) / GPI
        # OpEx = GPI × expense_ratio
        # Simplified: BEO = (expense_ratio + DS/GPI) × 100
        if annual_gpi > 0:
            calc_beo = round(((exp_ratio / 100) + (annual_ds / annual_gpi)) * 100, 1)
            if beo:
                diff = abs(calc_beo - beo)
                results.append({
                    'check': 'Break-even Occupancy',
                    'status': 'pass' if diff < 2 else ('warn' if diff < 5 else 'fail'),
                    'expected': f'{calc_beo}%',
                    'actual': f'{beo}%',
                    'difference': f'{diff:.1f}pp off' if diff > 0.5 else 'match',
                    'formula': f'(Expenses + Debt Service) / GPI = {calc_beo}%',
                })
    
    # ============================================
    # 6. INTERNAL CONSISTENCY CHECKS
    # ============================================
    
    # Sources = Uses check (if we have both)
    sources = _n(ds.get('total_equity_required', 0)) + _n(ds.get('debt_amount', 0))
    hard = _n(fp.get('hard_costs'))
    soft = _n(fp.get('soft_costs'))
    land = _n(fp.get('land_cost'))
    contingency = _n(fp.get('contingency'))
    
    if hard and soft and land:
        uses_total = hard + soft + land + (contingency or 0)
        if total_cost and total_cost > 0:
            diff_pct = abs(uses_total - total_cost) / total_cost * 100
            results.append({
                'check': 'Hard + Soft + Land + Contingency = Total Cost',
                'status': 'pass' if diff_pct < 2 else ('warn' if diff_pct < 10 else 'fail'),
                'expected': _fmt_dollar(total_cost),
                'actual': _fmt_dollar(uses_total),
                'difference': f'{diff_pct:.1f}% off',
                'formula': f'${hard:,.0f} + ${soft:,.0f} + ${land:,.0f} + ${(contingency or 0):,.0f} = ${uses_total:,.0f}',
            })
    
    # Avg rent per sqft cross-check
    avg_rent_psf = _n(fp.get('avg_rent_per_sqft'))
    if avg_rent and units and sqft and sqft > 0:
        avg_unit_sf = sqft / units
        calc_rent_psf = round(avg_rent / avg_unit_sf, 2)
        if avg_rent_psf:
            diff = abs(calc_rent_psf - avg_rent_psf)
            results.append({
                'check': 'Rent/SF = Avg Rent / Avg Unit SF',
                'status': 'pass' if diff < 0.1 else ('warn' if diff < 0.5 else 'fail'),
                'expected': f'${calc_rent_psf:.2f}/SF',
                'actual': f'${avg_rent_psf:.2f}/SF',
                'difference': f'${diff:.2f}/SF off' if diff > 0.01 else 'match',
                'formula': f'${avg_rent:,.0f} / {avg_unit_sf:.0f} SF = ${calc_rent_psf:.2f}/SF',
            })
    
    # ============================================
    # 7. BENCHMARK RANGE CHECKS
    # ============================================
    
    benchmarks = [
        ('LTV', ltv, 50, 80, '%', 'Typical range 50-75%'),
        ('Pref Return', pref, 6, 12, '%', 'Market standard 7-8%'),
        ('IRR', irr, 8, 30, '%', 'Realistic range 12-20%'),
        ('Equity Multiple', em, 1.2, 3.5, 'x', 'Typical 1.5-2.5x'),
        ('Cash-on-Cash', coc, 4, 15, '%', 'Typical 6-10%'),
        ('Cap Rate (Entry)', entry_cap, 3, 10, '%', 'Market dependent'),
        ('Cap Rate (Exit)', exit_cap, 3, 10, '%', 'Should be ≥ entry'),
        ('Occupancy', occupancy, 85, 98, '%', 'Realistic 93-95%'),
        ('Expense Ratio', exp_ratio, 30, 55, '%', 'Typical multifamily 40-50%'),
        ('Interest Rate', interest_rate, 3, 10, '%', 'Current market range'),
        ('DSCR', dscr, 1.0, 3.0, 'x', 'Min 1.25x, prefer >1.4x'),
        ('Yield on Cost', yield_on_cost, 4, 12, '%', 'Should exceed market cap rate'),
    ]
    
    for name, val, low, high, unit, note in benchmarks:
        if val is not None:
            if val < low or val > high:
                results.append({
                    'check': f'{name} in Normal Range',
                    'status': 'warn',
                    'expected': f'{low}-{high}{unit}',
                    'actual': f'{val}{unit}',
                    'difference': 'outside normal range',
                    'formula': note,
                })
    
    # ============================================
    # 8. COMPLETENESS CHECK
    # ============================================
    
    critical_fields = {
        'Total Project Cost': total_cost,
        'Total Equity': equity,
        'Debt Amount': debt,
        'LTV': ltv,
        'Unit Count': units,
        'Total SF': sqft,
        'Price/Unit': ppu,
        'Target IRR': irr,
        'Equity Multiple': em,
        'Preferred Return': pref,
        'Avg Rent': avg_rent,
        'Occupancy': occupancy,
        'Interest Rate': interest_rate,
    }
    
    missing = [k for k, v in critical_fields.items() if v is None]
    filled = len(critical_fields) - len(missing)
    
    results.append({
        'check': 'Critical Fields Completeness',
        'status': 'pass' if not missing else ('warn' if len(missing) <= 3 else 'fail'),
        'expected': f'{len(critical_fields)}/{len(critical_fields)} critical fields',
        'actual': f'{filled}/{len(critical_fields)} filled',
        'difference': f'Missing: {", ".join(missing)}' if missing else 'all present',
        'formula': 'These fields are essential for deal evaluation',
    })
    
    return results


def _n(val):
    """Safely convert to float."""
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _fmt_dollar(val):
    """Format as dollar amount."""
    if val is None:
        return '—'
    return f'${val:,.0f}'


def _extract_dollar(text: str):
    """Extract dollar amount from a string like '48.0% ($4,650,000)'.
    Looks for explicit $ sign first, then falls back to large numbers."""
    import re
    # First try to find explicit dollar amounts
    dollar_match = re.search(r'\$([\d,]+(?:\.\d+)?)', text)
    if dollar_match:
        try:
            return float(dollar_match.group(1).replace(',', ''))
        except ValueError:
            pass
    # Fallback: find numbers > 1000 (likely dollar amounts, not percentages)
    all_nums = re.findall(r'([\d,]+(?:\.\d+)?)', text)
    for num_str in all_nums:
        try:
            val = float(num_str.replace(',', ''))
            if val > 1000:  # Skip percentages and small numbers
                return val
        except ValueError:
            continue
    return None

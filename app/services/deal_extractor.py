import os
import io
import json
import base64
import anthropic

EXTRACTION_PROMPT = """You are a real estate investment analyst specializing in LP due diligence for syndications. Extract ALL available metrics from the following deal documents.

IMPORTANT: Brian Burke's "The Hands-Off Investor" emphasizes that LPs must distinguish between GROSS returns (project-level, before fees) and NET returns (to investor, after all fees and promote). Always try to identify BOTH. If only one is stated, note which one it is.

Return a JSON object with EXACTLY these keys (use null for any field not found in the documents):

{
  "deal_structure": {
    "investment_class": "GP/LP/Class A/Class B/Co-GP — the investment class or structure type",
    "minimum_investment": "dollar amount as number (e.g. 50000)",
    "total_equity_required": "total equity raise amount as number",
    "total_project_cost": "total project cost/budget as number",
    "construction_loan_amount": "construction/bridge loan amount as number — this is the INITIAL loan used during construction or renovation. If only one loan exists, put it here.",
    "permanent_loan_amount": "permanent/takeout loan amount as number — this is the LONG-TERM loan that replaces the construction loan after stabilization. May be larger than construction loan. null if not mentioned or same as construction loan.",
    "debt_amount": "the PRIMARY current loan amount as number — use construction_loan_amount if project is in development/construction phase, or permanent_loan_amount if already stabilized",
    "ltv": "loan-to-value ratio as percentage number (e.g. 65 for 65%) — calculate using debt_amount / total_project_cost",
    "loan_type": "construction/bridge/perm/agency/HUD/CMBS etc — describe the full loan strategy (e.g. 'construction-to-perm' or 'bridge with perm takeout')",
    "interest_rate": "loan interest rate as percentage number — if construction and perm rates differ, use construction rate and note perm rate in loan_type",
    "hold_period_years": "expected hold period in years as number",
    "waterfall_structure": "description of profit waterfall/distribution structure",
    "preferred_return": "preferred return percentage as number (e.g. 8 for 8%)",
    "promote_structure": "promote/carried interest structure description",
    "gp_coinvest": "GP co-investment amount or percentage",
    "fees_dev_fee": "development fee as percentage or dollar amount",
    "fees_asset_mgmt": "asset management fee as percentage number",
    "fees_acquisition": "acquisition fee as percentage number",
    "fees_disposition": "disposition fee as percentage number",
    "fees_construction_mgmt": "construction management fee as percentage number",
    "capital_stack": "Full capital stack breakdown — senior debt, mezzanine debt, preferred equity, common equity, GP co-invest. Describe each layer with amount and position",
    "sources_and_uses": "Sources: LP equity, GP equity, senior debt, mezzanine, etc. Uses: acquisition/land, hard costs, soft costs, reserves, fees, closing costs. Full breakdown as text",
    "gp_equity_coinvest_pct": "What percentage of total equity is the GP investing alongside LPs? As number (e.g. 5 for 5%)",
    "distribution_frequency": "Monthly, quarterly, annually, or upon sale/refi",
    "capital_call_provisions": "What happens if there's a capital call? Dilutive or punitive? What are LP obligations?",
    "exit_strategies": "All planned exit strategies: sale, refinance, recapitalize, hold for cash flow, REIT conversion",
    "investment_term_years": "Total investment term with extension options description",
    "redemption_rights": "Can LPs redeem early? Lockup period? Penalties?"
  },
  "target_returns": {
    "primary_strategy": "The sponsor's PRIMARY stated strategy: 'hold' or 'sale' or 'hold_with_sale_option'. If sponsor says they plan to hold long-term but also gives a hypothetical sale scenario, use 'hold_with_sale_option'.",
    "hold_scenario": {
      "description": "Description of the hold/cash flow scenario — when does cash flow start, what assumptions (e.g. 'Hold for cash flow after stabilization Q4 2026, 1.8%/yr rent growth, 5% interest rate')",
      "cash_on_cash_return": "Annual cash-on-cash return to investors during hold period as percentage number (e.g. 12.6)",
      "priority_return": "Priority/preferred cash-on-cash return as percentage number if different from total CoC (e.g. 11.5)",
      "annual_cash_flow_per_share": "Annual cash flow per share/unit of investment as dollar number",
      "distribution_yield": "Annual distribution yield on invested equity as percentage number"
    },
    "sale_scenario": {
      "description": "Description of the sale/exit scenario — when would sale happen, what assumptions (e.g. 'Hypothetical sale in Q1 2032, for example purposes only')",
      "is_hypothetical": "true if sponsor says this is hypothetical/for example purposes/illustration only, false if this is the actual plan",
      "assumed_sale_year": "Year of assumed sale as number (e.g. 2032)",
      "assumed_hold_years": "Number of years from investment to assumed sale as number",
      "sale_irr": "IRR assuming sale as percentage number",
      "sale_equity_multiple": "Equity multiple assuming sale as number (e.g. 2.4)",
      "projected_profit_on_sale": "Total projected profit if sold as dollar number per share/unit",
      "exit_cap_rate": "Assumed exit cap rate as percentage number if mentioned"
    },
    "target_irr": "The MOST RELEVANT IRR — use hold yield if hold strategy, or sale IRR if sale strategy. For 'hold_with_sale_option', use the HOLD cash-on-cash as the primary metric, NOT the hypothetical sale IRR.",
    "target_equity_multiple": "The MOST RELEVANT equity multiple — for hold strategies this may not apply or be hypothetical",
    "target_cash_on_cash": "target cash-on-cash return as percentage number — THIS is the primary metric for hold strategies",
    "target_avg_annual_return": "target average annual return as percentage number",
    "projected_profit": "total projected profit as dollar number",
    "gross_irr": "Gross (project-level) IRR before fees and promote as percentage number",
    "net_irr": "Net (to investor) IRR after ALL fees and promote as percentage number",
    "gross_equity_multiple": "Gross equity multiple before fees as number",
    "net_equity_multiple": "Net equity multiple after all fees as number",
    "distribution_yield": "Annual cash distribution yield on invested equity as percentage number",
    "profit_split_above_pref": "How profits split above the preferred return (e.g. '70/30 LP/GP')",
    "profit_split_above_tier2": "Second promote tier if applicable (e.g. '50/50 above 15% IRR')",
    "total_fee_drag": "Total fees as percentage of equity — sum of all sponsor fees as number"
  },
  "project_details": {
    "unit_count": "total number of units as integer",
    "unit_mix": "unit mix description (e.g. '120 1BR, 80 2BR, 40 3BR')",
    "total_sqft": "total square footage as number",
    "price_per_unit": "total project cost divided by unit count — calculate if not stated",
    "price_per_sqft": "total project cost divided by total square footage — calculate if not stated",
    "lot_size": "lot size description (acres or sqft)",
    "construction_type": "Type I/III/V/wood-frame/podium/steel etc",
    "construction_start": "expected construction start date",
    "construction_duration_months": "construction duration in months as number",
    "stabilization_date": "expected stabilization date",
    "entitlement_status": "entitled/in-process/not-started",
    "zoning": "zoning designation",
    "renovation_scope": "For value-add: per-unit renovation budget and scope (kitchens, baths, flooring, etc.)",
    "renovation_timeline_months": "Expected renovation/lease-up timeline in months as number",
    "current_occupancy": "Current occupancy rate at acquisition as percentage number",
    "current_avg_rent": "Current average rent per unit before value-add as dollar number",
    "proforma_avg_rent": "Projected rent after renovations as dollar number",
    "rent_premium": "Expected rent increase from renovations — describe dollar amount and percentage",
    "comparable_properties": "Comp properties used to justify rent assumptions"
  },
  "financial_projections": {
    "stabilized_noi": "stabilized net operating income as dollar number",
    "entry_cap_rate": "going-in/entry cap rate as percentage number",
    "exit_cap_rate": "exit/reversion cap rate as percentage number",
    "avg_rent_per_unit": "average rent per unit per month as dollar number",
    "avg_rent_per_sqft": "average rent per square foot as dollar number",
    "rent_growth_assumption": "annual rent growth assumption as percentage number",
    "occupancy_assumption": "stabilized occupancy assumption as percentage number",
    "operating_expense_ratio": "operating expense ratio as percentage number",
    "construction_budget": "total construction/hard cost budget as dollar number",
    "land_cost": "land acquisition cost as dollar number",
    "soft_costs": "soft costs (arch, eng, legal, permits) as dollar number",
    "hard_costs": "hard construction costs as dollar number",
    "contingency": "contingency amount as dollar number or percentage"
  },
  "market_location": {
    "city": "city name",
    "state": "state name or abbreviation",
    "submarket": "submarket or neighborhood name",
    "market_population": "metro/market population as number",
    "market_job_growth": "market job growth rate as percentage number",
    "market_rent_growth": "market rent growth rate as percentage number",
    "comparable_rents": "comparable rents description from documents",
    "market_vacancy_rate": "market vacancy rate as percentage number",
    "walk_score": "walk score as number (0-100)",
    "nearby_employers": "major nearby employers",
    "nearby_amenities": "nearby amenities description"
  },
  "risk_assessment": {
    "market_risk_score": "1-10 score (10=lowest risk) based on market fundamentals",
    "execution_risk_score": "1-10 based on developer track record, entitlements, construction complexity",
    "financial_risk_score": "1-10 based on leverage, assumptions aggressiveness",
    "entitlement_risk_score": "1-10 based on entitlement status and zoning",
    "developer_risk_score": "1-10 based on developer experience and track record",
    "overall_risk_score": "1-10 weighted average of above",
    "risk_notes": "brief notes on key risks identified"
  },
  "underwriting_checks": {
    "break_even_occupancy": "Minimum occupancy to cover all expenses + debt service as percentage number",
    "dscr": "Debt Service Coverage Ratio — NOI / annual debt service as number (e.g. 1.35)",
    "yield_on_cost": "Stabilized NOI / total project cost as percentage number",
    "rent_growth_vs_market": "Is assumed rent growth in line with market? Description",
    "expense_growth_assumption": "Annual expense growth assumption as percentage number",
    "cap_rate_spread": "Exit cap rate minus entry cap rate description",
    "replacement_cost_per_unit": "Cost to build new comparable units as dollar number",
    "revenue_per_unit": "Total annual revenue per unit as dollar number",
    "operating_expense_per_unit": "Total annual operating expenses per unit as dollar number",
    "management_fee_pct": "Property management fee as percentage of revenue as number",
    "reserves_per_unit": "Annual capital reserve per unit as dollar number",
    "tax_benefits": "Expected depreciation benefits, cost segregation study, K-1 losses description",
    "interest_rate_sensitivity": "How do returns change if interest rates move +/- 1%? Description",
    "exit_cap_sensitivity": "How do returns change if exit cap rate moves +/- 50bps? Description",
    "rent_growth_sensitivity": "How do returns change if rent growth is 0%? Description"
  },
  "sponsor_evaluation": {
    "sponsor_name": "Name of the syndicator/sponsor/GP",
    "sponsor_track_record": "Number of deals, years in business, total AUM description",
    "sponsor_prior_returns": "Actual realized returns on prior deals (not just projections)",
    "sponsor_full_cycle_deals": "Number of deals taken full cycle (acquired AND exited) as number",
    "sponsor_default_history": "Any defaults, foreclosures, or capital losses?",
    "sponsor_team_experience": "Key team members and their specific experience",
    "sponsor_property_mgmt": "In-house or third-party property management?",
    "sponsor_communication": "Expected reporting frequency and format",
    "sponsor_skin_in_game": "GP's personal capital at risk in this deal description",
    "alignment_score": "1-10 rating of alignment of interests (based on fees, co-invest, promote structure) as number"
  }
}

IMPORTANT RULES:
1. Return ONLY valid JSON — no markdown, no explanation, no code blocks
2. Use numbers for numeric fields (not strings like "$50,000" — just 50000)
3. Use null for any field you cannot find in the documents
4. For percentage fields, use the number only (e.g. 18.5 not "18.5%")
5. For dollar amounts, use raw numbers (e.g. 5000000 not "$5M")
6. Risk scores should be integers 1-10 where 10 = lowest risk / best
7. Be thorough — search every page of EVERY document for relevant data
8. If multiple documents are provided, COMBINE all information into a single unified extraction. Different docs may contain different pieces (e.g., offering memo has deal terms, proforma has financials, market study has comps). Merge everything.
9. If a metric appears in multiple documents, use the most recent/prominent value
9. For IRR and equity multiples, ALWAYS try to identify if they are gross or net. If the document only shows one number without specifying, put it in target_irr/target_equity_multiple AND note in the description fields
10. Calculate yield_on_cost (stabilized NOI / total project cost) and break_even_occupancy if you have enough data
11. DSCR = NOI / annual debt service — calculate if possible

DOCUMENTS TO ANALYZE:
"""


async def extract_metrics_from_docs(doc_texts: list[dict], doc_paths: list[str] = None) -> dict:
    """Send document texts AND page images to Claude for metric extraction.

    Args:
        doc_texts: List of dicts with 'filename', 'doc_type', 'text' keys
        doc_paths: Optional list of file paths to PDFs for image extraction

    Returns:
        Extracted metrics as a dict matching the schema above
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY not set")

    # Build content blocks - mix of text and images
    content_blocks = []

    # Add text context
    doc_context = ""
    for doc in doc_texts:
        doc_context += f"\n\n===== DOCUMENT: {doc['filename']} (Type: {doc['doc_type']}) =====\n"
        text = doc['text'][:30000]
        doc_context += text

    content_blocks.append({
        "type": "text",
        "text": EXTRACTION_PROMPT + doc_context
    })

    # Add page images from PDFs for vision-based extraction
    # Budget: ~12 pages total across all docs at 150 DPI to stay under API limits
    MAX_TOTAL_PAGES = 12
    DPI = 150
    pages_used = 0

    if doc_paths:
        try:
            import fitz
            # Calculate pages per doc
            total_doc_pages = 0
            doc_infos = []
            for path in doc_paths:
                if not os.path.exists(path):
                    continue
                pdf_doc = fitz.open(path)
                doc_infos.append((path, pdf_doc))
                total_doc_pages += pdf_doc.page_count

            # Distribute page budget across docs proportionally
            for path, pdf_doc in doc_infos:
                if pages_used >= MAX_TOTAL_PAGES:
                    pdf_doc.close()
                    continue

                fname = os.path.basename(path)
                pages_remaining = MAX_TOTAL_PAGES - pages_used
                # Proportional allocation, minimum 3 pages per doc
                if len(doc_infos) > 1:
                    alloc = max(3, int(MAX_TOTAL_PAGES * pdf_doc.page_count / total_doc_pages))
                else:
                    alloc = MAX_TOTAL_PAGES
                max_pages = min(pdf_doc.page_count, alloc, pages_remaining)

                content_blocks.append({
                    "type": "text",
                    "text": f"\n\nBELOW ARE PAGE IMAGES from '{fname}' ({pdf_doc.page_count} pages total, showing {max_pages}). These contain tables, charts, and formatted data that may not appear in the text above. Extract ALL numbers, fees, projections, and financial data from these images:\n"
                })
                for page_num in range(max_pages):
                    page = pdf_doc[page_num]
                    mat = fitz.Matrix(DPI/72, DPI/72)
                    pix = page.get_pixmap(matrix=mat)
                    # Convert to JPEG for smaller size (vs PNG)
                    img_bytes = pix.tobytes("jpeg")
                    img_b64 = base64.b64encode(img_bytes).decode("utf-8")
                    content_blocks.append({
                        "type": "text",
                        "text": f"Page {page_num + 1} of {pdf_doc.page_count}:"
                    })
                    content_blocks.append({
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/jpeg",
                            "data": img_b64
                        }
                    })
                    pages_used += 1
                pdf_doc.close()
        except Exception as e:
            # If image extraction fails, continue with text only
            content_blocks.append({
                "type": "text",
                "text": f"\n(Note: Could not extract page images: {e}. Relying on text only.)\n"
            })

    client = anthropic.Anthropic(api_key=api_key)
    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=8192,
        messages=[{"role": "user", "content": content_blocks}]
    )

    response_text = message.content[0].text.strip()

    # Try to parse JSON, handle potential markdown wrapping
    if response_text.startswith("```"):
        lines = response_text.split("\n")
        lines = [l for l in lines if not l.startswith("```")]
        response_text = "\n".join(lines)

    try:
        metrics = json.loads(response_text)
    except json.JSONDecodeError:
        # Try to find JSON in the response
        start = response_text.find("{")
        end = response_text.rfind("}") + 1
        if start >= 0 and end > start:
            metrics = json.loads(response_text[start:end])
        else:
            raise ValueError(f"Could not parse AI response as JSON")

    # Ensure new sections exist even if AI didn't return them
    if "underwriting_checks" not in metrics:
        metrics["underwriting_checks"] = {}
    if "sponsor_evaluation" not in metrics:
        metrics["sponsor_evaluation"] = {}

    # Post-processing: calculate derived fields if AI missed them
    _post_process_metrics(metrics)

    return metrics


def _safe_num(val):
    """Safely convert to float, returns None if not possible."""
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _post_process_metrics(metrics: dict):
    """Calculate derived fields if they're missing or obviously wrong."""
    ds = metrics.get("deal_structure", {}) or {}
    pd_ = metrics.get("project_details", {}) or {}
    fp = metrics.get("financial_projections", {}) or {}
    uc = metrics.get("underwriting_checks", {}) or {}

    total_cost = ds.get("total_project_cost")
    units = pd_.get("unit_count")
    sqft = pd_.get("total_sqft")

    # Calculate total project cost if missing but we have equity + debt
    if not total_cost or total_cost == 0:
        equity = _safe_num(ds.get("total_equity_required"))
        debt = _safe_num(ds.get("debt_amount"))
        if equity and debt:
            total_cost = equity + debt
            ds["total_project_cost"] = total_cost
        elif equity:
            total_cost = equity
            ds["total_project_cost"] = total_cost

    # ALWAYS calculate price per unit and price per sqft
    if total_cost and units and units > 0:
        pd_["price_per_unit"] = round(total_cost / units)

    if total_cost and sqft and sqft > 0:
        pd_["price_per_sqft"] = round(total_cost / sqft)

    # Reconcile construction vs permanent loans
    construction_loan = _safe_num(ds.get("construction_loan_amount"))
    permanent_loan = _safe_num(ds.get("permanent_loan_amount"))
    debt = _safe_num(ds.get("debt_amount"))

    # If we have construction loan but debt_amount is the perm loan, fix it
    if construction_loan and permanent_loan and debt:
        # If debt matches perm but project is in development, use construction loan
        if debt == permanent_loan and construction_loan < permanent_loan:
            ds["debt_amount"] = construction_loan
            debt = construction_loan
    elif construction_loan and not debt:
        ds["debt_amount"] = construction_loan
        debt = construction_loan
    elif not construction_loan and debt:
        ds["construction_loan_amount"] = debt
        construction_loan = debt

    # LTV = debt / total project cost (using current/construction loan)
    if total_cost and debt and total_cost > 0:
        calculated_ltv = round(debt / total_cost * 100, 1)
        ds["ltv"] = calculated_ltv  # Always recalculate from components
        # Also calculate perm LTV if we have it
        if permanent_loan and permanent_loan != debt:
            ds["ltv_at_stabilization"] = round(permanent_loan / total_cost * 100, 1)

    # Yield on cost = stabilized NOI / total project cost
    noi = fp.get("stabilized_noi")
    if noi and total_cost and total_cost > 0 and not uc.get("yield_on_cost"):
        uc["yield_on_cost"] = round(noi / total_cost * 100, 2)

    # DSCR = NOI / annual debt service (use perm loan for stabilized DSCR)
    interest_rate = ds.get("interest_rate")
    dscr_debt = permanent_loan or debt  # Use perm loan for stabilized DSCR if available
    if noi and dscr_debt and interest_rate and not uc.get("dscr"):
        annual_debt_service = dscr_debt * (interest_rate / 100)  # Simplified interest-only
        if annual_debt_service > 0:
            uc["dscr"] = round(noi / annual_debt_service, 2)

    # Revenue per unit
    avg_rent = fp.get("avg_rent_per_unit")
    if avg_rent and units and units > 0 and not uc.get("revenue_per_unit"):
        uc["revenue_per_unit"] = round(avg_rent * 12)

    # GP co-invest percentage calculation
    gp_coinvest_raw = ds.get("gp_coinvest")
    total_equity = ds.get("total_equity_required")
    if gp_coinvest_raw and total_equity and not ds.get("gp_equity_coinvest_pct"):
        try:
            gp_val = float(str(gp_coinvest_raw).replace("%", "").replace("$", "").replace(",", ""))
            if gp_val > 100:  # Looks like a dollar amount
                ds["gp_equity_coinvest_pct"] = round(gp_val / total_equity * 100, 1)
        except (ValueError, TypeError):
            pass

    metrics["deal_structure"] = ds
    metrics["project_details"] = pd_
    metrics["underwriting_checks"] = uc

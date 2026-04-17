import os
import io
import json
import base64
import anthropic

from app.config import MODEL_EXTRACT
from app.services.operation_log import record

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
    "gp_coinvest": "GP co-investment amount or percentage — CRITICAL: distinguish between the sponsor/GP putting in their OWN NEW CASH vs. rolling over equity from a prior phase/acquisition. If the 'GP equity' is actually prior LP investors rolling their equity forward, that is NOT true GP co-invest — note this in the description. Only count cash the GP/sponsor entity itself is contributing.",
    "fees_dev_fee": "development fee as percentage or dollar amount",
    "fees_asset_mgmt": "asset management fee as percentage number",
    "fees_acquisition": "acquisition fee as percentage number",
    "fees_disposition": "disposition fee as percentage number",
    "fees_construction_mgmt": "construction management fee as percentage number",
    "capital_stack": "Full capital stack breakdown — senior debt, mezzanine debt, preferred equity, common equity, GP co-invest. Describe each layer with amount and position",
    "sources_and_uses": "Sources: LP equity, GP equity, senior debt, mezzanine, etc. Uses: acquisition/land, hard costs, soft costs, reserves, fees, closing costs. Full breakdown as text",
    "gp_equity_coinvest_pct": "What percentage of total equity is the GP/sponsor investing with their OWN MONEY (not rolled-over LP equity from a prior phase)? As number (e.g. 5 for 5%). If the document shows a large 'GP equity' figure but it's actually rolled-over equity from prior investors, return null or the true GP-only amount.",
    "gp_coinvest_is_rollover": "true if the GP's 'co-invest' is actually rolled-over equity from a prior phase or prior LP investors rather than new cash from the sponsor. false if it's genuinely new GP money. null if unclear.",
    "gp_coinvest_description": "Describe the nature of the GP co-investment: Is it new cash? Rolled land basis? Prior LP equity rolling forward? Deferred fees? Quote the document's language.",
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
    "target_irr": "The MOST RELEVANT IRR TO THE INVESTOR — use hold yield if hold strategy, or sale IRR if sale strategy. For 'hold_with_sale_option', use the HOLD cash-on-cash as the primary metric, NOT the hypothetical sale IRR. CRITICAL: read from the INVESTOR / LP column, never from the sponsor / GP / 'Ambient' / manager column. When in doubt, the lower number is the LP return.",
    "target_equity_multiple": "The MOST RELEVANT equity multiple TO THE INVESTOR — not the sponsor's promote-inclusive multiple. For hold strategies this may not apply or be hypothetical",
    "target_cash_on_cash": "target cash-on-cash return TO THE INVESTOR as percentage number — THIS is the primary metric for hold strategies. Pull from the LP / Investor column, not the sponsor column.",
    "target_avg_annual_return": "target average annual return TO THE INVESTOR as percentage number",
    "projected_profit": "total projected profit TO THE INVESTOR as dollar number (after promote)",
    "gross_irr": "Gross (project-level / partnership-level / deal-level) IRR BEFORE fees and promote as percentage number. This is typically LARGER than net_irr.",
    "net_irr": "Net (to the LP / investor) IRR AFTER ALL fees and promote as percentage number. This is what a new LP subscribing today would actually earn — read from the Investor/LP column, NOT the sponsor's column. Typically SMALLER than gross_irr.",
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
3. Use null for any field you cannot find in the documents. NULL IS ALWAYS BETTER THAN A GUESS. If you're not confident a value is correct, return null. This tool is used for financial decisions — a wrong number is far more dangerous than a missing one.
4. For percentage fields, use the number only (e.g. 18.5 not "18.5%")
5. For dollar amounts, use raw numbers (e.g. 5000000 not "$5M")
6. Risk scores should be integers 1-10 where 10 = lowest risk / best
7. Be thorough — search every page of EVERY document for relevant data. Check the full text AND every page image. Financial tables with critical numbers often appear on pages 15-30+.
8. If multiple documents are provided, COMBINE all information into a single unified extraction. Different docs may contain different pieces (e.g., offering memo has deal terms, proforma has financials, market study has comps). Merge everything.
9. If a metric appears in multiple documents, use the most recent/prominent value
10. For IRR and equity multiples, ALWAYS try to identify if they are gross or net. If the document only shows one number without specifying, put it in target_irr/target_equity_multiple AND note in the description fields
11. Calculate yield_on_cost (stabilized NOI / total project cost) and break_even_occupancy if you have enough data
12. DSCR = NOI / annual debt service — calculate if possible
13. CROSS-CHECK YOUR WORK: After extracting, verify internal consistency:
    - total_project_cost should ≈ total_equity_required + debt_amount
    - ltv should = debt_amount / total_project_cost × 100
    - price_per_unit should = total_project_cost / unit_count
    - If any of these don't reconcile, re-examine which numbers you pulled
14. For description/text fields (waterfall_structure, sources_and_uses, etc.), be SPECIFIC and quote actual numbers from the document rather than paraphrasing vaguely

CRITICAL: WHICH COLUMN / ROW TO READ FROM
Real-estate offering documents routinely present numbers in MULTIPLE
columns or rows that look similar but report different things. The
wrong column choice is the #1 source of extraction errors. Apply
these rules strictly:

  a. LP vs SPONSOR RETURNS columns. This rule applies ONLY to the
     RETURN-LEVEL metrics: IRR, cash-on-cash, equity multiple,
     distributions, yield, profit per unit. Tables of returns often
     have a "Sponsor" / "GP" / "Manager" / "Co-GP" / "Total
     Partnership" column AND an "Investor" / "LP" / "Class A" /
     "Limited Partner" column. For returns, ALWAYS extract FROM THE
     INVESTOR / LP COLUMN — sponsor-column returns include promote
     that the LP does not receive.

     Red flags that you're in the wrong returns column:
       - Column header is the sponsor's brand/entity name
         (e.g. "Ambient", "Greenfield Partners", "JV Waterfall")
         rather than "Investor" / "LP" / a share class letter.
       - An adjacent "GP" / "Manager" / "Sponsor" column has
         materially lower returns (that's the LP column).
       - Label says "Gross", "Partnership", "Deal-Level", or
         "Project-Level" — those are before-fees / not LP.

     DOES NOT APPLY TO STRUCTURAL FIELDS. Fields that describe the
     sponsor, the GP, or the deal structure legitimately come from
     the GP / Sponsor rows and numbers. Always extract these from
     wherever the document reports them, including GP / Sponsor /
     Manager columns and rows:
       - gp_coinvest, gp_equity_coinvest_pct (the GP's co-investment
         dollars and percentage — found ON the GP row)
       - fees_dev_fee, fees_asset_mgmt, fees_acquisition,
         fees_disposition, fees_construction_mgmt (sponsor fees)
       - promote_structure, waterfall_structure, profit_split_*
       - sponsor_name, sponsor_track_record, sponsor_* fields
       - preferred_return, investment_class
     For these, the "GP column" is the SOURCE, not a trap.

  b. GROSS VS NET. When both are shown, gross_irr goes in gross_irr
     and the investor's net goes in net_irr AND target_irr. When
     only one is shown, put it in target_irr and also in whichever
     of gross_irr/net_irr the document identifies it as.

  c. HOLD VS SALE SCENARIO. OMs commonly show a long-term HOLD
     scenario (primary) and a HYPOTHETICAL SALE scenario (for
     illustration). Do NOT mix numbers across scenarios — the
     hold scenario's cash-on-cash does not belong in the sale
     scenario's IRR, and vice versa. Use primary_strategy,
     hold_scenario.*, and sale_scenario.* to keep them separate.

  d. CLASS A VS CLASS B VS ROLLED-OVER EQUITY. When multiple
     investor classes exist (Class A preferred vs Class B common,
     or "New Phase 2 Equity" vs "Rolled-Over Land Equity") the
     target_irr / target_equity_multiple should reflect the
     PRIMARY NEW-MONEY LP — the class that a new investor would
     subscribe to today. If the OM calls one class out as "for
     new investors" or "Class B New Investors", use that.

  e. If a value is in dispute between two sources in the same
     doc (e.g. summary page vs detailed table), prefer the
     detailed table with a line-item breakdown. Summary numbers
     are often rounded or promotional.

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

    # Send full document text — no truncation. A 30-page OM is ~80K
    # chars ≈ 20K tokens. With Opus 4.7's 200K context this fits
    # easily, and truncation was the #1 cause of missed data (critical
    # financial tables on page 15+ were invisible).
    doc_context = ""
    for doc in doc_texts:
        doc_context += f"\n\n===== DOCUMENT: {doc['filename']} (Type: {doc['doc_type']}) =====\n"
        doc_context += doc['text']

    content_blocks.append({
        "type": "text",
        "text": EXTRACTION_PROMPT + doc_context
    })

    # Send ALL page images from PDFs for vision-based extraction.
    # Tables, charts, and waterfall diagrams are often unreadable in
    # plain text but crystal-clear in images. At 150 DPI JPEG each
    # page is ~50-100KB; a 30-page OM totals ~3MB — well within
    # Anthropic's request limits. Cap at 30 pages as a safety valve.
    MAX_TOTAL_PAGES = 30
    DPI = 150
    pages_used = 0

    if doc_paths:
        try:
            import fitz
            doc_infos = []
            total_doc_pages = 0
            for path in doc_paths:
                if not os.path.exists(path):
                    continue
                pdf_doc = fitz.open(path)
                doc_infos.append((path, pdf_doc))
                total_doc_pages += pdf_doc.page_count

            for path, pdf_doc in doc_infos:
                if pages_used >= MAX_TOTAL_PAGES:
                    pdf_doc.close()
                    continue

                fname = os.path.basename(path)
                pages_remaining = MAX_TOTAL_PAGES - pages_used
                max_pages = min(pdf_doc.page_count, pages_remaining)

                content_blocks.append({
                    "type": "text",
                    "text": f"\n\nBELOW ARE ALL PAGE IMAGES from '{fname}' ({pdf_doc.page_count} pages total, showing {max_pages}). These contain tables, charts, and formatted data that may not appear in the text above. Extract ALL numbers, fees, projections, and financial data from these images:\n"
                })
                for page_num in range(max_pages):
                    page = pdf_doc[page_num]
                    mat = fitz.Matrix(DPI/72, DPI/72)
                    pix = page.get_pixmap(matrix=mat)
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
            content_blocks.append({
                "type": "text",
                "text": f"\n(Note: Could not extract page images: {e}. Relying on text only.)\n"
            })

    # Stages recorded separately so the diagnostics panel shows which
    # step failed — Claude call vs JSON parse vs post-process.
    filenames = [d.get("filename") for d in doc_texts] or (doc_paths or [])
    async with record(
        "extract",
        model=MODEL_EXTRACT,
        meta={
            "docs": filenames,
            "pages_used": pages_used,
            "text_chars": sum(len(d.get("text", "") or "") for d in doc_texts),
        },
    ) as op:
        client = anthropic.AsyncAnthropic(api_key=api_key)
        op.note = "calling Anthropic (async streaming)"
        # AsyncAnthropic + async streaming keeps the event loop responsive
        # during the 1-3 minute call, so healthchecks and the diagnostics
        # endpoint continue to answer. Sync streaming inside an async
        # endpoint blocks the whole worker — Railway then kills it mid-
        # call and we lose the error trail.
        response_text = ""
        input_tokens = None
        output_tokens = None
        stop_reason = None
        async with client.messages.stream(
            model=MODEL_EXTRACT,
            max_tokens=32768,
            messages=[{"role": "user", "content": content_blocks}],
        ) as stream:
            async for text_chunk in stream.text_stream:
                response_text += text_chunk
            final = await stream.get_final_message()
            try:
                input_tokens = getattr(final.usage, "input_tokens", None)
                output_tokens = getattr(final.usage, "output_tokens", None)
            except Exception:
                pass
            stop_reason = getattr(final, "stop_reason", None)

        op.input_tokens = input_tokens
        op.output_tokens = output_tokens
        op.meta["stop_reason"] = stop_reason
        if stop_reason == "max_tokens":
            raise ValueError(
                "Extraction response hit the max_tokens ceiling — "
                "Claude's JSON was truncated. Try fewer documents per "
                "extraction or a tighter prompt."
            )

        op.note = "received response, parsing"
        response_text = response_text.strip()
        # Truncated preview for the diagnostics UI — the full response
        # can be 30+ KB and we don't want to bloat the buffer.
        op.response_preview = response_text[:2000]

        # Parse defensively — strips markdown fences, falls back to
        # largest {...} span, drops stray trailing commas. Raises a
        # ValueError with a readable preview if all attempts fail.
        from app.services.deal_verifier import _parse_json_defensively
        metrics = _parse_json_defensively(response_text)

        # Ensure new sections exist even if AI didn't return them
        if "underwriting_checks" not in metrics:
            metrics["underwriting_checks"] = {}
        if "sponsor_evaluation" not in metrics:
            metrics["sponsor_evaluation"] = {}

        # Post-processing: calculate derived fields if AI missed them
        op.note = "post-processing"
        _post_process_metrics(metrics)

        op.meta["top_level_keys"] = sorted(list(metrics.keys()))
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
    tr = metrics.get("target_returns", {}) or {}

    # target_irr is the HEADLINE number on the snapshot card. For an
    # LP reading this dashboard, "target" means what THEY are
    # projected to earn — which depends on the deal's strategy.
    #
    # For HOLD strategies, the investor's actual return is bounded by
    # cash flow: preferred return + whatever excess the waterfall
    # distributes. An IRR of 17-21% on a hold deal is almost always
    # the hypothetical-sale IRR being pulled from the wrong row —
    # real hold yields are in the 8-14% range (pref + excess).
    #
    # For SALE strategies, net IRR is the right headline — it
    # includes the terminal sale value that the investor actually
    # receives.
    net = _safe_num(tr.get("net_irr"))
    gross = _safe_num(tr.get("gross_irr"))
    pref = _safe_num(ds.get("preferred_return"))  # lives on deal_structure
    coc = _safe_num(tr.get("target_cash_on_cash"))
    primary_strategy = (tr.get("primary_strategy") or "").strip().lower()

    # Try to get hold-scenario-specific return
    hold = tr.get("hold_scenario") or {}
    hold_coc = _safe_num(hold.get("cash_on_cash_return")) if isinstance(hold, dict) else None
    hold_priority = _safe_num(hold.get("priority_return")) if isinstance(hold, dict) else None

    if primary_strategy in ("hold", "hold_with_sale_option"):
        # For hold-first deals, the investor's projected return is
        # the cash flow yield, not any sale-scenario IRR.
        #
        # Priority: hold_scenario.cash_on_cash → target_cash_on_cash
        # → hold_scenario.priority_return → preferred_return.
        # NEVER use net_irr or gross_irr as target — those are
        # almost always from the hypothetical sale scenario.
        hold_return = hold_coc or coc or hold_priority or pref
        if hold_return is not None:
            tr["target_irr"] = hold_return
        elif net is not None:
            # Last resort: if we have absolutely nothing else, use
            # net_irr but sanity-check it against the pref. If it's
            # >30% above pref, it's suspiciously high for a hold deal.
            if pref is not None and net > pref * 1.3:
                tr["target_irr"] = pref
            else:
                tr["target_irr"] = net
        elif gross is not None:
            tr["target_irr"] = gross
    elif primary_strategy == "sale":
        # Sale strategy: net IRR is the right headline.
        if net is not None:
            tr["target_irr"] = net
        elif tr.get("target_irr") is None and gross is not None:
            tr["target_irr"] = gross
    else:
        # Unknown strategy: prefer net over gross.
        if net is not None:
            tr["target_irr"] = net
        elif tr.get("target_irr") is None and gross is not None:
            tr["target_irr"] = gross

    metrics["target_returns"] = tr

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

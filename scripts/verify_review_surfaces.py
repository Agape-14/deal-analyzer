"""Check saved numbers and context using the same routes the app serves."""

from io import BytesIO

import fitz
from openpyxl import load_workbook

from app.routers.deals import CompareRequest, compare_deals, export_comparison, get_deal, list_deals
from app.routers.reports import _fmt_money, _fmt_pct, deal_pdf_report
from app.services.financial_presentation import (
    RETURN_LABELS, accepted_return_fact, cash_flow_check_context, operating_fact_context, optional_sale_returns,
    return_context, return_evidence, schedule_context, schedule_source, source_reference,
)


class SurfaceMismatch(ValueError):
    """A report disagrees with Summary. Messages contain labels, never values."""


OPERATING_ROWS = (
    ("DEAL STRUCTURE", "deal_structure", "ltv", "LTV", "Loan-to-value", _fmt_pct),
    ("DEAL STRUCTURE", "deal_structure", "loan_to_cost", "Loan-to-cost", "Loan-to-cost", _fmt_pct),
    ("FINANCIAL PROJECTIONS", "financial_projections", "stabilized_noi", "Stabilized NOI", "Stabilized NOI", _fmt_money),
    ("FINANCIAL PROJECTIONS", "financial_projections", "untrended_noi", "Untrended NOI", "Untrended NOI", _fmt_money),
)
BUDGET_ROWS = {
    "total_project_cost": "Total Project Cost",
    "hard_costs_total": "Hard Costs Total",
    "soft_costs_total": "Soft Costs",
    "land_cost_total": "Land Cost",
    "financing_costs": "Financing Costs",
    "preconstruction_soft_costs": "Preconstruction Soft Costs",
    "city_agency_fees": "City and Agency Fees",
    "offsite_development_costs": "Offsite Development",
    "onsite_construction_costs": "Onsite Construction",
    "construction_leaseup_soft_costs": "Construction and Lease-up Soft Costs",
}
SCORE_ROWS = {
    "overall": "Overall Score", "returns": "Returns Score", "market": "Market Score",
    "structure": "Structure Score", "risk": "Risk Score", "financials": "Financials Score",
    "underwriting": "Underwriting Score", "sponsor": "Sponsor Score",
}


def _require(matches, surface, label, deal_id=None):
    if not matches:
        subject = f" for deal {deal_id}" if deal_id is not None else ""
        raise SurfaceMismatch(f"{surface}{subject} omitted or changed {label}.")


async def _body(response):
    return b"".join([chunk async for chunk in response.body_iterator])


def _compact(text):
    return " ".join(text.split())


def _text_check(text, fragment, label, deal_id):
    _require(not fragment or _compact(str(fragment)) in text, "PDF", label, deal_id)


def _pdf_return(text, label, value, fact, deal_id):
    multiple = fact["identity"]["unit"] == "multiple"
    _text_check(text, f"{label} {f'{value}x' if multiple else _fmt_pct(value)}", label, deal_id)
    _text_check(text, return_context(fact), f"{label} context", deal_id)
    _text_check(text, return_evidence(fact), f"{label} evidence", deal_id)


def _pdf(summary, content):
    deal_id = summary["id"]
    analysis = summary["analysis"]
    metrics, scores = analysis["accepted_metrics"], summary["scores"]
    with fitz.open(stream=content, filetype="pdf") as document:
        text = _compact(" ".join(page.get_text() for page in document))
    _text_check(text, f"Analysis revision {analysis['version']}", "analysis revision", deal_id)
    _text_check(text, "Investment Scores", "score section", deal_id)
    if scores.get("overall") is None and scores.get("provisional_overall") is not None:
        coverage = scores["coverage"]
        _text_check(text, f"{coverage['supported_categories']} of 7 categories", "partial score coverage", deal_id)
    cost = (metrics.get("deal_structure") or {}).get("total_project_cost")
    if cost is not None:
        _text_check(text, f"Total Project Cost {_fmt_money(cost)}", "project cost", deal_id)
    minimum = (metrics.get("deal_structure") or {}).get("minimum_investment")
    if minimum is not None:
        _text_check(text, f"Minimum Investment {_fmt_money(minimum)}", "minimum investment", deal_id)
    costs = {path: fact for path, fact in analysis["facts"].items() if path.startswith("construction_costs.")
             and fact.get("state") in {"checked", "manual", "calculated"} and fact.get("value") is not None}
    for fact in costs.values():
        fmt = _fmt_pct if fact["identity"]["unit"] == "percent" else _fmt_money
        _text_check(text, f"{fact['label']} {fmt(fact['value'])}", fact["label"], deal_id)
    for _, group, key, _, label, fmt in OPERATING_ROWS:
        value = (metrics.get(group) or {}).get(key)
        if value is not None:
            _text_check(text, f"{label} {fmt(value)}", label, deal_id)
            _text_check(text, operating_fact_context(analysis["facts"].get(f"{group}.{key}")), f"{label} context", deal_id)
    for key, label in RETURN_LABELS:
        fact = accepted_return_fact(analysis, key)
        if fact:
            _pdf_return(text, label, analysis["returns"][key], fact, deal_id)
    optional = optional_sale_returns(analysis)
    if optional:
        _text_check(text, "Optional Sale Scenario", "optional sale section", deal_id)
    for fact in optional:
        _pdf_return(text, fact["label"], fact["value"], fact, deal_id)
    schedule = analysis.get("return_schedule")
    if schedule:
        _text_check(text, "Projected Cash-on-Cash by Year", "schedule section", deal_id)
        _text_check(text, schedule_context(schedule), "schedule context", deal_id)
        _text_check(text, schedule_source(schedule), "schedule source", deal_id)
        for row in schedule["rows"]:
            value = _fmt_pct(row["cash_on_cash_pct"]) if row["cash_on_cash_pct"] is not None else "Not projected"
            _text_check(text, f"Year {row['year']} {value}", "schedule row", deal_id)
    check = analysis.get("return_crosscheck")
    if check:
        _text_check(text, "PDF Cash-Flow Check", "cash-flow check", deal_id)
        _text_check(text, cash_flow_check_context(check), "cash-flow check context", deal_id)
        if check["status"] == "current":
            _text_check(text, f"Annual-period IRR {_fmt_pct(check['annual_irr_pct'])}", "cash-flow IRR", deal_id)
            if check["cash_flow_multiple"] is not None:
                _text_check(text, f"Cash-flow multiple {check['cash_flow_multiple']:.2f}x", "cash-flow multiple", deal_id)
            for row in check["rows"]:
                _text_check(text, f"{row['label']} {check['currency']} {row['amount']:,.2f}", "annual cash-flow row", deal_id)
                for item in (row.get("flow_scope_label"), source_reference(row["evidence"])):
                    _text_check(text, item, "cash-flow row context", deal_id)
        else:
            _text_check(text, "Source version changed. Recheck the calculation.", "cash-flow stale status", deal_id)


def _spreadsheet(workbook, summaries):
    sheet = workbook["Deal Comparison"]
    sections = {"SCORES", "DEAL STRUCTURE", "TARGET RETURNS", "PROJECT DETAILS", "CONSTRUCTION COSTS", "FINANCIAL PROJECTIONS"}
    rows, section = {}, ""
    for label, *values in sheet.iter_rows(min_row=2, values_only=True):
        if label in sections:
            section = label
        elif label:
            rows[section, label] = values
    costs_count, scheduled, optional, cashflows = 0, [], [], []
    for index, summary in enumerate(summaries):
        deal_id, name, analysis, scores = summary["id"], summary["project_name"], summary["analysis"], summary["scores"]
        metrics = analysis["accepted_metrics"]

        def check(section, label, expected):
            cells = rows.get((section, label))
            _require(cells is not None and cells[index] == expected, "XLSX", label, deal_id)

        for key, label in SCORE_ROWS.items():
            score = scores.get(key) if key == "overall" else (scores.get(key) or {}).get("score")
            check("SCORES", label, score)
            basis = (scores.get("comparison_basis", {}).get(key) or {}).get("inputs") or []
            check("SCORES", f"{label} basis", ", ".join(basis) or None)
        check("DEAL STRUCTURE", "Total Project Cost", (metrics.get("deal_structure") or {}).get("total_project_cost"))
        check("DEAL STRUCTURE", "Minimum Investment", (metrics.get("deal_structure") or {}).get("minimum_investment"))
        for key, label in BUDGET_ROWS.items():
            value = (metrics.get("construction_costs") or {}).get(key)
            check("CONSTRUCTION COSTS", label, value)
            costs_count += int(value is not None)
        for section, group, key, label, _, _ in OPERATING_ROWS:
            check(section, label, (metrics.get(group) or {}).get(key))
            context = operating_fact_context(analysis["facts"].get(f"{group}.{key}"))
            check(section, f"{label} Context", context or None)
        for key, label in RETURN_LABELS:
            fact = accepted_return_fact(analysis, key)
            check("TARGET RETURNS", label, analysis["returns"].get(key))
            check("TARGET RETURNS", f"{label} Context", return_context(fact) if fact else None)
            check("TARGET RETURNS", f"{label} Evidence", return_evidence(fact))
        for fact in optional_sale_returns(analysis):
            optional.append((name, fact["label"], fact["value"], fact["identity"]["unit"],
                             return_context(fact), return_evidence(fact)))
        schedule = analysis.get("return_schedule")
        if schedule:
            for row in schedule["rows"]:
                scheduled.append((name, row["year"], row["cash_on_cash_pct"], schedule_context(schedule),
                                  row.get("note") or None, schedule.get("assumptions") or None, schedule_source(schedule, row)))
        flow = analysis.get("return_crosscheck")
        if flow:
            current = flow["status"] == "current"
            for row in flow["rows"] if current else [{}]:
                sources = (row.get("evidence") or []) + (row.get("event_evidence") or [])
                cashflows.append((name, "Checked" if current else "Source changed", cash_flow_check_context(flow),
                                  flow["annual_irr_pct"], flow["cash_flow_multiple"], row.get("label"), row.get("amount"),
                                  row.get("flow_scope_label"), row.get("date_label"), flow["calculation_basis"],
                                  source_reference(sources or flow["evidence"])))
    for name, expected in (("Optional Sale Scenarios", optional), ("Return Projections", scheduled), ("PDF Cash Flow Checks", cashflows)):
        actual = list(workbook[name].iter_rows(min_row=2, values_only=True)) if name in workbook.sheetnames else []
        _require(len(actual) == len(expected) and all(len(a) == len(b) and all(
            (abs(x - y) < 1e-9 if isinstance(x, (float, int)) and isinstance(y, (float, int)) else x == y)
            for x, y in zip(a, b)) for a, b in zip(actual, expected)), "XLSX", name)
    return costs_count, len(scheduled), len(optional), len(cashflows)


async def verify_review_surfaces(db, deals: list, *, audit_scores=False) -> dict:
    """Verify Summary, Compare and both downloads without saving their contents."""
    ids = [deal.id for deal in deals]
    request = CompareRequest(deal_ids=ids)
    summaries = [await get_deal(deal_id, db) for deal_id in ids]
    compared = (await compare_deals(request, db))["deals"]
    _require([row["id"] for row in compared] == ids, "Compare", "selected deal order")
    for summary, comparison in zip(summaries, compared):
        deal_id = summary["id"]
        for key in ("version", "returns", "return_schedule", "return_crosscheck", "findings",
                    "accepted_metrics", "facts", "financing", "readiness"):
            _require(comparison["analysis"][key] == summary["analysis"][key], "Compare", key, deal_id)
        _require(comparison["scores"] == summary["scores"], "Compare", "scores", deal_id)
        _pdf(summary, await _body(await deal_pdf_report(deal_id, db)))
    with BytesIO(await _body(await export_comparison(request, db))) as buffer:
        workbook = load_workbook(buffer, read_only=True, data_only=True)
        try:
            budgets, schedule, sales, cashflows = _spreadsheet(workbook, summaries)
        finally:
            workbook.close()
    result = {"summary_deals": len(summaries), "compared_deals": len(compared), "pdf_reports": len(ids),
            "xlsx_workbooks": 1, "budget_values": budgets, "schedule_rows": schedule, "optional_sale_values": sales,
            "cash_flow_check_rows": cashflows}
    if audit_scores:
        dashboard = {item["id"]: item for item in await list_deals(False, db)}
        for summary in summaries:
            deal_id = summary["id"]
            candidate = (dashboard.get(deal_id) or {}).get("analysis") or {}
            for key in ("review_coverage", "readiness", "findings", "return_crosscheck"):
                _require(candidate.get(key) == summary["analysis"][key], "Dashboard", key, deal_id)
        result["dashboard_deals"] = len(summaries)
        categories = ("returns", "market", "structure", "risk", "financials", "underwriting", "sponsor")
        result["review_audit"] = {}
        for summary in summaries:
            analysis = summary["analysis"]
            scores = summary["scores"]
            result["review_audit"][summary["id"]] = {
                "revision": analysis["version"],
                "score_coverage": scores.get("coverage"),
                "unscored": {category: (scores.get(category) or {}).get("missing_inputs", [])
                             for category in categories if (scores.get(category) or {}).get("score") is None},
                "review_groups": {group["key"]: group["status"] for group in analysis["review_coverage"]["groups"]},
                "readiness": {check["key"]: check["status"] for check in analysis["readiness"]["checks"]},
            }
    return result

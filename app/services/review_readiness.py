"""Check the published analysis with the same evidence used by each deal view."""

import math

from app.services.financial_presentation import RETURN_LABELS, accepted_return_fact
from app.services.review_coverage import ACCEPTED_STATES


TOTAL = "deal_structure.total_project_cost"
BUDGET_TOTAL = "construction_costs.total_project_cost"
EQUITY = "deal_structure.total_equity_required"
DEBT = "deal_structure.debt_amount"
CONSTRUCTION_LOAN = "deal_structure.construction_loan_amount"
COSTS = (
    "construction_costs.land_cost_total", "construction_costs.hard_costs_total",
    "construction_costs.soft_costs_total", "construction_costs.financing_costs",
)
DETAILED_COSTS = (
    "construction_costs.land_cost_total", "construction_costs.preconstruction_soft_costs",
    "construction_costs.city_agency_fees", "construction_costs.offsite_development_costs",
    "construction_costs.onsite_construction_costs", "construction_costs.construction_leaseup_soft_costs",
    "construction_costs.financing_costs",
)
RETURN_CONTEXT = (
    ("scenario", "scenario"), ("investor_class", "investor class"),
    ("basis", "calculation basis"), ("period", "return period"),
)


def _result(key, label, status, detail, paths=()):
    return {"key": key, "label": label, "status": status, "detail": detail, "paths": list(paths)}


def _accepted_number(facts, path):
    fact = facts.get(path) or {}
    value = fact.get("value")
    if fact.get("state") in ACCEPTED_STATES and isinstance(value, (int, float)) and math.isfinite(value):
        return value
    return None


def _different_context(facts, paths):
    for dimension in ("currency", "debt_phase", "period"):
        scopes = {(facts[path].get("identity") or {}).get(dimension, "").casefold().strip() for path in paths}
        if len(scopes - {"", "unspecified"}) > 1:
            return True
    return False


def _reconcile(facts, key, label, component_paths, total_path, difference_message):
    paths = (*component_paths, total_path)
    values = [_accepted_number(facts, path) for path in paths]
    if any(value is None for value in values):
        return _result(key, label, "incomplete", "Some amounts still need source evidence.",
                       [path for path, value in zip(paths, values) if value is None])
    if _different_context(facts, paths):
        return _result(key, label, "attention", "The amounts use different phases, periods, or currencies.", paths)
    difference = math.fsum(values[:-1]) - values[-1]
    if abs(difference) > 1:
        return _result(key, label, "attention", difference_message.format(difference=abs(difference)), paths)
    return _result(key, label, "checked", "The accepted amounts reconcile within one currency unit.", paths)


def _funding_check(facts, financing):
    label = "Funding"
    debt = (facts.get(DEBT) or {}).get("identity") or {}
    different_balance = (debt.get("debt_phase") in {"permanent", "bridge"}
                         or financing.get("debt_amount_kind") in {"peak_balance", "modeled_payoff"})
    debt_path = DEBT
    if (different_balance or _accepted_number(facts, DEBT) is None) and _accepted_number(facts, CONSTRUCTION_LOAN) is not None:
        debt_path = CONSTRUCTION_LOAN
    elif different_balance:
        draw_checked = any(measure.get("kind") == "draw" and measure.get("state") == "checked"
                           for measure in financing.get("measures", []))
        detail = ("Use the reviewed construction draw with costs on the same basis."
                  if draw_checked else "The saved debt measures a different phase or balance. Find funding and costs on the same basis.")
        return _result("funding", label, "incomplete",
                       detail, (DEBT,))
    cost = TOTAL if _accepted_number(facts, TOTAL) is not None else BUDGET_TOTAL
    return _reconcile(facts, "funding", label, (debt_path, EQUITY), cost,
                      "Debt plus equity differs from project cost by {difference:,.0f}. Check for another funding source or use.")


def _budget_check(facts):
    label = "Construction budget"
    structure_total, budget_total = (_accepted_number(facts, path) for path in (TOTAL, BUDGET_TOTAL))
    if structure_total is not None and budget_total is not None:
        if _different_context(facts, (TOTAL, BUDGET_TOTAL)):
            return _result("budget", label, "attention", "The two project cost totals use different scopes.", (TOTAL, BUDGET_TOTAL))
        if abs(structure_total - budget_total) > 1:
            return _result("budget", label, "attention", "The accepted project cost and budget total differ.", (TOTAL, BUDGET_TOTAL))
    total_path = BUDGET_TOTAL if budget_total is not None else TOTAL
    # Some source budgets use phases in place of aggregate hard and soft costs.
    # Keep each complete breakdown independent so a subtotal cannot be counted twice.
    components = DETAILED_COSTS if all(_accepted_number(facts, path) is not None for path in DETAILED_COSTS) else COSTS
    return _reconcile(facts, "budget", label, components, total_path,
                      "The budget components differ from the total by {difference:,.0f}. Check for other costs or overlapping subtotals.")


def _return_check(analysis, coverage):
    label = "Return context"
    facts = [fact for key, _ in RETURN_LABELS if (fact := accepted_return_fact(analysis, key))]
    schedule = analysis.get("return_schedule")
    missing = {}
    for fact in facts:
        identity = fact.get("identity") or {}
        for key, name in RETURN_CONTEXT:
            if str(identity.get(key) or "").casefold().strip() in {"", "unspecified", "unknown"}:
                missing.setdefault(fact["path"], []).append(name)
    if missing:
        fields = ", ".join(dict.fromkeys(name for names in missing.values() for name in names))
        return _result("returns", label, "attention", f"Confirm the {fields} for the displayed return.", missing)
    if facts or (schedule and any(row.get("cash_on_cash_pct") is not None for row in schedule["rows"])):
        return _result("returns", label, "checked", "The published projection includes its investor class, basis, and period.")
    status = next((group["status"] for group in coverage["groups"] if group["key"] == "primary_return"), None)
    if status in {"not_stated", "not_applicable"}:
        return _result("returns", label, status, "The primary return was accounted for in the source review.")
    return _result("returns", label, "incomplete", "A source-supported projection is still needed for the primary strategy.")


def review_readiness(analysis):
    coverage = analysis["review_coverage"]
    source_status = coverage["sources"]["status"]
    source_detail = {
        "read": "Reading completed for the active sources.",
        "unread": "Open Documents to read or reprocess the active sources.",
        "partial": "Review reading warnings in Documents before concluding a value is absent.",
        "unknown": "Check whether all active source pages and sheets were read.",
        "no_documents": "Add the offering or model in Documents.",
    }
    checks = [
        _result("sources", "Document reading", "checked" if source_status == "read" else "incomplete", source_detail[source_status]),
        _funding_check(analysis["facts"], analysis.get("financing") or {}),
        _budget_check(analysis["facts"]),
        _return_check(analysis, coverage),
    ]
    return {"checks": checks, "attention_count": sum(check["status"] in {"attention", "incomplete"} for check in checks)}

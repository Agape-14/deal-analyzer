"""An investment keeps its approved underwriting baseline after deal edits."""
from copy import deepcopy
from datetime import datetime, timezone

TERM_FIELDS = ("investment_class", "preferred_return", "projected_irr",
               "projected_equity_multiple", "projected_cash_on_cash", "hold_period_years")


def scoped_structure_value(analysis, structure, key, investor_class):
    context = ((analysis.get("facts") or {}).get("deal_structure." + key) or {}).get("identity") or {}
    stated_class = str(context.get("investor_class") or "unspecified").casefold()
    stated_scenario = str(context.get("scenario") or "unspecified").casefold()
    strategy = analysis.get("primary_strategy")
    scenario = "hold" if strategy in {"hold", "hold_with_sale_option"} else strategy
    if stated_class not in {"", "unspecified"} and stated_class != str(investor_class).casefold():
        return None
    if stated_scenario not in {"", "unspecified"} and stated_scenario != scenario:
        return None
    return structure.get(key)


def accepted_forecast(deal, analysis):
    from app.version import release_identity

    metrics = analysis.get("accepted_metrics") or {}
    structure = metrics.get("deal_structure") or {}
    returns = analysis.get("returns") or {}
    schedule = analysis.get("return_schedule")
    investor_class = analysis.get("investor_class") or "unspecified"
    if investor_class == "unspecified" and schedule:
        investor_class = schedule.get("investor_class") or investor_class
    if investor_class == "unspecified":
        classes = {((analysis.get("facts") or {}).get(returns.get(key + "_path")) or {}).get("identity", {}).get("investor_class")
                   for key in ("target_irr", "target_equity_multiple", "cash_on_cash") if returns.get(key) is not None}
        classes.discard(None)
        classes.discard("unspecified")
        if len(classes) == 1:
            investor_class = classes.pop()
    if investor_class == "unspecified":
        investor_class = structure.get("investment_class") or ""
    terms = {
        "investment_class": investor_class,
        "preferred_return": scoped_structure_value(analysis, structure, "preferred_return", investor_class),
        "projected_irr": returns.get("target_irr"),
        "projected_equity_multiple": returns.get("target_equity_multiple"),
        "projected_cash_on_cash": returns.get("cash_on_cash"),
        "hold_period_years": scoped_structure_value(analysis, structure, "hold_period_years", investor_class),
    }
    paths = {returns.get(key + "_path") for key in ("target_irr", "target_equity_multiple", "cash_on_cash")}
    paths.update({"deal_structure.preferred_return", "deal_structure.hold_period_years", "deal_structure.investment_class"})
    facts = {path: deepcopy(fact) for path, fact in (analysis.get("facts") or {}).items()
             if path in paths and fact.get("state") in {"checked", "manual", "calculated"}}
    # No source documents or extracted text are copied into this position record.
    return {
        "schema_version": 1, "captured_at": datetime.now(timezone.utc).isoformat(),
        "deal_id": deal.id, "deal_revision": deal.revision,
        "analysis_version": analysis.get("version"), "analysis_input_hash": analysis.get("input_hash"),
        "analysis_created_at": analysis.get("created_at"),
        "app_commit": release_identity()["backend_commit"],
        "primary_strategy": analysis.get("primary_strategy"), "terms": terms,
        "returns": deepcopy(returns), "facts": facts,
        "return_schedule": deepcopy(schedule),
    }


def record_term_overrides(inv, changes, reason="", *, force_fields=()):
    """Retain baseline evidence and attribute every changed investor term."""
    baseline = (inv.forecast_snapshot or {}).get("terms") or {}
    overrides = deepcopy(inv.terms_overrides or {})
    for field, (previous, value) in changes.items():
        if field not in TERM_FIELDS or (previous == value and field not in force_fields):
            continue
        event = {"previous_value": previous, "value": value,
                 "recorded_at": datetime.now(timezone.utc).isoformat(), "reason": reason.strip(),
                 "source": "manual", "investor_class": inv.investment_class}
        history = list((overrides.get(field) or {}).get("history") or [])
        history.append(event)
        overrides[field] = {**event, "baseline_value": baseline.get(field), "history": history}
    inv.terms_overrides = overrides or None

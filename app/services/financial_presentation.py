"""Presentation of accepted return evidence shared by PDF and XLSX exports."""

RETURN_LABELS = (
    ("target_irr", "Target IRR"),
    ("target_equity_multiple", "Equity Multiple"),
    ("cash_on_cash", "Cash-on-Cash"),
)
_CONTEXT = (
    ("scenario", "Scenario"),
    ("investor_class", "Investor class"),
    ("basis", "Calculation basis"),
    ("period", "Period"),
)


def accepted_return_fact(analysis, key):
    returns = analysis.get("returns") or {}
    if returns.get(key) is None:
        return None
    return (analysis.get("facts") or {}).get(returns.get(f"{key}_path"))


def return_context(fact):
    identity = (fact or {}).get("identity") or {}
    parts = []
    for field, label in _CONTEXT:
        value = identity.get(field) or "unspecified"
        if field == "scenario":
            value = value.replace("_", " ")
        parts.append(f"{label}: {value}")
    return " · ".join(parts)


def source_reference(evidence):
    parts = []
    for item in evidence or []:
        source = item["document_name"]
        if item.get("page"):
            source += f", p. {item['page']}"
        if item.get("sheet"):
            source += f", {item['sheet']}"
        if item.get("cell"):
            source += f" {item['cell']}"
        parts.append(source)
    return " · ".join(dict.fromkeys(parts))


def return_evidence(fact):
    if not fact:
        return None
    note = fact.get("reason") if fact.get("state") == "manual" else None
    source = source_reference(fact.get("evidence"))
    return " · ".join(part for part in (source, note) if part) or None


def schedule_context(schedule):
    return (
        f"Investor class: {schedule['investor_class']}"
        f" · Equity basis: {schedule['equity_basis']}"
        f" · Period: {schedule['period_basis']}"
    )
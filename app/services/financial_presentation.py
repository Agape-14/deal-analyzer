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


def optional_sale_returns(analysis):
    if not str(analysis.get("primary_strategy", "")).startswith("hold"):
        return []
    return [fact for path, fact in (analysis.get("facts") or {}).items()
            if path.startswith("target_returns.") and fact.get("value") is not None
            and fact.get("state") in {"checked", "calculated", "manual"}
            and fact.get("identity", {}).get("scenario") == "sale"
            and fact.get("identity", {}).get("unit") in {"percent", "multiple"}]


def return_context(fact):
    identity = (fact or {}).get("identity") or {}
    parts = []
    for field, label in _CONTEXT:
        value = identity.get(field) or "unspecified"
        if field == "scenario":
            value = value.replace("_", " ")
        parts.append(f"{label}: {value}")
    return " · ".join(parts)


def operating_fact_context(fact):
    identity = (fact or {}).get("identity") or {}
    return " · ".join(identity[key] for key in ("debt_phase", "basis", "period")
                      if identity.get(key) and identity[key] != "unspecified")


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


def schedule_source(schedule, row=None):
    # The document and sheet/page are common to the schedule. A workbook
    # cell identifies one year, so include it only for that year's row.
    cell = row.get("source_cell") if row else None
    return source_reference([{**item, "cell": cell} for item in schedule["evidence"]])


def schedule_context(schedule):
    return (
        f"Investor class: {schedule['investor_class']}"
        f" · Equity basis: {schedule['equity_basis']}"
        f" · Period: {schedule['period_basis']}"
    )

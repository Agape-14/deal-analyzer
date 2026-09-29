"""Answers rendered from the current analysis, without generated financial claims."""
from __future__ import annotations
import re
from app.services.analysis import ACCEPTED

DEFINITIONS = {
    "irr": "IRR measures the annualized return of dated cash flows. It is not an annual cash distribution rate.",
    "cash": "Cash-on-cash return measures cash distributions relative to invested equity for the stated period. It does not include an assumed sale profit.",
    "multiple": "Equity multiple measures total proceeds relative to invested equity. It does not describe how long the investment takes.",
    "leverage": "Leverage adds debt obligations. A downside calculation needs a supported cash-flow model; accepted debt terms alone do not establish a downside return.",
}

def format_fact(fact):
    value, identity = fact["value"], fact["identity"]
    unit = identity["unit"]
    if isinstance(value, (int, float)):
        number = f"{value:,.2f}".rstrip("0").rstrip(".")
        value = {"percent": f"{number}%", "multiple": f"{number}x", "years": f"{number} years",
                 "months": f"{number} months", "currency": f"{identity.get('currency', 'unspecified')} {number}"}.get(unit, number)
    elif isinstance(value, list):
        value = "; ".join(f"{tier['threshold']}% hurdle: LP {tier['lp_split']}%, GP {tier['gp_split']}%" for tier in value)
    context = [f"{key.replace('_', ' ')}: {identity[key]}" for key in
               ("scenario", "investor_class", "basis", "debt_phase", "period") if identity.get(key) not in (None, "", "unspecified")]
    state = {"manual": "analyst-resolved", "checked": "source-checked", "calculated": "calculated"}[fact["state"]]
    return f"{fact['label']}: {value} ({state}{'; ' + '; '.join(context) if context else ''})."

def answer_from_analysis(analysis, question):
    query = question.lower()
    facts, returns = analysis["facts"], analysis["returns"]
    paths, lines = [], []
    asks_returns = bool(re.search(r"return|irr|yield|multiple|cash.on.cash", query))
    asks_questions = bool(re.search(r"risk|missing|question|conflict|uncertain|memo|check", query))
    asks_debt = bool(re.search(r"debt|leverage|loan|ltv|interest|downside", query))
    asks_terms = bool(re.search(r"term|structure|minimum|cost|equity|capital|hold|unit|sponsor|class", query))
    if asks_returns or not (asks_questions or asks_debt or asks_terms):
        lines.append("Current headline returns:")
        for key, label in (("target_irr", "IRR"), ("cash_on_cash", "Cash-on-cash return"), ("target_equity_multiple", "Equity multiple")):
            path = returns.get(key + "_path")
            if returns.get(key) is not None and path in facts and facts[path]["state"] in ACCEPTED:
                paths.append(path)
            else:
                lines.append(f"{label}: Unavailable in the current reviewed analysis.")
    if asks_debt or asks_terms:
        terms = ("debt", "loan", "ltv", "interest", "amortization") if asks_debt else ("minimum_investment", "hold_period", "investment_term", "total_equity", "total_project", "unit_count", "preferred_return")
        paths.extend(path for path, fact in facts.items() if fact["state"] in ACCEPTED and any(term in path for term in terms))
    for path, fact in facts.items():
        if fact["state"] in ACCEPTED and fact["label"].lower() in query and not path.startswith("target_returns."):
            paths.append(path)
    references = []
    for path in dict.fromkeys(paths):
        fact = facts[path]
        lines.append(format_fact(fact))
        sources = []
        for evidence in fact.get("evidence", []):
            location = f"page {evidence['page']}" if evidence.get("page") else " / ".join(str(evidence[k]) for k in ("sheet", "cell") if evidence.get(k))
            sources.append(f"{evidence.get('document_name', 'Source')}{', ' + location if location else ''}")
        if sources:
            lines.append("Source: " + "; ".join(dict.fromkeys(sources)))
        if fact.get("formula"):
            lines.append("Calculation: " + fact["formula"])
        references.append({"path": path, "state": fact["state"], "evidence": fact.get("evidence", []), "dependencies": fact.get("dependencies", [])})
    questions = analysis.get("questions", [])
    if asks_questions or asks_returns or not references:
        if questions:
            lines.append("Open evidence questions:")
            lines.extend(f"• {q['title']}: {q['impact']}" for q in questions)
        elif asks_questions:
            lines.append("No material evidence questions are currently recorded. This does not establish investment suitability.")
    if re.search(r"what.*(mean|is)|explain|plain english|difference|leverage|downside", query):
        lines.extend(text for key, text in DEFINITIONS.items() if key in query or (asks_returns and key != "leverage"))
    if not references:
        lines.append("No accepted fact answers this question yet. Review the Questions tab or add the relevant source document.")
    lines.append("Only current reviewed facts are shown. Unspecified class, basis, currency or period remains unspecified.")
    return "\n\n".join(lines), references

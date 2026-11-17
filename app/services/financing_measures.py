"""Project explicitly reviewed construction financing measures into analysis."""

from __future__ import annotations

from typing import Literal

FinancingKind = Literal["draw", "peak_balance", "modeled_payoff", "lender_commitment"]

FINANCING_LABELS = {
    "draw": "Construction loan draw",
    "peak_balance": "Modeled peak construction loan balance",
    "modeled_payoff": "Modeled construction debt at payoff",
    "lender_commitment": "Construction lender commitment",
}
FINANCING_KEY = "_financing_measures"
DEBT_PATH = "deal_structure.debt_amount"
DEBT_LABEL = "Debt amount"


def financing_document_set(documents):
    from app.services.analysis import digest

    # A primary source change can change the meaning of a financing measure.
    # Identical copies excluded from review do not change the evidence set.
    active_sources = [
        (item["id"], item["content_hash"])
        for item in documents
        if item.get("source_role", "active") == "active" and item.get("included_in_review", True)
    ]
    return digest(sorted(active_sources))


def matching_debt_amount(metrics, debt_amount, amount):
    """A display label must stay attached to its approved amount and phase."""
    contexts = metrics.get("_fact_context") or {}
    context = contexts.get(DEBT_PATH) or {}
    debt_phase = str(context.get("debt_phase") or "").strip().casefold()
    currency = str(context.get("currency") or "").strip().casefold()
    return (
        debt_amount is not None
        and debt_amount == amount
        and debt_phase in ("", "unspecified", "construction")
        and currency in ("", "unspecified", "usd")
    )


def project_financing(metrics, documents, debt_amount):
    from app.services.analysis import evidence_for

    result = {
        "debt_amount_kind": None,
        "debt_amount_label": DEBT_LABEL,
        "debt_amount_currency": None,
        "measures": [],
    }
    record = metrics.get(FINANCING_KEY)
    if not isinstance(record, dict) or record.get("version") != 1:
        return result

    selected_kind = record.get("debt_amount_kind")
    evidence_current = record.get("document_set") == financing_document_set(documents)
    active_documents = [item for item in documents if item.get("included_in_review", True)]
    rows = record.get("measures")
    for item in rows if isinstance(rows, list) else []:
        if not isinstance(item, dict) or not isinstance(item.get("citation"), dict):
            continue
        kind = item.get("kind")
        if not isinstance(kind, str) or kind not in FINANCING_LABELS:
            continue
        citation = item["citation"]
        evidence, error = evidence_for(citation, active_documents)
        current = evidence_current and not error and len(evidence) == 1
        amount = item.get("amount")
        if not isinstance(amount, (float, int)) or isinstance(amount, bool) or not 0 <= amount <= 10**15:
            continue
        if current and kind == selected_kind and matching_debt_amount(metrics, debt_amount, amount):
            result["debt_amount_kind"] = kind
            result["debt_amount_label"] = FINANCING_LABELS[kind]
            result["debt_amount_currency"] = "USD"
        result["measures"].append({
            "kind": kind,
            "label": FINANCING_LABELS[kind],
            "amount": amount,
            "currency": "USD",
            "debt_phase": "construction",
            "note": item.get("note", ""),
            "state": "checked" if current else "stale",
            "evidence": evidence if current else [],
            "citation": citation,
        })
    return result

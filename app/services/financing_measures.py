"""Project cited construction financing measures into analysis."""

from __future__ import annotations

import re
from typing import Literal

from app.services.source_evidence import normalized_text

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
CONSTRUCTION_LOAN_PATH = "deal_structure.construction_loan_amount"
COMMITMENT_LABEL = r"construction (?:loan|lender|debt) commitment"
COMMITMENT_AMOUNT = r"(?:(?:usd\s+)?\$?|us\$)\s*((?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)(?:\s+usd)?"


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


def _commitment_quote_amount(citation):
    quote = citation.get("source_excerpt")
    if not isinstance(quote, str) or len(quote) > 1000:
        return None
    if citation.get("source_page") and not (citation.get("source_sheet") or citation.get("source_cell")):
        match = re.fullmatch(rf"{COMMITMENT_LABEL}\s*[:=–—]?\s*{COMMITMENT_AMOUNT}\.?", normalized_text(quote))
        return match[1] if match else None
    cell = str(citation.get("source_cell") or "").lower()
    address = re.fullmatch(r"[a-z]{1,3}([1-9]\d*)", cell)
    if not citation.get("source_sheet") or not address or citation.get("source_page"):
        return None
    row = address[1]
    matches = re.findall(
        rf"(?:^|\|)\s*[a-z]{{1,3}}{row}\s*=\s*{COMMITMENT_LABEL}\s*\|\s*"
        rf"{cell}\s*=\s*{COMMITMENT_AMOUNT}(?=\s*(?:\||$))",
        normalized_text(quote),
    )
    return matches[0] if len(matches) == 1 else None


def _accepted_commitment(metrics, active_documents, fact):
    from app.services.analysis import evidence_for

    if not fact or fact["state"] != "checked" or not 0 < fact["value"] <= 10**15:
        return None
    identity = fact["identity"]
    if identity["currency"].casefold() != "usd" or not re.fullmatch(COMMITMENT_LABEL, normalized_text(identity["basis"])):
        return None
    context = (metrics.get("_fact_context") or {}).get(CONSTRUCTION_LOAN_PATH) or {}
    if normalized_text(context.get("debt_phase")) not in {"", "unspecified", "construction"}:
        return None
    provenance = (metrics.get("_provenance") or {}).get(CONSTRUCTION_LOAN_PATH) or {}
    if type(provenance.get("source_doc_id")) is not int or not provenance.get("source_document_hash"):
        return None
    citation = {key: value for key, value in provenance.items() if key in {
        "source_doc_id", "source_doc_name", "source_document_hash", "source_page", "source_sheet", "source_cell",
        "source_excerpt", "source_table_index", "source_table_row", "source_table_column", "source_column_label",
    }}
    quote_amount = _commitment_quote_amount(citation)
    if quote_amount is None or float(quote_amount.replace(",", "")) != fact["value"]:
        return None
    evidence, error = evidence_for(citation, active_documents)
    if error or len(evidence) != 1:
        return None
    return {
        "kind": "lender_commitment",
        "label": FINANCING_LABELS["lender_commitment"],
        "amount": fact["value"],
        "currency": "USD",
        "debt_phase": "construction",
        "note": "",
        "state": "checked",
        "evidence": evidence,
        "citation": citation,
        "source_path": CONSTRUCTION_LOAN_PATH,
    }


def project_financing(metrics, documents, debt_amount, construction_loan=None):
    from app.services.analysis import evidence_for

    result = {
        "debt_amount_kind": None,
        "debt_amount_label": DEBT_LABEL,
        "debt_amount_currency": None,
        "measures": [],
    }
    active_documents = [item for item in documents if item.get("included_in_review", True)]
    record = metrics.get(FINANCING_KEY)
    if record is None:
        commitment = _accepted_commitment(metrics, active_documents, construction_loan)
        if commitment:
            result["measures"].append(commitment)
    if not isinstance(record, dict) or record.get("version") != 1:
        return result

    selected_kind = record.get("debt_amount_kind")
    evidence_current = record.get("document_set") == financing_document_set(documents)
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

"""Independent arithmetic checks of quoted investor cash flows from PDF sources."""
from __future__ import annotations

import copy
import math
import re
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.services.document_versions import review_documents
from app.services.source_evidence import fresh_audit_evidence, normalized_text

CROSSCHECK_KEY = "_return_crosscheck"
_YEAR = re.compile(r"\byears?[\s\-–—]*0*(\d+)(?:\s*[-–—]\s*(\d+))?\b", re.I)
_CALENDAR_YEAR = re.compile(r"\b[12]\d{3}\b")
_INITIAL = re.compile(r"\b(?:initial (?:investment|contribution|outlay)|at inception|month 0)\b", re.I)
_MONEY = re.compile(
    r"(?<![\w.,])(?P<open>\()?\s*(?P<sign1>[-+])?\s*(?P<symbol>[$€£])?\s*"
    r"(?P<sign2>[-+])?\s*(?P<number>(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)"
    r"\s*(?P<scale>million|billion|mm|[mk])?\s*(?P<close>\))?(?![\w%]|[.,]\d)", re.I
)
_EXPLICIT_ZERO = re.compile(r"(?<!\w)[$€£]\s*[-–—](?!\s*\d)(?!\w)")
_FLOW_LABELS = {
    "unspecified": "Unspecified",
    "operating": "Operating cash flow",
    "capital_event": "Includes capital-event cash flow",
    "refinance": "Includes refinance proceeds",
    "sale": "Includes sale proceeds",
}
_EVENTS = {
    "operating": r"operating (?:cash flows?|distributions?)|cash flows? from operations",
    "capital_event": r"capital (?:event|return|contribution)|equity (?:contribution|return)|initial (?:investment|contribution|outlay)|sale proceeds|refinanc",
    "refinance": r"refinanc(?:e|ing)|cash[- ]out",
    "sale": r"\bsale\b|\bdisposition\b",
}


class PdfCitation(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)
    source_doc_id: int = Field(ge=1)
    source_page: int = Field(ge=1)
    source_excerpt: str = Field(min_length=8, max_length=6000)


class CashFlowRow(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True, allow_inf_nan=False)
    year: int = Field(ge=0, le=9999)
    amount: float = Field(ge=-1e15, le=1e15)
    citation: PdfCitation | None = None
    flow_scope: Literal["unspecified", "operating", "capital_event", "refinance", "sale"] = "unspecified"
    date_label: str | None = Field(default=None, min_length=1, max_length=100)
    event_citation: PdfCitation | None = None


class PdfCashFlowTable(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)
    citation: PdfCitation
    year_header: str = Field(min_length=4, max_length=1500)
    cash_flow_row: str = Field(min_length=4, max_length=3000)


class ReturnCrosscheckInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True, allow_inf_nan=False)
    investor_class: str = Field(min_length=1, max_length=100)
    scenario: Literal["hold", "sale"]
    basis: str = Field(default="", max_length=180)
    currency: str = Field(pattern=r"^(?:[A-Z]{3}|[$€£])$")
    scope_citation: PdfCitation | None = None
    rows: list[CashFlowRow] = Field(min_length=2, max_length=101)
    table: PdfCashFlowTable | None = None

    @model_validator(mode="after")
    def validate_years(self):
        years = [row.year for row in self.rows]
        if years != list(range(years[0], years[-1] + 1)):
            raise ValueError("Provide each cited annual period once in increasing order. Missing periods cannot be filled with assumed zero cash flow.")
        if not self.table and (not self.scope_citation or any(not row.citation for row in self.rows)):
            raise ValueError("Provide a PDF scope citation and each row citation, or a shared table citation.")
        return self


def return_crosscheck_output_schema():
    """Strict provider schema; older callers may still omit nullable/default fields."""
    def strict(value):
        if isinstance(value, list):
            return [strict(item) for item in value]
        if not isinstance(value, dict):
            return value
        result = {key: strict(child) for key, child in value.items() if key not in {"default", "title"}}
        if "properties" in result:
            result["required"] = list(result["properties"])
            result["additionalProperties"] = False
        return result
    return strict(ReturnCrosscheckInput.model_json_schema())


def _years(text):
    matches = list(_YEAR.finditer(text))
    if matches:
        values = []
        for match in matches:
            first = int(match[1])
            last = int(match[2]) if match[2] else first
            if last < first or last - first > 100:
                raise ValueError("The quoted year range is invalid.")
            values.extend(range(first, last + 1))
        return values
    return [int(match[0]) for match in _CALENDAR_YEAR.finditer(text)]


def _money(text):
    values = []
    text = text.replace("−", "-")
    zero_markers = list(_EXPLICIT_ZERO.finditer(text))
    amount_text = _EXPLICIT_ZERO.sub(lambda match: " " * len(match[0]), text)
    for match in _MONEY.finditer(amount_text):
        if bool(match["open"]) != bool(match["close"]):
            raise ValueError("The quoted cash-flow amount has unmatched parentheses.")
        signs = [match[key] for key in ("sign1", "sign2") if match[key]]
        if len(set(signs)) > 1 or (match["open"] and "+" in signs):
            raise ValueError("The quoted cash-flow sign is ambiguous.")
        scale = {"million": 1000000, "mm": 1000000, "m": 1000000, "billion": 1000000000, "k": 1000}.get((match["scale"] or "").casefold(), 1)
        amount = Decimal(match["number"].replace(",", "")) * scale
        if match["open"] or "-" in signs:
            amount = -amount
        values.append((match.start(), amount, bool(match["symbol"])))
    for match in zero_markers:
        values.append((match.start(), Decimal(0), True))
    return [(amount, symbol) for _, amount, symbol in sorted(values)]


def _row_citation(payload, row):
    return row.citation or payload.table.citation


def _scope_citation(payload):
    return payload.scope_citation or payload.table.citation


def _contains(text, label):
    return bool(re.search(r"(?<!\w)" + re.escape(normalized_text(label)) + r"(?!\w)", normalized_text(text)))


def _check_year(row, quote, *, allow_range=False):
    years = set(_years(quote))
    if row.year == 0 and _INITIAL.search(quote) and not _YEAR.search(quote):
        return
    ranges = list(_YEAR.finditer(quote))
    if allow_range and len(ranges) == 1 and ranges[0][2] and row.year in years:
        return
    if years != {row.year}:
        raise ValueError(f"Year {row.year}: cite this annual period alone or use a quoted horizontal table.")


def _row_value(row):
    quote = _YEAR.sub("", row.citation.source_excerpt)
    if row.year >= 1000 and not _YEAR.search(row.citation.source_excerpt):
        quote = re.sub(r"\b" + str(row.year) + r"\b", "", quote, count=1)
    marked = [value for value, currency in _money(quote) if currency]
    if marked:
        values = marked
    else:
        if row.date_label:
            quote = quote.replace(row.date_label, "")
        values = [value for value, _ in _money(quote)]
    if values != [Decimal(str(row.amount))]:
        raise ValueError(f"Year {row.year}: the quoted signed cash-flow amount does not match.")


def _verify_table(payload):
    table = payload.table
    excerpt = normalized_text(table.citation.source_excerpt)
    if normalized_text(table.year_header) not in excerpt or normalized_text(table.cash_flow_row) not in excerpt:
        raise ValueError("The quoted table must contain its exact year header and cash-flow row.")
    if _years(table.year_header) != [row.year for row in payload.rows]:
        raise ValueError("The table year columns must match all submitted periods in order.")
    row_text = re.sub(re.escape(payload.investor_class), "", table.cash_flow_row, flags=re.I)
    amounts = [value for value, _ in _money(row_text)]
    if amounts != [Decimal(str(row.amount)) for row in payload.rows]:
        raise ValueError("The table's signed cash-flow amounts do not match the year columns.")
    scope = _scope_citation(payload)
    local_scope = ((scope.source_doc_id, scope.source_page) == (table.citation.source_doc_id, table.citation.source_page)
                   and normalized_text(scope.source_excerpt) in excerpt)
    if not local_scope and not _contains(table.cash_flow_row, payload.investor_class):
        raise ValueError("The quoted table must identify the selected investor class.")
    if not _contains(table.cash_flow_row, payload.investor_class) and re.search(r"\b(?:gp|sponsor|project)\b", table.cash_flow_row, re.I):
        raise ValueError("The quoted cash-flow row belongs to another investor or project scope.")
    header_matches = list(_YEAR.finditer(table.year_header)) or list(_CALENDAR_YEAR.finditer(table.year_header))
    if len(header_matches) != len(payload.rows):
        raise ValueError("Provide one explicit year header for each table column.")
    for index, row in enumerate(payload.rows):
        citation = _row_citation(payload, row)
        if (citation.source_doc_id, citation.source_page) != (table.citation.source_doc_id, table.citation.source_page):
            raise ValueError("Each horizontal-table row must cite the table's PDF page.")
        row_excerpt = normalized_text(citation.source_excerpt)
        if row_excerpt not in excerpt or normalized_text(table.cash_flow_row) not in row_excerpt:
            raise ValueError("Each table citation must retain the complete quoted cash-flow row.")
        if row.date_label:
            start = header_matches[index].start()
            end = header_matches[index + 1].start() if index + 1 < len(header_matches) else len(table.year_header)
            if normalized_text(row.date_label) not in normalized_text(table.year_header[start:end]):
                raise ValueError(f"Year {row.year}: the cited date does not belong to this table column.")


def _checked_citation(citation, documents, manifest):
    document = next((document for document in documents if document.id == citation.source_doc_id), None)
    if not document or not document.filename.casefold().endswith(".pdf"):
        raise ValueError("Cash-flow cross-checks require a current PDF source.")
    stamped, issue = fresh_audit_evidence(citation.model_dump(), documents, manifest)
    if issue:
        raise ValueError(issue)
    return {"document_id": stamped["source_doc_id"], "document_name": stamped["source_doc_name"],
            "content_hash": stamped["source_document_hash"], "page": stamped["source_page"],
            "excerpt": stamped["source_excerpt"]}


def _validate_scope(payload):
    scope = _scope_citation(payload).source_excerpt
    if not _contains(scope, payload.investor_class) or not re.search(r"cash[\s-]*flows?|contributions?|distributions?", scope, re.I):
        raise ValueError("The scope quote must identify this investor class and its cash flows.")
    quotes = " ".join([scope, *(_row_citation(payload, row).source_excerpt for row in payload.rows)])
    if payload.basis and not _contains(scope, payload.basis):
        raise ValueError("The calculation basis must be stated in the scope quote.")
    currency_present = payload.currency in quotes if payload.currency in {"$", "€", "£"} else _contains(quotes, payload.currency)
    if not currency_present:
        raise ValueError("Use the currency label printed in the cited sources.")
    scenario = r"\bhold\b|\bholding\b" if payload.scenario == "hold" else r"\bsale\b|\bdisposition\b"
    if not re.search(scenario, quotes, re.I):
        raise ValueError("The cited source must identify the selected hold or sale scenario.")
    for row in payload.rows:
        citation = _row_citation(payload, row)
        scope_citation = _scope_citation(payload)
        local_scope = (citation.source_doc_id, citation.source_page) == (scope_citation.source_doc_id, scope_citation.source_page)
        another_scope = re.search(r"\b(?:gp|sponsor|project)\b|\bclass\s+[a-z0-9]+\b", citation.source_excerpt, re.I)
        if not _contains(citation.source_excerpt, payload.investor_class) and (not local_scope or another_scope):
            raise ValueError(f"Year {row.year}: the quoted row does not identify this investor cash-flow context.")
        if row.date_label and normalized_text(row.date_label) not in normalized_text(citation.source_excerpt):
            raise ValueError(f"Year {row.year}: preserve a date label printed in the cited row.")
        if row.flow_scope == "unspecified":
            continue
        event = row.event_citation or citation
        _check_year(row, event.source_excerpt, allow_range=True)
        text = event.source_excerpt
        local_event = (event.source_doc_id, event.source_page) == (citation.source_doc_id, citation.source_page)
        if not _contains(text, payload.investor_class) and (not local_event or re.search(r"\b(?:gp|sponsor|project)\b", text, re.I)):
            raise ValueError(f"Year {row.year}: the event quote does not identify this investor cash-flow context.")
        if not re.search(_EVENTS[row.flow_scope], text, re.I) or re.search(
            r"\b(?:no|without|excludes?|excluding|not)\b.{0,35}(?:" + _EVENTS[row.flow_scope] + ")", text, re.I
        ):
            raise ValueError(f"Year {row.year}: the cash-flow classification needs an explicit supporting quote.")


def _annual_irr(rows):
    nonzero = [row.amount for row in rows if row.amount]
    changes = sum(first * second < 0 for first, second in zip(nonzero, nonzero[1:]))
    if not nonzero or nonzero[0] >= 0 or nonzero[-1] <= 0 or changes != 1:
        return None
    origin = rows[0].year
    scale = max(abs(row.amount) for row in rows)
    def npv(log_rate):
        powers = [-(row.year - origin) * log_rate for row in rows]
        shift = max(powers)
        return math.fsum(row.amount / scale * math.exp(power - shift) for row, power in zip(rows, powers))
    low, high = -30.0, 30.0
    if npv(low) <= 0 or npv(high) >= 0:
        return None
    for _ in range(160):
        middle = (low + high) / 2
        if npv(middle) > 0:
            low = middle
        else:
            high = middle
    return round(math.expm1((low + high) / 2) * 100, 4)


def _calculation(payload):
    inflows = math.fsum(row.amount for row in payload.rows if row.amount > 0)
    outflows = -math.fsum(row.amount for row in payload.rows if row.amount < 0)
    irr = _annual_irr(payload.rows)
    warnings = [] if irr is not None else ["A unique annual IRR requires one negative-to-positive sign change in the cited series."]
    if not outflows:
        warnings.append("The cited series contains no investment outflow for the cash-flow multiple.")
    return {"annual_irr_pct": irr, "cash_flow_multiple": round(inflows / outflows, 6) if outflows else None,
            "calculation_basis": "Annual period IRR; cash-flow multiple equals total positive cash flows divided by total negative cash-flow magnitude.",
            "warnings": warnings}


def checked_return_crosscheck(payload, documents, manifest):
    payload = payload if isinstance(payload, ReturnCrosscheckInput) else ReturnCrosscheckInput.model_validate(payload)
    documents = review_documents(documents)
    if not documents:
        raise ValueError("Current readable PDF sources are required.")
    scope_evidence = _checked_citation(_scope_citation(payload), documents, manifest)
    _validate_scope(payload)
    if payload.table:
        table_evidence = _checked_citation(payload.table.citation, documents, manifest)
        _verify_table(payload)
    rows, evidence = [], [scope_evidence]
    for row in payload.rows:
        citation = _checked_citation(_row_citation(payload, row), documents, manifest)
        if not payload.table:
            _check_year(row, row.citation.source_excerpt)
            _row_value(row)
        event_evidence = [_checked_citation(row.event_citation, documents, manifest)] if row.event_citation else []
        row_evidence = [citation]
        if payload.table and table_evidence != citation:
            row_evidence.insert(0, table_evidence)
        rows.append({"year": row.year, "label": f"Year {row.year}", "amount": row.amount,
                     "date_label": row.date_label, "flow_scope": row.flow_scope,
                     "flow_scope_label": _FLOW_LABELS[row.flow_scope], "evidence": row_evidence, "event_evidence": event_evidence})
        evidence.extend([*row_evidence, *event_evidence])
    bindings = []
    for document_id in sorted({source["document_id"] for source in evidence}):
        source = next(source for source in manifest if source["id"] == document_id)
        bindings.append({"document_id": document_id, "filename": source["filename"],
                         "file_sha256": source.get("file_sha256"), "content_hash": source["content_hash"]})
    filename_versions = {}
    for binding in bindings:
        filename = binding["filename"].casefold()
        filename_versions[filename] = sorted({
            source.get("file_sha256") or source["content_hash"] for source in manifest
            if source["filename"].casefold() == filename
            and source.get("included_in_review", source.get("source_role", "active") == "active")
        })
    from app.services.analysis import digest
    result = {"status": "current", "stale_reasons": [], "investor_class": payload.investor_class, "scenario": payload.scenario,
              "basis": payload.basis, "currency": payload.currency, "rows": rows,
              "evidence": list({(source["document_id"], source["page"], source["excerpt"]): source for source in evidence}.values()),
              **_calculation(payload)}
    return {"version": 1, "input": payload.model_dump(), "input_hash": digest(payload.model_dump()),
            "bindings": bindings, "filename_versions": filename_versions, "result": result}


def project_return_crosscheck(metrics, manifest):
    record = (metrics or {}).get(CROSSCHECK_KEY)
    if not isinstance(record, dict) or record.get("version") != 1:
        return None
    from app.services.analysis import digest
    try:
        payload = ReturnCrosscheckInput.model_validate(record["input"])
        if record["input_hash"] != digest(payload.model_dump()):
            return None
        result = copy.deepcopy(record["result"])
        if any(result.get(key) != getattr(payload, key) for key in ("investor_class", "scenario", "basis", "currency")):
            return None
        if len(result["rows"]) != len(payload.rows) or not record["bindings"]:
            return None
        for saved, row in zip(result["rows"], payload.rows):
            if any(saved.get(key) != getattr(row, key) for key in ("year", "amount", "date_label", "flow_scope")):
                return None
        citations = [_scope_citation(payload), *(_row_citation(payload, row) for row in payload.rows)]
        citations.extend(row.event_citation for row in payload.rows if row.event_citation)
        if payload.table:
            citations.append(payload.table.citation)
        if {citation.source_doc_id for citation in citations} != {binding["document_id"] for binding in record["bindings"]}:
            return None
        result.update(_calculation(payload))
        current = [source for source in manifest if source.get("included_in_review", source.get("source_role", "active") == "active")]
        stale_reasons = []
        for binding in record["bindings"]:
            source = next((source for source in current if source["id"] == binding["document_id"]), None)
            if not source:
                stale_reasons.append("cited_source_unavailable")
            elif binding.get("file_sha256") and source.get("file_sha256"):
                if source["file_sha256"] != binding["file_sha256"]:
                    stale_reasons.append("cited_pdf_changed")
            elif source["content_hash"] != binding["content_hash"]:
                stale_reasons.append("cited_pdf_changed")
            known_versions = record["filename_versions"][binding["filename"].casefold()]
            for other in current:
                if other["filename"].casefold() == binding["filename"].casefold():
                    if (other.get("file_sha256") or other["content_hash"]) not in known_versions:
                        stale_reasons.append("active_filename_version_added")
        if stale_reasons:
            result["status"] = "needs_review"
            result["stale_reasons"] = list(dict.fromkeys(stale_reasons))
            result["previous_calculation"] = {key: result.get(key) for key in ("annual_irr_pct", "cash_flow_multiple")}
            result.update(annual_irr_pct=None, cash_flow_multiple=None)
            result["warnings"] = [*result.get("warnings", []), "A cited PDF version changed or is no longer active. Recheck this calculation against current sources."]
        return result
    except (KeyError, TypeError, ValueError, ValidationError):
        return None

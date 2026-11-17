"""Source-checked cash-on-cash projections by year for a hold strategy."""
from __future__ import annotations

import math
import re

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.services.source_evidence import fresh_audit_evidence, normalized_text

SCHEDULE_KEY = "_return_schedule"
_YEAR = re.compile(r"\byear[\s\-–—]*0*(\d+)\b", re.I)
_PERCENT = re.compile(r"(?<![\d.])([+-]?\d+(?:\.\d+)?)\s*%")
_UNAVAILABLE = re.compile(r"(?<!\w)(?:n/?a|not available|not applicable)(?!\w)", re.I)


class ReturnScheduleRow(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, allow_inf_nan=False, strict=True)

    year: int = Field(ge=1, le=50)
    cash_on_cash_pct: float | None = Field(ge=-1000, le=1000)
    note: str = Field(default="", max_length=300)
    source_excerpt: str = Field(min_length=8, max_length=1500)
    source_cell: str | None = Field(default=None, pattern=r"^[A-Za-z]{1,3}[1-9]\d*$")

    @model_validator(mode="after")
    def validate_unavailable(self):
        if self.cash_on_cash_pct is None and not self.note:
            raise ValueError("Explain why the source marks this year's return as unavailable.")
        return self


class ReturnScheduleInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, strict=True)

    investor_class: str = Field(min_length=1, max_length=100)
    equity_basis: str = Field(min_length=1, max_length=180)
    period_basis: str = Field(min_length=1, max_length=180)
    assumptions: str = Field(default="", max_length=1000)
    source_doc_id: int = Field(ge=1)
    source_page: int | None = Field(default=None, ge=1)
    source_sheet: str | None = Field(default=None, min_length=1, max_length=128)
    rows: list[ReturnScheduleRow] = Field(min_length=1, max_length=50)

    @model_validator(mode="after")
    def validate_schedule(self):
        if (self.source_page is None) == (self.source_sheet is None):
            raise ValueError("Choose a PDF page or a workbook sheet for the schedule.")
        if any(bool(row.source_cell) != bool(self.source_sheet) for row in self.rows):
            raise ValueError("Workbook schedule rows need a value cell. PDF rows use the page alone.")
        years = [row.year for row in self.rows]
        if years != sorted(set(years)):
            raise ValueError("Provide one row per year in ascending order.")
        if all(row.cash_on_cash_pct is None for row in self.rows):
            raise ValueError("Include at least one sourced annual return.")
        return self


def active_sources_fingerprint(documents):
    from app.services.analysis import digest

    return digest([(doc["id"], doc["content_hash"]) for doc in documents
                   if doc.get("included_in_review", doc.get("source_role", "active") == "active")])


def _value_matches_quote(row: ReturnScheduleRow):
    quote = normalized_text(row.source_excerpt).replace("−", "-")
    if {int(year) for year in _YEAR.findall(quote)} != {row.year}:
        raise ValueError(f"Year {row.year}: cite text from this year alone, including its year label.")

    if row.source_cell:
        # Inspect only the cited value cell, not neighboring percentages or the year label.
        cell = re.search(rf"(?<!\w){re.escape(row.source_cell.casefold())}\s*=\s*([^|]*)", quote)
        quote = cell[1].strip() if cell else ""

    value = row.cash_on_cash_pct
    if value is None:
        matches = bool(_UNAVAILABLE.search(quote))
    else:
        candidates = [float(number) for number in _PERCENT.findall(quote)]
        if row.source_cell and re.fullmatch(r"[+-]?\d+(?:\.\d+)?(?:e[+-]?\d+)?", quote):
            candidates.append(float(quote) * 100)
        matches = any(math.isclose(value, number, rel_tol=0, abs_tol=1e-9) for number in candidates)
    if not matches:
        raise ValueError(f"Year {row.year}: the quote needs the recorded return or an explicit unavailable value.")


def checked_return_schedule(schedule: ReturnScheduleInput, documents, manifest):
    """Validate the analyst's citations before storing a reviewed schedule."""
    active = next((doc for doc in manifest if doc["id"] == schedule.source_doc_id
                   and doc.get("included_in_review", doc.get("source_role", "active") == "active")), None)
    if not active:
        raise ValueError("Choose a current source from this deal's documents.")
    record = schedule.model_dump()
    locator = {key: record[key] for key in ("source_doc_id", "source_page", "source_sheet")}
    citation = None
    for row in schedule.rows:
        citation, issue = fresh_audit_evidence(
            {**locator, "source_cell": row.source_cell, "source_excerpt": row.source_excerpt}, documents, manifest,
        )
        if issue:
            raise ValueError(f"Year {row.year}: {issue}")
        _value_matches_quote(row)
    return {"schedule": record, "source_document_hash": citation["source_document_hash"],
            "review_document_set": active_sources_fingerprint(manifest)}


def project_return_schedule(metrics, documents):
    """Expose only schedules whose reviewed source package remains current."""
    from app.services.analysis import evidence_for

    record = metrics.get(SCHEDULE_KEY)
    if not isinstance(record, dict) or record.get("review_document_set") != active_sources_fingerprint(documents):
        return None
    if not record.get("source_document_hash"):
        return None
    try:
        schedule = ReturnScheduleInput.model_validate(record.get("schedule"))
    except ValidationError:
        return None
    first_row = schedule.rows[0]
    evidence, issue = evidence_for({
        "source_doc_id": schedule.source_doc_id, "source_document_hash": record["source_document_hash"],
        "source_page": schedule.source_page, "source_sheet": schedule.source_sheet,
        "source_cell": first_row.source_cell, "source_excerpt": first_row.source_excerpt,
    }, documents)
    if issue:
        return None
    return {**schedule.model_dump(exclude={"source_doc_id", "source_page", "source_sheet"}), "evidence": evidence}

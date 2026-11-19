"""Validate an explicitly reviewed set of page locators against an uploaded PDF."""
from __future__ import annotations

import asyncio
import re
import unicodedata
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select

from app.database import async_session
from app.models import Deal
from app.services.analysis import digest
from app.services.document_context import sha256_file, split_text_pages
from app.services.document_versions import review_documents
from app.services.review_drafts import DIMENSIONS, FIELDS, ReviewFact, ReviewResult, load_documents, package_identity
from app.services.review_findings import FindingCitation, SourceFinding
from app.services.return_crosscheck import PdfCitation, ReturnCrosscheckInput, _money, _years
from scripts.review_backfill import BackfillPlan, execute_plan
from scripts.verify_review_surfaces import verify_review_surfaces

PATTERNS = {
    "money": re.compile(r"\$\s*([\d,]+(?:\.\d+)?)"),
    "number": re.compile(r"(?<![\w.])([\d,]+(?:\.\d+)?)"),
    "percent": re.compile(r"(?<![\w.])([\d,]+(?:\.\d+)?)\s*%"),
    "multiple": re.compile(r"(?<![\w.])([\d,]+(?:\.\d+)?)\s*[×xX](?!\w)"),
}
MONTH = re.compile(r"\b(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|"
                   r"sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\b(?:\s+[12]\d{3})?", re.I)
TABLE_MONEY = re.compile(
    r"[\s|]*(?:[(]?\s*[-+−]?\s*[$€£]\s*[(]?\s*[-+−]?\s*[0-9][\d,]*(?:\.\d+)?\s*[)]?"
    r"|[$€£]\s*[-–—](?=\s|\||$))"
)


class SourceReplayBlocked(ValueError):
    """Only structural errors are safe to show in job logs."""


class Locator(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    path: str = Field(max_length=100)
    page: int = Field(gt=0)
    anchor: str = Field(min_length=3, max_length=75)
    kind: Literal["money", "number", "percent", "multiple", "anchor", "sale"]
    index: int = Field(default=0, ge=0, le=8)
    window: int = Field(default=120, ge=8, le=240)
    context: dict[str, str] = Field(default_factory=dict)


class QuoteSelection(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    page: int = Field(gt=0)
    anchor: str = Field(min_length=3, max_length=100)
    through: Literal["anchor", "number", "money", "percent", "multiple", "month"] = "anchor"
    index: int = Field(default=0, ge=0, le=12)
    window: int = Field(default=100, ge=8, le=320)


class FindingSelection(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    kind: Literal["conflict", "source_note"]
    title: str = Field(min_length=5, max_length=100)
    detail: str = Field(min_length=12, max_length=500)
    quotes: list[QuoteSelection] = Field(min_length=1, max_length=4)


class EventSelection(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    flow_scope: Literal["refinance", "sale", "operating", "capital_event"]
    quote: QuoteSelection


class CashFlowSelection(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    page: int = Field(gt=0)
    section: str = Field(min_length=4, max_length=100)
    header: str = Field(min_length=3, max_length=80)
    row: str = Field(min_length=5, max_length=100)
    investor_class: str = Field(min_length=3, max_length=100)
    currency: str = Field(pattern=r"^(?:[A-Z]{3}|[$€£])$")
    scenario: Literal["hold", "sale"]
    events: list[EventSelection] = Field(default_factory=list, max_length=12)


class ReplayRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    mode: Literal["validate", "apply", "verify"] = "validate"
    deal_id: int = Field(gt=0)
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    locators: list[Locator] = Field(default_factory=list, max_length=80)
    findings: list[FindingSelection] = Field(default_factory=list, max_length=10)
    cash_flow_check: CashFlowSelection | None = None
    compare_ids: list[int] = Field(default_factory=list, max_length=8)
    rehearse_recovery: bool = False
    expected_revision: int | None = Field(default=None, gt=0)
    preview_digest: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def check_scope(self):
        paths = [row.path for row in self.locators]
        if len(paths) != len(set(paths)):
            raise ValueError("Select one locator per fact.")
        if self.mode in {"validate", "apply"} and not (paths or self.findings or self.cash_flow_check):
            raise ValueError("Select source locators to review.")
        if self.mode == "apply" and (not self.expected_revision or not self.preview_digest):
            raise ValueError("Apply requires the exact preview and revision.")
        if self.mode == "verify" and not self.compare_ids:
            raise ValueError("Select at least one existing comparison deal.")
        if self.rehearse_recovery and self.mode != "verify":
            raise ValueError("Rehearse recovery during a read-only verification.")
        if any(set(row.context) - set(DIMENSIONS) for row in self.locators):
            raise ValueError("Invalid source context dimension.")
        return self


class ReplayBatch(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    requests: list[ReplayRequest] = Field(min_length=1, max_length=5)


def _normalized(text):
    return " ".join(unicodedata.normalize("NFKC", text).split())


def quote_from_selection(pages, source_id, selection):
    text = _normalized(pages.get(selection.page, ""))
    anchor = _normalized(selection.anchor)
    start = text.casefold().find(anchor.casefold())
    if start == -1:
        raise SourceReplayBlocked(f"Page {selection.page} did not contain a selected citation anchor.")
    end = start + len(anchor)
    if selection.through != "anchor":
        pattern = MONTH if selection.through == "month" else PATTERNS[selection.through]
        matches = list(pattern.finditer(text[end:end + selection.window]))
        if len(matches) <= selection.index:
            raise SourceReplayBlocked(f"Page {selection.page} did not contain a value for the selected citation.")
        end += matches[selection.index].end()
    return {"source_doc_id": source_id, "source_page": selection.page, "source_excerpt": text[start:end]}


def crosscheck_from_selection(pages, source_id, selection):
    page = _normalized(pages.get(selection.page, ""))
    lower = page.casefold()
    section = lower.find(_normalized(selection.section).casefold())
    header = lower.find(_normalized(selection.header).casefold(), section + len(selection.section)) if section >= 0 else -1
    row = lower.find(_normalized(selection.row).casefold(), header + len(selection.header)) if header >= 0 else -1
    if min(section, header, row) < 0 or row - section > 900:
        raise SourceReplayBlocked("The selected cash-flow table header and row were not found together.")
    labels = page[header:row].strip()
    years = _years(labels)
    if not 2 <= len(years) <= 30:
        raise SourceReplayBlocked("The selected cash-flow table has no bounded sequence of annual columns.")
    end = row + len(_normalized(selection.row))
    amounts = []
    for _ in years:
        token = TABLE_MONEY.match(page, end)
        if not token:
            raise SourceReplayBlocked("A selected cash-flow column has no explicit monetary amount.")
        parsed = _money(token.group())
        if len(parsed) != 1:
            raise SourceReplayBlocked("A selected cash-flow column has an ambiguous monetary amount.")
        amounts.append(float(parsed[0][0]))
        end = token.end()
    row_text = page[row:end].strip()
    table = PdfCitation(source_doc_id=source_id, source_page=selection.page, source_excerpt=page[section:end].strip())
    events = {}
    for event in selection.events:
        citation = quote_from_selection(pages, source_id, event.quote)
        event_year = _years(citation["source_excerpt"])
        if len(event_year) != 1 or event_year[0] not in years or event_year[0] in events:
            raise SourceReplayBlocked("An event citation did not identify a unique cash-flow year.")
        events[event_year[0]] = {"flow_scope": event.flow_scope, "event_citation": citation}
    return ReturnCrosscheckInput.model_validate({
        "investor_class": selection.investor_class, "scenario": selection.scenario, "currency": selection.currency,
        "table": {"citation": table.model_dump(), "year_header": labels, "cash_flow_row": row_text},
        "rows": [{"year": year, "amount": amount, **events.get(year, {})} for year, amount in zip(years, amounts)],
    })


def fact_from_locator(pages, source_id, row):
    if row.path not in FIELDS:
        raise SourceReplayBlocked(f"Unknown reviewed field: {row.path}")
    text = " ".join(unicodedata.normalize("NFKC", pages.get(row.page, "")).split())
    anchor = " ".join(unicodedata.normalize("NFKC", row.anchor).split())
    start = text.casefold().find(anchor.casefold())
    if start == -1:
        raise SourceReplayBlocked(f"Page {row.page} did not contain the anchor for {row.path}.")
    tail_start = start + len(anchor)
    if row.kind in {"anchor", "sale"}:
        value = text[start:tail_start] if row.kind == "anchor" else "sale"
        quote = text[start:tail_start]
    else:
        following = text[tail_start:tail_start + row.window]
        captures = list(PATTERNS[row.kind].finditer(following))
        if len(captures) <= row.index:
            raise SourceReplayBlocked(f"Page {row.page} did not give a value for {row.path}.")
        chosen = captures[row.index]
        value = float(chosen[1].replace(",", ""))
        quote = text[start:tail_start + chosen.end()]
    return ReviewFact(path=row.path, value=value, source_doc_id=source_id, source_page=row.page,
                      source_excerpt=quote, **row.context)


async def replay_source(request, *, engine):
    async with async_session() as db:
        deal = await db.get(Deal, request.deal_id)
        if not deal or deal.deleted_at:
            raise SourceReplayBlocked("The selected deal is unavailable.")
        docs = await load_documents(db, deal.id)
        active = review_documents(docs)
        matches = [doc for doc in active if doc.file_path and sha256_file(doc.file_path) == request.source_sha256]
        if len(matches) != 1 or not matches[0].extracted_text:
            raise SourceReplayBlocked("The exact uploaded PDF was not readable in the selected deal.")
        source = matches[0]
        if request.mode == "verify":
            ids = [request.deal_id] + [d for d in request.compare_ids if d != request.deal_id]
            deals = {item.id: item for item in (await db.execute(
                select(Deal).where(Deal.id.in_(ids), Deal.deleted_at.is_(None))
            )).scalars().all()}
            if len(deals) != len(ids):
                raise SourceReplayBlocked("A comparison deal is unavailable.")
            surfaces = await verify_review_surfaces(db, [deals[i] for i in ids], audit_scores=True)
            result = {"status": "verified", "surfaces": surfaces}
            if request.rehearse_recovery:
                from app.routers.deal_uploads import UPLOAD_DIR
                from scripts.recovery_rehearsal import RecoveryRehearsalBlocked, rehearse_recovery

                try:
                    result["recovery"] = await asyncio.to_thread(rehearse_recovery, engine.url.database, UPLOAD_DIR)
                except RecoveryRehearsalBlocked as exc:
                    reason = str(exc)
                    result["recovery"] = {"status": "blocked", "reason": reason if re.fullmatch(r"[a-z_]+", reason) else "rehearsal_blocked"}
            return result
        revision = deal.revision
        if request.expected_revision and revision != request.expected_revision:
            raise SourceReplayBlocked("The selected deal changed since the preview.")
        package = package_identity(deal, docs)
        pages = dict(split_text_pages(source.extracted_text))
        facts, issues = [], []
        for row in request.locators:
            try:
                facts.append(fact_from_locator(pages, source.id, row))
            except (ValueError, TypeError):
                issues.append({"path": row.path, "page": row.page})
        if issues:
            return {"status": "locator_issues", "deal_id": deal.id, "source_id": source.id,
                    "readable_pages": len(pages), "active_documents": len(active), "issues": issues}
        hold = next((fact.value for fact in facts if fact.path == "deal_structure.hold_period_years"), None)
        if any(fact.period == "offering_target_hold" for fact in facts):
            if not isinstance(hold, (int, float)):
                raise SourceReplayBlocked("The target holding period was not verified.")
            facts = [fact.model_copy(update={"period": f"{hold:g}-year target hold"})
                     if fact.period == "offering_target_hold" else fact for fact in facts]
        findings = [
            SourceFinding(kind=item.kind, title=item.title, detail=item.detail,
                          citations=[FindingCitation.model_validate(quote_from_selection(pages, source.id, quote))
                                     for quote in item.quotes])
            for item in request.findings
        ]
        crosscheck = crosscheck_from_selection(pages, source.id, request.cash_flow_check) if request.cash_flow_check else None
        review = ReviewResult(package_id=package, facts=facts, findings=findings, return_crosscheck=crosscheck)
        preview_digest = digest({"revision": revision, "review": review.model_dump()})
        if request.mode == "apply" and request.preview_digest != preview_digest:
            raise SourceReplayBlocked("The source-selected facts differ from the approved preview.")
        plan = BackfillPlan.model_validate({"version": 1, "deals": [{
            "deal_id": deal.id, "expected_revision": revision, "package_id": package,
            "review": review.model_dump(), "approve_paths": [fact.path for fact in facts],
            "approve_findings": bool(findings), "approve_return_crosscheck": crosscheck is not None,
        }]})
        report = {"deal_id": deal.id, "revision": revision, "source_id": source.id,
                  "readable_pages": len(pages), "active_documents": len(active),
                  "preview_digest": preview_digest, "selected": len(facts), "selected_findings": len(findings),
                  "selected_cashflow_periods": len(crosscheck.rows) if crosscheck else 0, "property_type": deal.property_type}
        if request.mode == "validate":
            report["numeric_values"] = {fact.path: fact.value for fact in facts if not isinstance(fact.value, str)}
    result = await execute_plan(plan, engine=engine, apply=request.mode == "apply")
    summary = result["deals"][0]
    return {**report, "status": result["status"], "saved_revision": summary["revision"],
            "analysis": summary.get("analysis")}

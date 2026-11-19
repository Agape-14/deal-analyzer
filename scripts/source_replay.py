"""Validate an explicitly reviewed set of page locators against an uploaded PDF."""
from __future__ import annotations

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
from scripts.review_backfill import BackfillPlan, execute_plan
from scripts.verify_review_surfaces import verify_review_surfaces

PATTERNS = {
    "money": re.compile(r"\$\s*([\d,]+(?:\.\d+)?)"),
    "number": re.compile(r"(?<![\w.])([\d,]+(?:\.\d+)?)"),
    "percent": re.compile(r"(?<![\w.])([\d,]+(?:\.\d+)?)\s*%"),
    "multiple": re.compile(r"(?<![\w.])([\d,]+(?:\.\d+)?)\s*[×xX](?!\w)"),
}


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


class ReplayRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    mode: Literal["validate", "apply", "verify"] = "validate"
    deal_id: int = Field(gt=0)
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    locators: list[Locator] = Field(default_factory=list, max_length=80)
    compare_ids: list[int] = Field(default_factory=list, max_length=8)
    expected_revision: int | None = Field(default=None, gt=0)
    preview_digest: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def check_scope(self):
        paths = [row.path for row in self.locators]
        if len(paths) != len(set(paths)):
            raise ValueError("Select one locator per fact.")
        if self.mode in {"validate", "apply"} and not paths:
            raise ValueError("Select source locators to review.")
        if self.mode == "apply" and (not self.expected_revision or not self.preview_digest):
            raise ValueError("Apply requires the exact preview and revision.")
        if self.mode == "verify" and not self.compare_ids:
            raise ValueError("Select at least one existing comparison deal.")
        if any(set(row.context) - set(DIMENSIONS) for row in self.locators):
            raise ValueError("Invalid source context dimension.")
        return self


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
            return {"status": "verified", "surfaces": surfaces}
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
        review = ReviewResult(package_id=package, facts=facts)
        preview_digest = digest({"revision": revision, "review": review.model_dump()})
        if request.mode == "apply" and request.preview_digest != preview_digest:
            raise SourceReplayBlocked("The source-selected facts differ from the approved preview.")
        plan = BackfillPlan.model_validate({"version": 1, "deals": [{
            "deal_id": deal.id, "expected_revision": revision, "package_id": package,
            "review": review.model_dump(), "approve_paths": [fact.path for fact in facts],
        }]})
        report = {"deal_id": deal.id, "revision": revision, "source_id": source.id,
                  "readable_pages": len(pages), "active_documents": len(active),
                  "preview_digest": preview_digest, "selected": len(facts), "property_type": deal.property_type}
        if request.mode == "validate":
            report["numeric_values"] = {fact.path: fact.value for fact in facts if not isinstance(fact.value, str)}
    result = await execute_plan(plan, engine=engine, apply=request.mode == "apply")
    summary = result["deals"][0]
    return {**report, "status": result["status"], "saved_revision": summary["revision"],
            "analysis": summary.get("analysis")}

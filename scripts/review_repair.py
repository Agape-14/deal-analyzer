"""Resolve selected saved review rows and verify restored returns on the service."""

from __future__ import annotations

import copy
from pathlib import Path
from types import SimpleNamespace
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select

from app.database import async_session
from app.models import Deal, DealDocument, ReviewJob
from app.routers.deal_uploads import reprocess_document
from app.routers.field_edits import _append_field_history, _refresh_integrity
from app.services.analysis import ACCEPTED, build_analysis, digest, flatten, valid_number
from app.services.analysis_store import document_manifest
from app.services.data_integrity import is_path_locked, mark_manual_edit
from app.services.document_context import sha256_file
from app.services.document_versions import file_hash, review_documents
from app.services.return_revalidation import revalidate_same_file_returns
from app.services.review_drafts import (
    DRAFT_KEY, FIELDS, ReviewResult, apply_rows, draft_record, load_documents, package_identity, validate_rows,
)
from scripts.verify_review_surfaces import verify_review_surfaces


class RepairSelector(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    path: Literal["deal_structure.ltv", "financial_projections.stabilized_noi",
                  "target_returns.sale_scenario.sale_irr", "target_returns.sale_scenario.sale_equity_multiple"]
    source_doc_id: int = Field(gt=0)
    source_page: int = Field(gt=0)


class RepairDeal(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    deal_id: int = Field(gt=0)
    expected_revision: int = Field(gt=0)
    package_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    fields: list[RepairSelector] = Field(default_factory=list, max_length=4)
    return_schedule_rows: int = Field(default=0, ge=0, le=50)
    scoped_return_path: str | None = Field(default=None, max_length=100)

    @model_validator(mode="after")
    def unique_fields(self):
        if len({field.path for field in self.fields}) != len(self.fields):
            raise ValueError("Choose each repair field once.")
        return self


class RepairRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    mode: Literal["validate", "apply"] = "validate"
    deals: list[RepairDeal] = Field(min_length=2, max_length=8)
    preview_digest: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def check_request(self):
        if len({deal.deal_id for deal in self.deals}) != len(self.deals):
            raise ValueError("Choose each deal once.")
        if (self.mode == "apply") != bool(self.preview_digest):
            raise ValueError("Apply requires the preview digest.")
        return self


class RepairBlocked(ValueError):
    """Safe reason for rolling back a scoped repair."""


def _repair_review_rows(deal, docs, item):
    metrics = copy.deepcopy(deal.metrics or {})
    record = metrics.get(DRAFT_KEY)
    if not isinstance(record, dict):
        raise RepairBlocked(f"Deal {deal.id} has no saved review draft.")
    review = ReviewResult.model_validate(record["result"])
    if review.package_id != item.package_id:
        raise RepairBlocked(f"Deal {deal.id} has a stale review draft.")
    original = flatten(metrics)
    selected = {selector.path: selector for selector in item.fields}
    facts = [fact for fact in review.facts if fact.path in selected]
    if len(facts) != len(selected) or {fact.path for fact in facts} != set(selected):
        raise RepairBlocked(f"Deal {deal.id} needs one saved candidate per selected field.")
    for fact in facts:
        selector = selected[fact.path]
        previous = original[fact.path]
        if (fact.source_doc_id, fact.source_page) != (selector.source_doc_id, selector.source_page):
            raise RepairBlocked(f"The reviewed source changed for {fact.path}.")
        if ".sale_scenario." in fact.path:
            if len(previous) <= 1:
                raise RepairBlocked(f"The expected alias conflict changed for {fact.path}.")
        else:
            old = valid_number(fact.path, previous[0], FIELDS[fact.path][0]) if len(previous) == 1 else None
            if old is None or old == fact.value or not is_path_locked(metrics, fact.path):
                raise RepairBlocked(f"The expected locked value changed for {fact.path}.")
        # Resolve the saved aliases on a copy and keep their prior values in
        # history. The normal draft validator still checks the current citation.
        mark_manual_edit(metrics, fact.path, fact.value, lock=True)
        metrics["_provenance"][fact.path]["verification_note"] = (
            "Resolved using the current source quote and its financing or return context."
        )
        metrics.setdefault("_fact_context", {}).pop(fact.path, None)
        _append_field_history(metrics, fact.path, previous if len(previous) > 1 else previous[0],
                              fact.value, "source_conflict_resolved")
    shadow = SimpleNamespace(metrics=metrics)
    rows = validate_rows(shadow, docs, review.model_copy(update={"facts": facts}))
    for row in rows:
        if row["issue"]:
            raise RepairBlocked(f'{row["path"]}: {row["issue"]}')
        metrics["_fact_context"][row["path"]] = row["context"]
    metrics = apply_rows(shadow, docs, rows)
    remaining = [fact for fact in review.facts if fact.path not in selected]
    if remaining or review.coverage or review.findings or review.return_crosscheck:
        updated = review.model_copy(update={
            "facts": remaining, "package_id": package_identity(SimpleNamespace(
                id=deal.id, property_type=deal.property_type, metrics=metrics), docs),
        })
        metrics[DRAFT_KEY] = draft_record(updated, record["provider"], record.get("usage"))
    return metrics


def _shown_values(analysis):
    return {
        "returns": analysis["returns"],
        "schedule": analysis.get("return_schedule"),
        "facts": {path: [fact["value"], fact["identity"]] for path, fact in analysis["facts"].items()
                  if fact["state"] in ACCEPTED},
    }


def _project(deal, docs, item):
    analysis = build_analysis(deal.metrics or {}, document_manifest(docs), deal.property_type)
    if item.return_schedule_rows and len((analysis.get("return_schedule") or {}).get("rows", [])) != item.return_schedule_rows:
        raise RepairBlocked(f"Deal {deal.id} could not revalidate the saved hold schedule.")
    if item.scoped_return_path:
        fact = analysis["facts"].get(item.scoped_return_path)
        if (not fact or analysis["returns"].get("cash_on_cash_path") != item.scoped_return_path
                or any(fact["identity"].get(key) in (None, "", "unspecified")
                       for key in ("investor_class", "basis", "period"))):
            raise RepairBlocked(f"Deal {deal.id} could not revalidate the saved cash return context.")
    for selector in item.fields:
        fact = analysis["facts"].get(selector.path)
        if not fact or fact["state"] not in ACCEPTED or not fact["evidence"]:
            raise RepairBlocked(f"{selector.path} did not reach the accepted analysis with its citation.")
    return analysis


async def _lock_deals(db, ids):
    deals = (await db.execute(select(Deal).where(Deal.id.in_(ids), Deal.deleted_at.is_(None))
                             .order_by(Deal.id).with_for_update())).scalars().all()
    await db.execute(select(DealDocument.id).where(DealDocument.deal_id.in_(ids)).with_for_update())
    jobs = (await db.execute(select(ReviewJob.status).where(ReviewJob.deal_id.in_(ids)).with_for_update())).scalars()
    if any(status in {"queued", "running"} for status in jobs):
        raise RepairBlocked("A target deal already has an active review.")
    if len(deals) != len(ids):
        raise RepairBlocked("A target deal is unavailable.")
    return {deal.id: deal for deal in deals}


async def execute_repair(request: RepairRequest, *, engine):
    apply = request.mode == "apply"
    report = {"mode": request.mode, "status": "pending", "deals": []}
    if engine.url.get_backend_name() == "sqlite" and not Path(engine.url.database or "").is_file():
        raise RepairBlocked("The existing database is unavailable.")
    async with engine.connect() as connection:
        if connection.dialect.name == "sqlite":
            await connection.exec_driver_sql("BEGIN IMMEDIATE")
        else:
            await connection.begin()
        try:
            async with async_session(bind=connection, join_transaction_mode="create_savepoint") as db:
                deals = await _lock_deals(db, [item.deal_id for item in request.deals])
                targets = []
                for item in request.deals:
                    deal = deals[item.deal_id]
                    docs = await load_documents(db, deal.id)
                    if deal.revision != item.expected_revision or package_identity(deal, docs) != item.package_id:
                        raise RepairBlocked(f"Deal {deal.id} changed after preparation.")
                    for doc in review_documents(docs):
                        actual_hash = sha256_file(doc.file_path) if doc.file_path else ""
                        if not actual_hash or actual_hash != file_hash(doc):
                            raise RepairBlocked(f"Source {doc.id} did not match its saved file hash.")
                    targets.append((item, deal, docs))

                outcomes = {}
                for item, deal, docs in targets:
                    if item.fields:
                        _refresh_integrity(deal, _repair_review_rows(deal, docs, item))
                    if item.return_schedule_rows or item.scoped_return_path:
                        await revalidate_same_file_returns(db, deal, docs)
                    await db.commit()
                    await db.refresh(deal)
                    analysis = _project(deal, docs, item)
                    outcomes[deal.id] = _shown_values(analysis)
                    report["deals"].append({
                        "deal_id": deal.id, "revision": deal.revision, "resolved": len(item.fields),
                        "schedule_rows": len((analysis.get("return_schedule") or {}).get("rows", [])),
                        "scoped_return": bool(item.scoped_return_path),
                    })
                if not apply:
                    for item, deal, docs in targets:
                        for doc in review_documents(docs):
                            await reprocess_document(doc.id, db)
                        await db.refresh(deal)
                        refreshed = await load_documents(db, deal.id)
                        if outcomes[deal.id] != _shown_values(_project(deal, refreshed, item)):
                            raise RepairBlocked(f"Reprocessing the same files changed displayed values for deal {deal.id}.")
                    report["same_file_refresh"] = True
                report["surfaces"] = await verify_review_surfaces(db, list(deals.values()))
                operation_digest = digest({"selection": [item.model_dump() for item in request.deals], "outcomes": outcomes})
                if apply and operation_digest != request.preview_digest:
                    raise RepairBlocked("The production outcome differs from the verified preview.")
                report["preview_digest"] = operation_digest
            if apply:
                await connection.commit()
                report["status"] = "applied"
            else:
                await connection.rollback()
                report["status"] = "validated"
            return report
        except BaseException:
            await connection.rollback()
            raise

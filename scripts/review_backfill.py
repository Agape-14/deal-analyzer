"""Validate or apply a private review plan against the configured service DB.

Run from the repository root with python -m scripts.review_backfill --plan -.
Read JSON from stdin or --plan FILE. The default runs every save path inside
a transaction and rolls it back. Add --apply to persist a validated batch.
The plan contains version=1 and deals with deal_id, expected_revision,
package_id, and the desired review, approve_paths, financing, return_reviews,
or return_schedule payloads. Operation payloads omit expected_revision.
"""
from __future__ import annotations

import argparse
import asyncio
import copy
import json
from pathlib import Path
import sys
from typing import Annotated, Literal

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError, model_validator
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.database import async_session
from app.models import Deal, DealDocument, ReviewJob
from app.routers.analysis import ScopedReturn, WithheldReturn, review_return
from app.routers.deal_uploads import reprocess_document
from app.routers.financing_measures import FinancingUpdate, save_financing_measures
from app.routers.return_schedules import ReturnScheduleUpdate, save_return_schedule
from app.routers.review_drafts import ReviewApproval, approve_draft
from app.services.analysis import analysis_for_deal, build_analysis, digest, effective_scores, return_review_binding
from app.services.analysis_store import document_manifest
from app.services.canonical_metrics import get_path
from app.services.document_context import documents_fingerprint, sha256_file
from app.services.document_versions import file_hash, review_documents
from app.services.financial_presentation import optional_sale_returns
from app.services.review_drafts import (
    DRAFT_KEY, ReviewResult, draft_record, load_documents, package_identity, validate_rows,
)
from app.services.return_schedules import active_sources_fingerprint


RECEIPT_KEY = "_review_backfill_receipts"
RETURN_REVIEW = TypeAdapter(Annotated[ScopedReturn | WithheldReturn, Field(discriminator="action")])


class SourceRefresh(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    document_id: int = Field(gt=0)
    expected_file_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class DealPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    deal_id: int = Field(gt=0)
    expected_revision: int = Field(ge=1)
    package_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    refresh_sources: list[SourceRefresh] = Field(default_factory=list)
    rebind_after_refresh: bool = False
    review: ReviewResult | None = None
    approve_paths: list[str] = Field(default_factory=list)
    financing: dict | None = None
    return_reviews: list[dict] = Field(default_factory=list)
    return_schedule: dict | None = None

    @model_validator(mode="after")
    def explicit_selection(self):
        if len(self.approve_paths) != len(set(self.approve_paths)):
            raise ValueError("List each approved fact path once.")
        if self.review is None and self.approve_paths:
            raise ValueError("Approved fact paths need a review result.")
        if self.review is not None:
            if self.review.package_id != self.package_id:
                raise ValueError("The review and deal package IDs must agree.")
            if not self.approve_paths:
                raise ValueError("Select the review facts to approve explicitly.")
            if not set(self.approve_paths).issubset({fact.path for fact in self.review.facts}):
                raise ValueError("Every approved path must occur in the review result.")
            if self.refresh_sources and not self.rebind_after_refresh:
                raise ValueError("Refreshing review sources requires explicit rebind_after_refresh.")
        if len({item.document_id for item in self.refresh_sources}) != len(self.refresh_sources):
            raise ValueError("Refresh each source document once.")
        if self.rebind_after_refresh and not self.refresh_sources:
            raise ValueError("Package rebinding needs explicitly listed source refreshes.")
        if self.review is None and self.financing is None and not self.return_reviews and self.return_schedule is None and not self.refresh_sources:
            raise ValueError("A deal plan needs an explicit review action.")
        return self


class BackfillPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    version: Literal[1]
    deals: list[DealPlan] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_deals(self):
        if len({deal.deal_id for deal in self.deals}) != len(self.deals):
            raise ValueError("List each deal once in the plan.")
        return self


class BackfillFailure(ValueError):
    def __init__(self, message, report):
        super().__init__(message)
        deals = [{"deal_id": item["deal_id"], "revision": item.get("initial_revision", item["revision"]),
                  "current_package_id": item["current_package_id"]} for item in report["deals"]]
        for original, sanitized in zip(report["deals"], deals):
            blocked = [{"path": row["path"], "issue": row["issue"]} for row in original.get("review", [])
                       if row["selected"] and row["issue"]]
            if blocked:
                sanitized["blocked_selected"] = blocked
        self.report = {**report, "deals": deals, "status": "failed", "error": message}


def _payload(data, revision):
    if "expected_revision" in data:
        raise ValueError("Put expected_revision on the deal plan, not an operation payload.")
    return {**data, "expected_revision": revision}


def _analysis_summary(deal, analysis=None):
    analysis = analysis if analysis is not None else analysis_for_deal(deal)
    metrics = analysis["accepted_metrics"]
    budget_paths = {
        "total_project_cost": ("deal_structure.total_project_cost", "construction_costs.total_project_cost"),
        "hard_costs": ("construction_costs.hard_costs_total", "construction_costs.hard_costs", "financial_projections.hard_costs"),
        "soft_costs": ("construction_costs.soft_costs_total", "construction_costs.soft_costs", "financial_projections.soft_costs"),
        "land_cost": ("construction_costs.land_cost_total", "construction_costs.land_cost", "financial_projections.land_cost"),
    }
    budget = {label: next((get_path(metrics, path) for path in paths if get_path(metrics, path) is not None), None)
              for label, paths in budget_paths.items()}
    published = {key: analysis["facts"].get(analysis["returns"].get(f"{key}_path"))
                 for key in ("target_irr", "cash_on_cash", "target_equity_multiple")}
    return {
        "analysis_revision": analysis["version"],
        "accepted_fact_count": analysis["coverage"]["accepted"],
        "primary_strategy": analysis["primary_strategy"],
        "budget": budget,
        "published_returns": {key: analysis["returns"].get(key)
                              for key in ("target_irr", "cash_on_cash", "target_equity_multiple")},
        "published_return_contexts": {
            key: {dimension: fact["identity"].get(dimension)
                  for dimension in ("scenario", "investor_class", "basis", "period")}
            for key, fact in published.items() if fact
        },
        "optional_sale_returns": [
            {"path": fact["path"], "value": fact["value"],
             "context": {key: fact["identity"].get(key) for key in ("scenario", "investor_class", "basis", "period")}}
            for fact in optional_sale_returns(analysis)
        ],
        "return_schedule_rows": len((analysis.get("return_schedule") or {}).get("rows") or []),
        "score_coverage": effective_scores(deal).get("coverage") or {},
    }


def _return_baseline(deal, docs):
    metrics = deal.metrics or {}
    manifest = document_manifest(docs)
    analysis = build_analysis(metrics, manifest, deal.property_type)
    projected = _analysis_summary(deal, analysis)
    return_fields = (
        "primary_strategy", "published_returns", "published_return_contexts", "return_schedule_rows",
    )
    result = {key: projected[key] for key in return_fields}
    displayed = _analysis_summary(deal)
    result["displayed"] = {key: displayed[key] for key in return_fields}
    schedule = metrics.get("_return_schedule")
    result["schedule_record_exists"] = isinstance(schedule, dict)
    result["schedule_source_set_current"] = (
        schedule.get("review_document_set") == active_sources_fingerprint(manifest)
        if isinstance(schedule, dict) else None
    )
    result["selected_investor_class"] = analysis["investor_class"]
    published_paths = {analysis["returns"].get(f"{key}_path")
                       for key in ("target_irr", "cash_on_cash", "target_equity_multiple")}
    result["scoped_return_records"] = {}
    for path, record in (metrics.get("_return_reviews") or {}).items():
        if not isinstance(record, dict) or record.get("action") != "scope":
            continue
        fact = analysis["facts"].get(path)
        binding_current = bool(fact and record.get("binding") == return_review_binding(metrics, path, fact["value"]))
        source_set_current = record.get("document_set") == active_sources_fingerprint(manifest)
        result["scoped_return_records"][path] = {
            "binding_current": binding_current,
            "source_set_current": source_set_current,
            "context_applied": bool(binding_current and source_set_current and fact
                                    and fact["state"] in {"checked", "calculated", "manual"}
                                    and all(fact["identity"].get(key) == value
                                            for key, value in (record.get("context") or {}).items())),
            "published": path in published_paths,
        }
    return result


async def _lock_targets(db, plan):
    ids = sorted(item.deal_id for item in plan.deals)
    deals = (await db.execute(select(Deal).where(Deal.id.in_(ids)).order_by(Deal.id)
                             .with_for_update().execution_options(populate_existing=True))).scalars().all()
    (await db.execute(select(DealDocument).where(DealDocument.deal_id.in_(ids))
                      .order_by(DealDocument.id).with_for_update().execution_options(populate_existing=True))).scalars().all()
    (await db.execute(select(ReviewJob).where(ReviewJob.deal_id.in_(ids))
                      .order_by(ReviewJob.deal_id).with_for_update().execution_options(populate_existing=True))).scalars().all()
    return {deal.id: deal for deal in deals}


async def _check_target(item, deal, docs, summary, plan_hash, report):
    if deal is None or deal.deleted_at is not None:
        raise BackfillFailure(f"Deal {item.deal_id} is unavailable.", report)
    if deal.review_job and deal.review_job.status in {"queued", "running"}:
        raise BackfillFailure(f"Deal {item.deal_id} has an active document review.", report)
    refresh_hashes = {refresh.document_id: refresh.expected_file_sha256 for refresh in item.refresh_sources}
    for doc in review_documents(docs):
        status = (doc.extraction_quality or {}).get("status")
        if status in {"queued", "extracting"} or (status == "error" and doc.id not in refresh_hashes):
            raise BackfillFailure(f"Document {doc.id} is not ready for review.", report)
        if not doc.file_path or not Path(doc.file_path).is_file():
            raise BackfillFailure(f"Original document {doc.id} is unavailable.", report)
        if sha256_file(doc.file_path) != refresh_hashes.get(doc.id, file_hash(doc)):
            raise BackfillFailure(f"Original document {doc.id} does not match the required file hash.", report)
    current_package = summary["current_package_id"]
    for refresh in item.refresh_sources:
        source = next((doc for doc in docs if doc.id == refresh.document_id), None)
        if source is None or sha256_file(source.file_path) != refresh.expected_file_sha256:
            raise BackfillFailure(f"Refresh document {refresh.document_id} has a different ID or file hash.", report)
    receipt = ((deal.metrics or {}).get(RECEIPT_KEY) or {}).get(plan_hash)
    if receipt:
        if receipt.get("final_package_id") != current_package:
            raise BackfillFailure(f"Deal {deal.id} changed after this plan was applied.", report)
        summary["status"] = "already_applied"
        summary["analysis"] = _analysis_summary(deal)
        return deal, docs, True, summary
    if deal.revision != item.expected_revision or current_package != item.package_id:
        raise BackfillFailure(f"Deal {deal.id} has a different revision or source package.", report)
    return deal, docs, False, summary


async def _save_deal(db, item, deal, docs, summary, plan_hash, report):
    review = item.review
    if item.refresh_sources:
        for refresh in item.refresh_sources:
            await reprocess_document(refresh.document_id, db)
        await db.refresh(deal)
        docs = await load_documents(db, deal.id)
        summary["refreshed_documents"] = [refresh.document_id for refresh in item.refresh_sources]
        if review is not None:
            review = review.model_copy(update={"package_id": package_identity(deal, docs)})
    if item.review is not None:
        rows = validate_rows(deal, docs, review)
        selected = set(item.approve_paths)
        summary["review"] = [{"path": row["path"], "selected": row["path"] in selected,
                              "issue": row["issue"]} for row in rows]
        if any(row["issue"] and row["path"] in selected for row in rows):
            raise BackfillFailure(f"Deal {deal.id} has unresolved selected source checks.", report)
        deal.metrics = {**(deal.metrics or {}), DRAFT_KEY: draft_record(review, "codex")}
        await db.commit()
        await db.refresh(deal)
        await approve_draft(deal.id, ReviewApproval(
            draft_id=deal.metrics[DRAFT_KEY]["id"], expected_revision=deal.revision,
            paths=item.approve_paths,
        ), db)
    remaining = copy.deepcopy((deal.metrics or {}).get(DRAFT_KEY))
    remaining_is_current = (
        isinstance(remaining, dict)
        and (remaining.get("result") or {}).get("package_id") == package_identity(deal, docs)
    )
    remaining_sources = documents_fingerprint(docs)
    if item.financing is not None:
        data = FinancingUpdate.model_validate(_payload(item.financing, deal.revision))
        await save_financing_measures(deal.id, data, db)
    for payload in item.return_reviews:
        data = RETURN_REVIEW.validate_python(_payload(payload, deal.revision))
        await review_return(deal.id, data, db)
    if item.return_schedule is not None:
        data = ReturnScheduleUpdate.model_validate(_payload(item.return_schedule, deal.revision))
        await save_return_schedule(deal.id, data, db)
    docs = await load_documents(db, deal.id)
    if remaining_is_current and documents_fingerprint(docs) == remaining_sources:
        updated = ReviewResult.model_validate(remaining["result"]).model_copy(
            update={"package_id": package_identity(deal, docs)},
        )
        rows = validate_rows(deal, docs, updated)
        deal.metrics = {**(deal.metrics or {}), DRAFT_KEY: draft_record(
            updated, remaining["provider"], remaining.get("usage"),
        )}
        summary["remaining_review_rows"] = len(rows)
        summary["remaining_review_blocked"] = [{"path": row["path"], "issue": row["issue"]}
                                                for row in rows if row["issue"]]
    elif remaining:
        summary["remaining_review_stale"] = True
    final_package = package_identity(deal, docs)
    receipts = {**((deal.metrics or {}).get(RECEIPT_KEY) or {}),
                plan_hash: {"final_package_id": final_package}}
    deal.metrics = {**(deal.metrics or {}), RECEIPT_KEY: receipts}
    await db.commit()
    summary.update(status="applied", revision=deal.revision, final_package_id=final_package,
                   analysis=_analysis_summary(deal))


async def execute_plan(plan: BackfillPlan, *, engine, apply=False):
    """Route commits use savepoints. Only the outer transaction may persist."""
    plan_hash = digest(plan.model_dump())
    report = {"mode": "apply" if apply else "dry_run", "plan_digest": plan_hash,
              "status": "pending", "deals": []}
    if engine.url.get_backend_name() == "sqlite" and not Path(engine.url.database or "").is_file():
        raise BackfillFailure("The configured existing database is unavailable.", report)
    async with engine.connect() as connection:
        try:
            # SQLite's legacy driver does not begin a physical transaction for
            # SAVEPOINT alone. Explicit BEGIN prevents route commits escaping it.
            if connection.dialect.name == "sqlite":
                await connection.exec_driver_sql("BEGIN IMMEDIATE")
            else:
                await connection.begin()
            async with async_session(bind=connection, join_transaction_mode="create_savepoint") as db:
                deals = await _lock_targets(db, plan)
                targets = []
                for item in plan.deals:
                    deal = deals.get(item.deal_id)
                    docs = await load_documents(db, item.deal_id) if deal else []
                    summary = {"deal_id": item.deal_id, "revision": deal.revision if deal else None,
                               "initial_revision": deal.revision if deal else None,
                               "current_package_id": package_identity(deal, docs) if deal else None,
                               "status": "pending"}
                    draft = (deal.metrics or {}).get(DRAFT_KEY) if deal else None
                    if isinstance(draft, dict):
                        draft_package = (draft.get("result") or {}).get("package_id")
                        summary["existing_draft"] = {"id": draft.get("id"), "package_id": draft_package,
                                                     "stale": draft_package != summary["current_package_id"]}
                    report["deals"].append(summary)
                    targets.append((item, deal, docs, summary))
                checked_targets = []
                for item, deal, docs, summary in targets:
                    deal, docs, repeated, summary = await _check_target(item, deal, docs, summary, plan_hash, report)
                    checked_targets.append((item, deal, docs, repeated, summary))
                for item, deal, docs, repeated, summary in checked_targets:
                    if not repeated:
                        if not apply:
                            summary["return_baseline"] = _return_baseline(deal, docs)
                        await _save_deal(db, item, deal, docs, summary, plan_hash, report)
                        if not apply:
                            after = _return_baseline(deal, await load_documents(db, deal.id))
                            summary["return_after"] = after
                            summary["return_changes"] = {
                                key: summary["return_baseline"][key] != after[key]
                                for key in ("primary_strategy", "published_returns", "published_return_contexts",
                                            "return_schedule_rows", "schedule_record_exists", "scoped_return_records",
                                            "displayed")
                            }
            if apply:
                await connection.commit()
                report["status"] = "applied"
            else:
                await connection.rollback()
                report["status"] = "validated"
                for summary in report["deals"]:
                    if summary["status"] == "applied":
                        summary["projected_revision"] = summary["revision"]
                        summary["revision"] = summary["initial_revision"]
                        summary["status"] = "validated"
            return report
        except BackfillFailure:
            await connection.rollback()
            raise
        except HTTPException as exc:
            await connection.rollback()
            raise BackfillFailure(f"Save validation failed ({exc.status_code}): {exc.detail}", report) from None
        except (ValidationError, ValueError) as exc:
            await connection.rollback()
            message = "An operation payload failed validation." if isinstance(exc, ValidationError) else str(exc)
            raise BackfillFailure(message, report) from None
        except Exception as exc:
            await connection.rollback()
            raise BackfillFailure(f"The batch was rolled back after an operation failed ({type(exc).__name__}).", report) from None


async def _run(plan, apply):
    from app.database import engine
    try:
        return await execute_plan(plan, engine=engine, apply=apply)
    finally:
        await engine.dispose()


async def diagnose_plan(plan: BackfillPlan, *, engine):
    """Collect independent deal previews, each confined to its own rollback."""
    report = {"mode": "diagnostic_dry_run", "plan_digest": digest(plan.model_dump()),
              "status": "validated", "validated_deals": 0, "failed_deals": 0, "deals": []}
    for item in plan.deals:
        scoped_plan = plan.model_copy(update={"deals": [item]})
        try:
            result = await execute_plan(scoped_plan, engine=engine, apply=False)
        except BackfillFailure as exc:
            result = exc.report
        except Exception as exc:
            result = {"status": "failed", "error_type": type(exc).__name__, "deals": []}
        details = result.get("deals") or [{"deal_id": item.deal_id}]
        detail = {**details[0]}
        if result["status"] == "failed":
            detail.update(status="failed")
            for key in ("error", "error_type"):
                if key in result:
                    detail[key] = result[key]
            report["failed_deals"] += 1
            report["status"] = "failed"
        else:
            report["validated_deals"] += 1
        report["deals"].append(detail)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", default="-", help="Private JSON plan file, or - for stdin.")
    parser.add_argument("--apply", action="store_true", help="Persist the batch after every action validates.")
    args = parser.parse_args()
    try:
        body = sys.stdin.read() if args.plan == "-" else Path(args.plan).read_text(encoding="utf-8-sig")
        plan = BackfillPlan.model_validate_json(body)
        result = asyncio.run(_run(plan, args.apply))
    except BackfillFailure as exc:
        print(json.dumps(exc.report, indent=2))
        return 1
    except (OSError, ValidationError, SQLAlchemyError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "failed", "error": f"Backfill input or database failure ({type(exc).__name__})."}))
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

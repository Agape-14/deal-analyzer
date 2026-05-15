import asyncio
import copy
import json
import logging
import traceback

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import async_session, get_db
from app.models import Deal
from app.rate_limit import limit
from app.services.canonical_metrics import annotate_canonical_metrics
from app.services import notifications as notif_svc
from app.services.confidence import summarize_math_checks
from app.services.data_integrity import (
    auto_resolve_conflicts,
    conflicts_to_flags,
    detect_conflicts,
    quality_summary,
    smart_merge,
    stamp_verification,
    staleness_flags,
    now_iso,
)
from app.services.deal_extractor import _post_process_metrics, extract_metrics_from_docs
from app.services.deal_scorer import score_deal
from app.services.deal_validator import validate_deal_metrics
from app.services.deal_verifier import apply_corrections, verify_deal_metrics
from app.services.math_checker import run_math_checks

router = APIRouter()
log = logging.getLogger("kenyon.deal_pipeline")


def _pipeline_status(
    status: str,
    step: str,
    message: str,
    *,
    started_at: str | None = None,
    error: str | None = None,
    error_kind: str | None = None,
) -> dict:
    now = now_iso()
    return {
        "status": status,
        "step": step,
        "message": message,
        "started_at": started_at or now,
        "updated_at": now,
        "error": error,
        "error_kind": error_kind,
    }


def _ensure_metrics_dict(value, context: str) -> dict:
    """Return a metrics dict, accepting double-encoded JSON strings.

    Claude and older upload paths can occasionally hand us a JSON object
    encoded as a string. Without this guard, later merge code crashes with
    messages like "'str' object has no attribute 'keys'". Parse one or two
    layers, then fail with a user-readable error if it still is not an object.
    """
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return {}
        parsed = raw
        for _ in range(2):
            if not isinstance(parsed, str):
                break
            try:
                parsed = json.loads(parsed)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"{context} returned text instead of a JSON object. "
                    f"First 120 characters: {raw[:120]!r}. Parse error: {exc}"
                ) from exc
        if isinstance(parsed, dict):
            return parsed
        raise ValueError(f"{context} returned {type(parsed).__name__}, expected a JSON object.")
    raise ValueError(f"{context} returned {type(value).__name__}, expected a JSON object.")


def _set_pipeline_status(metrics: dict | None, status: dict) -> dict:
    next_metrics = _ensure_metrics_dict(metrics, "Stored deal metrics")
    existing = next_metrics.get("_pipeline") if isinstance(next_metrics.get("_pipeline"), dict) else {}
    if existing and not status.get("started_at"):
        status["started_at"] = existing.get("started_at")
    next_metrics["_pipeline"] = status
    return next_metrics


def _pipeline_error_kind(error: Exception) -> str:
    text = str(error) or error.__class__.__name__
    lower = text.lower()
    if any(token in lower for token in ("credit", "credits", "quota", "balance", "billing", "payment", "insufficient_quota", "insufficient quota")):
        return "ai_quota"
    if ("rate" in lower and "limit" in lower) or "429" in lower or "too many requests" in lower:
        return "ai_rate_limit"
    if "overloaded" in lower or "529" in lower:
        return "ai_temporarily_unavailable"
    if "anthropic" in lower:
        return "ai_provider"
    return "unknown"


def _pipeline_error_message(error: Exception) -> str:
    text = str(error) or error.__class__.__name__
    kind = _pipeline_error_kind(error)
    if kind == "ai_quota":
        return "Document review incomplete: the AI provider quota or credit balance was exhausted. The deal was not fully re-read, verified, or rescored. Add API credits or update billing, then review documents again."
    if kind == "ai_rate_limit":
        return "Document review incomplete: the AI provider rate limit was reached. The deal was not fully re-read, verified, or rescored. Wait for the limit window to reset, then review documents again."
    if kind == "ai_temporarily_unavailable":
        return "Document review incomplete: the AI provider was temporarily unavailable or overloaded. The deal was not fully re-read, verified, or rescored. Wait a few minutes, then review documents again."
    if kind == "ai_provider":
        return f"Document review incomplete during the Anthropic AI call. The deal was not fully re-read, verified, or rescored. Details: {text[:420]}"
    return text[:500]


def _pdf_docs(deal: Deal):
    return [
        d
        for d in deal.documents
        if d.file_path and str(d.file_path).lower().endswith(".pdf")
    ]


@router.get("/{deal_id}/quality")
async def deal_quality(deal_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Deal).options(selectinload(Deal.documents)).where(Deal.id == deal_id))
    deal = result.scalar_one_or_none()
    if not deal:
        raise HTTPException(status_code=404, detail="Deal not found")
    metrics = _ensure_metrics_dict(deal.metrics, "Stored deal metrics")
    return {
        "summary": quality_summary(metrics),
        "stale_flags": staleness_flags(metrics, deal.documents or []),
        "pipeline": metrics.get("_pipeline"),
    }


# Fields the downstream pipeline (scorer, validator, post-processor,
# math_checker) compares numerically. If any of these is stored as a
# non-numeric type, the pipeline crashes with "'>=' not supported
# between instances of 'str' and 'int'" or similar. Listing them
# explicitly here lets the diagnose endpoint flag the exact offender
# instead of asking the operator to read tracebacks.
_NUMERIC_FIELDS_BY_SECTION: dict[str, tuple[str, ...]] = {
    "deal_structure": (
        "ltv", "preferred_return", "fees_asset_mgmt", "fees_acquisition",
        "fees_disposition", "fees_dev_fee", "fees_construction_mgmt",
        "gp_equity_coinvest_pct", "total_project_cost", "total_equity_required",
        "debt_amount", "construction_loan_amount", "permanent_loan_amount",
        "hold_period_years", "interest_rate", "minimum_investment",
        "gp_cash_at_risk",
    ),
    "target_returns": (
        "target_irr", "net_irr", "gross_irr", "target_equity_multiple",
        "net_equity_multiple", "gross_equity_multiple", "target_cash_on_cash",
        "target_avg_annual_return", "projected_profit", "distribution_yield",
        "total_fee_drag",
    ),
    "project_details": (
        "unit_count", "total_sqft", "price_per_unit", "price_per_sqft",
        "construction_duration_months", "renovation_timeline_months",
        "current_occupancy", "current_avg_rent", "proforma_avg_rent",
    ),
    "financial_projections": (
        "stabilized_noi", "entry_cap_rate", "exit_cap_rate",
        "avg_rent_per_unit", "avg_rent_per_sqft", "rent_growth_assumption",
        "occupancy_assumption", "operating_expense_ratio",
        "construction_budget", "land_cost", "soft_costs", "hard_costs",
    ),
    "market_location": (
        "market_population", "market_job_growth", "market_rent_growth",
        "market_vacancy_rate", "walk_score",
    ),
    "underwriting_checks": (
        "break_even_occupancy", "dscr", "yield_on_cost",
        "expense_growth_assumption", "replacement_cost_per_unit",
        "revenue_per_unit", "operating_expense_per_unit",
        "management_fee_pct", "reserves_per_unit",
    ),
    "risk_assessment": (
        "market_risk_score", "execution_risk_score", "financial_risk_score",
        "entitlement_risk_score", "developer_risk_score", "overall_risk_score",
    ),
    "sponsor_evaluation": (
        "sponsor_full_cycle_deals", "alignment_score",
    ),
}


def _audit_metric_shapes(metrics: dict) -> list[dict]:
    """Return one entry per field whose type does not match the numeric
    contract the pipeline assumes. This is the diagnostic that tells you
    *which* value is stringy without needing to reproduce the crash."""
    issues: list[dict] = []
    for section, fields in _NUMERIC_FIELDS_BY_SECTION.items():
        block = metrics.get(section)
        if not isinstance(block, dict):
            if block not in (None, "", {}):
                issues.append({
                    "path": section,
                    "expected": "dict",
                    "actual_type": type(block).__name__,
                    "value_preview": repr(block)[:120],
                })
            continue
        for field in fields:
            if field not in block:
                continue
            value = block[field]
            if value is None or isinstance(value, bool):
                continue
            if isinstance(value, (int, float)):
                continue
            issues.append({
                "path": f"{section}.{field}",
                "expected": "number",
                "actual_type": type(value).__name__,
                "value_preview": repr(value)[:120],
            })
    return issues


def _run_stage(name: str, fn) -> dict:
    """Run a pipeline stage on a deep copy of metrics and capture the
    outcome. Returns a structured record either way — the diagnose
    endpoint never raises just because one stage fails."""
    try:
        fn()
        return {"name": name, "ok": True}
    except Exception as exc:  # noqa: BLE001
        return {
            "name": name,
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
            "trace_tail": traceback.format_exc().splitlines()[-12:],
        }


@router.get("/{deal_id}/diagnose")
async def diagnose_deal(deal_id: int, db: AsyncSession = Depends(get_db)):
    """In-process dry run of every pipeline stage against the stored
    metrics. Pure read — never writes, never calls Claude. Returns:

      - `pipeline`: the persisted `_pipeline` block (last known step/error)
      - `shape_issues`: every numeric field stored as a non-number
      - `stages`: per-stage `{ok, error, trace_tail}` records so you
        can see exactly where the pipeline would crash if you hit
        Review documents again — without rerunning extraction.

    Use this any time the hero card says "Document review incomplete"
    and you want the truth about why."""
    result = await db.execute(
        select(Deal).options(selectinload(Deal.documents)).where(Deal.id == deal_id)
    )
    deal = result.scalar_one_or_none()
    if not deal:
        raise HTTPException(status_code=404, detail="Deal not found")

    raw_metrics = deal.metrics
    report: dict = {
        "deal_id": deal_id,
        "project_name": deal.project_name,
        "metrics_raw_type": type(raw_metrics).__name__,
        "metrics_raw_preview": repr(raw_metrics)[:200] if not isinstance(raw_metrics, dict) else None,
    }

    # Stage 0: ensure metrics is a dict. If this fails, nothing else can run.
    try:
        metrics = _ensure_metrics_dict(raw_metrics, "Stored deal metrics")
    except Exception as exc:  # noqa: BLE001
        report["stages"] = [{
            "name": "load_metrics",
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
            "trace_tail": traceback.format_exc().splitlines()[-12:],
        }]
        report["shape_issues"] = []
        return report

    report["pipeline"] = metrics.get("_pipeline")
    report["top_level_keys"] = sorted(metrics.keys())
    report["shape_issues"] = _audit_metric_shapes(metrics)

    stages: list[dict] = [{"name": "load_metrics", "ok": True}]

    stages.append(_run_stage(
        "post_process_metrics",
        lambda: _post_process_metrics(copy.deepcopy(metrics)),
    ))
    stages.append(_run_stage(
        "annotate_canonical",
        lambda: annotate_canonical_metrics(copy.deepcopy(metrics)),
    ))
    stages.append(_run_stage(
        "validate_deal_metrics",
        lambda: validate_deal_metrics(copy.deepcopy(metrics), deal.property_type),
    ))
    stages.append(_run_stage(
        "staleness_flags",
        lambda: staleness_flags(copy.deepcopy(metrics), deal.documents or []),
    ))
    stages.append(_run_stage(
        "run_math_checks",
        lambda: run_math_checks(copy.deepcopy(metrics)),
    ))
    stages.append(_run_stage(
        "score_deal",
        lambda: score_deal(copy.deepcopy(metrics), require_verified=False),
    ))
    stages.append(_run_stage(
        "quality_summary",
        lambda: quality_summary(copy.deepcopy(metrics)),
    ))
    stages.append(_run_stage(
        "smart_merge_self",
        lambda: smart_merge(copy.deepcopy(metrics), copy.deepcopy(metrics)),
    ))

    report["stages"] = stages
    failed = [s for s in stages if not s.get("ok")]
    report["summary"] = {
        "stages_run": len(stages),
        "stages_failed": len(failed),
        "first_failure": failed[0]["name"] if failed else None,
        "first_failure_error": failed[0].get("error") if failed else None,
        "shape_issue_count": len(report["shape_issues"]),
    }
    return report


@router.post("/{deal_id}/extract", dependencies=[Depends(limit("ai"))])
async def extract_deal_metrics(deal_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Deal).options(selectinload(Deal.documents)).where(Deal.id == deal_id)
    )
    deal = result.scalar_one_or_none()
    if not deal:
        raise HTTPException(status_code=404, detail="Deal not found")
    if not deal.documents:
        raise HTTPException(status_code=400, detail="No documents uploaded yet")

    usable_docs = [d for d in deal.documents if (d.extracted_text or "")]
    usable_pdfs = _pdf_docs(deal)
    if not usable_docs and not usable_pdfs:
        raise HTTPException(status_code=400, detail="No extracted text or PDF files available")

    deal.metrics = _set_pipeline_status(
        deal.metrics,
        _pipeline_status("running", "extract", "Extraction started. Reading all uploaded documents."),
    )
    await db.commit()
    asyncio.ensure_future(_run_extract_background(deal_id))
    return {"message": "Extraction started", "status": "started", "deal_id": deal_id}


async def _run_extract_background(deal_id: int):
    async with async_session() as db:
        try:
            result = await db.execute(
                select(Deal).options(selectinload(Deal.documents)).where(Deal.id == deal_id)
            )
            deal = result.scalar_one_or_none()
            if not deal or not deal.documents:
                return

            existing_metrics = _ensure_metrics_dict(deal.metrics, "Stored deal metrics")
            usable_docs = [d for d in deal.documents if (d.extracted_text or "")]
            usable_pdfs = _pdf_docs(deal)
            per_doc_results: list[tuple[int, str, dict]] = []
            if len(deal.documents) > 1:
                for doc in deal.documents:
                    text = doc.extracted_text or ""
                    path = doc.file_path if doc in usable_pdfs else None
                    if not text and not path:
                        continue
                    one_doc_text = (
                        [{"filename": doc.filename, "doc_type": doc.doc_type, "text": text}]
                        if text
                        else []
                    )
                    try:
                        mx = await extract_metrics_from_docs(one_doc_text, doc_paths=[path] if path else [])
                        mx = _ensure_metrics_dict(mx, f"Extraction for {doc.filename}")
                        per_doc_results.append((doc.id, doc.filename, mx))
                    except Exception:
                        log.exception("per-document extraction failed for deal %s doc %s", deal_id, doc.id)

            doc_texts = [
                {"filename": d.filename, "doc_type": d.doc_type, "text": d.extracted_text or ""}
                for d in usable_docs
            ]
            incoming_metrics = await extract_metrics_from_docs(
                doc_texts,
                doc_paths=[d.file_path for d in usable_pdfs],
            )
            incoming_metrics = _ensure_metrics_dict(incoming_metrics, "Document extraction")

            primary_doc = usable_docs[0] if len(usable_docs) == 1 else None
            merged, changes = smart_merge(
                existing_metrics,
                incoming_metrics,
                source_doc_id=primary_doc.id if primary_doc else None,
                source_doc_name=primary_doc.filename if primary_doc else "multiple documents",
            )

            conflicts = detect_conflicts(per_doc_results) if len(per_doc_results) >= 2 else {}
            n_auto_resolved = 0
            if conflicts:
                doc_upload_dates = {d.id: d.upload_date for d in deal.documents}
                n_auto_resolved = auto_resolve_conflicts(conflicts, merged, doc_upload_dates)
                prov = dict(merged.get("_provenance") or {})
                for path, entries in conflicts.items():
                    if any(e.get("auto_resolved") for e in entries):
                        continue
                    existing_prov = prov.get(path, {})
                    existing_prov["conflict"] = entries
                    prov[path] = existing_prov
                merged["_provenance"] = prov

            history = list(merged.get("_extraction_history") or [])
            history.append(
                {
                    "at": now_iso(),
                    "changes": changes[:50],
                    "doc_count": len(deal.documents),
                    "conflicts": list(conflicts.keys()),
                }
            )
            merged["_extraction_history"] = history[-20:]

            validation_flags = validate_deal_metrics(merged, deal.property_type)
            validation_flags.extend(conflicts_to_flags(conflicts))
            validation_flags.extend(staleness_flags(merged, deal.documents))
            merged["validation_flags"] = validation_flags
            merged = annotate_canonical_metrics(merged)
            merged["_pipeline"] = _pipeline_status(
                "extract_complete",
                "extract",
                "Extraction complete. Values are ready for source verification.",
                started_at=existing_metrics.get("_pipeline", {}).get("started_at")
                if isinstance(existing_metrics.get("_pipeline"), dict)
                else None,
            )

            deal.metrics = merged
            ml = merged.get("market_location", {}) or {}
            if not deal.city and ml.get("city"):
                deal.city = ml["city"]
            if not deal.state and ml.get("state"):
                deal.state = ml["state"]
            try:
                deal.scores = score_deal(merged)
            except Exception:
                log.exception("score refresh after extraction failed for deal %s", deal_id)

            n_unresolved_conflicts = len(conflicts) - n_auto_resolved
            reds = [f for f in validation_flags if f.get("severity") == "red"]
            body_parts = [f"{len(changes)} field{'s' if len(changes) != 1 else ''} updated"]
            if n_auto_resolved:
                body_parts.append(f"{n_auto_resolved} conflict{'s' if n_auto_resolved != 1 else ''} auto-resolved")
            if n_unresolved_conflicts:
                body_parts.append(f"{n_unresolved_conflicts} unresolved conflict{'s' if n_unresolved_conflicts != 1 else ''}")
            if reds:
                body_parts.append(f"{len(reds)} red flag{'s' if len(reds) != 1 else ''}")
            await notif_svc.emit(
                db,
                kind="error" if n_unresolved_conflicts or reds else "success",
                title=f"Metrics extracted for {deal.project_name}",
                body=" - ".join(body_parts),
                href=f"/deals/{deal.id}?tab=overview",
                payload={"deal_id": deal.id, "changes": len(changes), "red_flags": len(reds)},
            )
            await db.commit()
        except Exception as e:
            log.exception("extract pipeline failed for deal %s", deal_id)
            await _persist_pipeline_failure(db, deal_id, "extract", "Extraction failed.", e)


@router.post("/{deal_id}/verify", dependencies=[Depends(limit("ai"))])
async def verify_deal_endpoint(deal_id: int, auto_correct: bool = True, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Deal).options(selectinload(Deal.documents)).where(Deal.id == deal_id)
    )
    deal = result.scalar_one_or_none()
    if not deal:
        raise HTTPException(status_code=404, detail="Deal not found")
    if not deal.metrics:
        raise HTTPException(status_code=400, detail="No metrics extracted yet. Run extraction first.")

    deal.metrics = _set_pipeline_status(
        deal.metrics,
        _pipeline_status("running", "verify", "Verification started. Checking extracted values against source documents."),
    )
    await db.commit()
    asyncio.ensure_future(_run_verify_background(deal_id, auto_correct))
    return {"message": "Verification started", "status": "started", "deal_id": deal_id}


async def _run_verify_background(deal_id: int, auto_correct: bool):
    async with async_session() as db:
        try:
            result = await db.execute(
                select(Deal).options(selectinload(Deal.documents)).where(Deal.id == deal_id)
            )
            deal = result.scalar_one_or_none()
            if not deal or not deal.metrics:
                return

            verification = await verify_deal_metrics(deal, db)
            metrics = _ensure_metrics_dict(deal.metrics, "Stored deal metrics")
            changes: list[str] = []
            if auto_correct:
                metrics, changes = apply_corrections(metrics, verification)
            metrics = stamp_verification(metrics, verification)

            math_results = run_math_checks(metrics)
            metrics["_math_checks"] = {
                "checked_at": now_iso(),
                "summary": summarize_math_checks(math_results, metrics),
                "results": math_results,
            }
            flags = validate_deal_metrics(metrics, deal.property_type)
            flags.extend(staleness_flags(metrics, deal.documents or []))
            metrics["validation_flags"] = flags
            metrics = annotate_canonical_metrics(metrics)
            metrics["_pipeline"] = _pipeline_status(
                "verify_complete",
                "verify",
                "Verification complete. Values are ready to be scored.",
                started_at=(deal.metrics or {}).get("_pipeline", {}).get("started_at")
                if isinstance((deal.metrics or {}).get("_pipeline"), dict)
                else None,
            )
            deal.metrics = metrics
            deal.scores = score_deal(metrics, math_checks=math_results)
            await notif_svc.emit(
                db,
                kind="success",
                title=f"Verification complete - {deal.project_name}",
                body=f"{len(changes)} correction{'s' if len(changes) != 1 else ''} applied",
                href=f"/deals/{deal.id}?tab=overview",
                payload={"deal_id": deal.id, "corrections": len(changes)},
            )
            await db.commit()
        except Exception as e:
            log.exception("verify pipeline failed for deal %s", deal_id)
            await _persist_pipeline_failure(db, deal_id, "verify", "Verification failed.", e)


@router.post("/{deal_id}/score", dependencies=[Depends(limit("write"))])
async def score_deal_endpoint(deal_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Deal).where(Deal.id == deal_id))
    deal = result.scalar_one_or_none()
    if not deal:
        raise HTTPException(status_code=404, detail="Deal not found")
    if not deal.metrics:
        raise HTTPException(status_code=400, detail="No metrics extracted yet. Run extraction first.")

    deal.metrics = _set_pipeline_status(
        deal.metrics,
        _pipeline_status("running", "score", "Scoring started. Recalculating validation, math checks, and score."),
    )
    await db.commit()
    try:
        metrics = _ensure_metrics_dict(deal.metrics, "Stored deal metrics")
        metrics = annotate_canonical_metrics(metrics)
        scores = score_deal(metrics)
    except Exception as e:
        await _persist_pipeline_failure(db, deal_id, "score", "Scoring failed.", e)
        raise HTTPException(status_code=503, detail=_pipeline_error_message(e))

    deal.scores = scores
    deal.metrics = _set_pipeline_status(
        metrics,
        _pipeline_status("complete", "score", "Document review complete. Extraction, verification, math checks, and scoring finished."),
    )
    await db.commit()
    return {"message": "Deal scored", "scores": scores}


async def _persist_pipeline_failure(db: AsyncSession, deal_id: int, step: str, message: str, error: Exception) -> None:
    try:
        await db.rollback()
        result = await db.execute(select(Deal).where(Deal.id == deal_id))
        deal = result.scalar_one_or_none()
        if not deal:
            return
        error_message = _pipeline_error_message(error)
        error_kind = _pipeline_error_kind(error)
        deal.metrics = _set_pipeline_status(
            deal.metrics,
            _pipeline_status("failed", step, message, error=error_message, error_kind=error_kind),
        )
        await notif_svc.emit(
            db,
            kind="error",
            title=f"Document review stopped - {deal.project_name}",
            body=error_message,
            href=f"/deals/{deal.id}?tab=overview",
            payload={"deal_id": deal.id, "step": step, "error": error_message, "error_kind": error_kind},
        )
        await db.commit()
    except Exception:
        log.exception("failed to persist pipeline failure for deal %s", deal_id)

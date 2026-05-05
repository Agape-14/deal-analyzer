"""Data-confidence gates for deal scoring.

The extractor is useful, but extracted values are only candidates until the
verification pass and deterministic math checks support them. This module keeps
that policy in one place so scoring, quality endpoints, and the UI all explain
the same answer.
"""

from __future__ import annotations

from typing import Any


CRITICAL_FIELDS: tuple[tuple[str, str], ...] = (
    ("deal_structure.minimum_investment", "Minimum investment"),
    ("deal_structure.total_equity_required", "Total equity required"),
    ("deal_structure.total_project_cost", "Total project cost"),
    ("deal_structure.debt_amount", "Debt amount"),
    ("deal_structure.ltv", "LTV"),
    ("deal_structure.hold_period_years", "Hold period"),
    ("target_returns.target_irr", "Target IRR"),
    ("target_returns.target_equity_multiple", "Equity multiple"),
    ("target_returns.target_cash_on_cash", "Cash-on-cash"),
    ("project_details.unit_count", "Unit count"),
    ("financial_projections.stabilized_noi", "Stabilized NOI"),
    ("financial_projections.avg_rent_per_unit", "Average rent"),
    ("financial_projections.occupancy_assumption", "Occupancy assumption"),
)

VERIFIED_STATUSES = {"confirmed", "calculated"}
BAD_STATUSES = {"wrong", "missing", "unverifiable"}


def _get_path(data: dict[str, Any], path: str) -> Any:
    cur: Any = data
    for part in path.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def _present(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    return value != []


def summarize_math_checks(checks: list[dict[str, Any]] | None) -> dict[str, Any]:
    checks = checks or []
    summary = {"pass": 0, "fail": 0, "warn": 0, "info": 0, "total": len(checks), "blocking": []}
    for check in checks:
        status = str((check or {}).get("status") or "").lower()
        if status in summary:
            summary[status] += 1
        if status == "fail":
            summary["blocking"].append({
                "check": check.get("check"),
                "difference": check.get("difference"),
                "formula": check.get("formula"),
            })
    return summary


def assess_data_quality(
    metrics: dict[str, Any] | None,
    math_checks: list[dict[str, Any]] | None = None,
    *,
    require_verified: bool = True,
) -> dict[str, Any]:
    metrics = metrics or {}
    if math_checks is None and metrics:
        try:
            from app.services.math_checker import run_math_checks

            math_checks = run_math_checks(metrics)
        except Exception:
            math_checks = []
    provenance = metrics.get("_provenance") or {}
    verification = metrics.get("_verification") or {}
    verified_at = verification.get("verified_at")
    verification_confidence = verification.get("confidence")

    critical: list[dict[str, Any]] = []
    missing = 0
    unverified = 0
    conflicted = 0
    bad = 0

    for path, label in CRITICAL_FIELDS:
        value = _get_path(metrics, path)
        present = _present(value)
        prov = provenance.get(path) or {}
        status = str(prov.get("status") or ("extracted" if present else "missing")).lower()
        source = str(prov.get("source") or "").lower()
        verified = status in VERIFIED_STATUSES or source == "manual"
        conflict = bool(prov.get("conflict"))

        severity = "ok"
        reason = None
        if not present:
            severity = "blocker"
            reason = "missing"
            missing += 1
        elif conflict:
            severity = "blocker"
            reason = "conflicting source values"
            conflicted += 1
        elif status in BAD_STATUSES:
            severity = "blocker"
            reason = status
            bad += 1
        elif require_verified and not verified:
            severity = "review"
            reason = "not verified against source"
            unverified += 1

        critical.append({
            "path": path,
            "label": label,
            "present": present,
            "status": status,
            "verified": verified,
            "severity": severity,
            "reason": reason,
        })

    math_summary = summarize_math_checks(math_checks)
    has_math_failures = math_summary["fail"] > 0
    has_blockers = missing > 0 or conflicted > 0 or bad > 0 or has_math_failures
    has_review_items = unverified > 0
    verification_complete = bool(verified_at)

    if conflicted:
        stage = "conflicting"
    elif missing or bad:
        stage = "insufficient_source"
    elif not verification_complete:
        stage = "provisional"
    elif has_math_failures:
        stage = "math_failed"
    elif has_review_items:
        stage = "needs_review"
    else:
        stage = "verified"

    can_score = (
        not has_blockers
        and (not require_verified or verification_complete)
        and not has_review_items
    )

    if verification_confidence is None:
        confidence_score = 35 if not verification_complete else 70
    else:
        try:
            confidence_score = float(verification_confidence)
        except (TypeError, ValueError):
            confidence_score = 70

    confidence_score -= missing * 8
    confidence_score -= unverified * 4
    confidence_score -= conflicted * 15
    confidence_score -= bad * 12
    confidence_score -= math_summary["fail"] * 10
    confidence_score -= math_summary["warn"] * 2
    confidence_score = max(0, min(100, round(confidence_score, 1)))

    return {
        "stage": stage,
        "can_score": can_score,
        "confidence_score": confidence_score,
        "verified_at": verified_at,
        "critical_fields": critical,
        "critical_summary": {
            "total": len(CRITICAL_FIELDS),
            "missing": missing,
            "unverified": unverified,
            "conflicted": conflicted,
            "bad": bad,
            "verified": len(CRITICAL_FIELDS) - missing - unverified - conflicted - bad,
        },
        "math_summary": math_summary,
    }

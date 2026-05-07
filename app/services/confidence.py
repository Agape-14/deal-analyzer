"""Data-confidence gates for deal scoring.

The extractor is useful, but extracted values are only candidates until the
verification pass and deterministic math checks support them. This module keeps
that policy in one place so scoring, quality endpoints, and the UI all explain
the same answer.
"""

from typing import Any, Dict, List, Optional, Tuple

from app.services.canonical_metrics import is_hold_strategy


# Each entry is (canonical_path, label, fallback_paths). The canonical path is
# what the scoring model and UI should use. Fallbacks keep older extracted deals
# reviewable, while math checks still block scoring when an alias conflicts.
CRITICAL_FIELDS = (
    ("deal_structure.minimum_investment", "Minimum investment", ()),
    ("deal_structure.total_equity_required", "Total equity required", ()),
    ("deal_structure.total_project_cost", "Total project cost", ()),
    ("deal_structure.debt_amount", "Debt amount", ()),
    ("deal_structure.ltv", "LTV", ()),
    ("deal_structure.hold_period_years", "Hold period", ()),
    ("target_returns.target_irr", "Target IRR", ("target_returns.net_irr",)),
    ("target_returns.target_equity_multiple", "Equity multiple", ("target_returns.net_equity_multiple",)),
    ("target_returns.target_cash_on_cash", "Cash-on-cash", ("target_returns.distribution_yield",)),
    ("project_details.unit_count", "Unit count", ()),
    ("financial_projections.stabilized_noi", "Stabilized NOI", ()),
    ("financial_projections.avg_rent_per_unit", "Average rent", ()),
    ("financial_projections.occupancy_assumption", "Occupancy assumption", ()),
)  # type: Tuple[Tuple[str, str, Tuple[str, ...]], ...]

VERIFIED_STATUSES = {"confirmed", "calculated"}
BAD_STATUSES = {"wrong", "missing", "math_failed"}
REVIEW_STATUSES = {"unverifiable"}
HOLD_SCENARIO_ALIAS_CHECKS = {
    "Target IRR = Net IRR",
    "Equity Multiple = Net Equity Multiple",
    "IRR vs Equity Multiple Consistency",
}
# These checks are useful analyst cautions, but they are not proof that the
# extracted source data is wrong. They rely on simplified formulas or partial
# component lists, so they should not single-handedly block confidence.
NON_BLOCKING_FAIL_CHECKS = {
    "Yield on Cost vs Entry Cap Rate",
    "DSCR = NOI / Annual Debt Service",
    "Hard + Soft + Land + Contingency = Total Cost",
    "Cost Components ≈ Total Project Cost",
}


def _get_path(data, path):
    # type: (Dict[str, Any], str) -> Any
    cur = data  # type: Any
    for part in path.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def _present(value):
    # type: (Any) -> bool
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    return value != []


def _pick_present_path(metrics, canonical_path, fallback_paths):
    # type: (Dict[str, Any], str, Tuple[str, ...]) -> Tuple[str, Any]
    for path in (canonical_path, *fallback_paths):
        value = _get_path(metrics, path)
        if _present(value):
            return path, value
    return canonical_path, None


def _is_ignored_hold_alias_check(check, metrics):
    # type: (Dict[str, Any], Dict[str, Any]) -> bool
    if not is_hold_strategy(metrics):
        return False
    name = str((check or {}).get("check") or "")
    if name in HOLD_SCENARIO_ALIAS_CHECKS:
        return True
    formula = str((check or {}).get("formula") or "").lower()
    return "hypothetical sale" in formula and "hold" in formula


def _is_non_blocking_fail_check(check):
    # type: (Dict[str, Any]) -> bool
    name = str((check or {}).get("check") or "")
    if name in NON_BLOCKING_FAIL_CHECKS:
        return True
    formula = str((check or {}).get("formula") or "").lower()
    return "interest-only approximation" in formula or "unaccounted" in str((check or {}).get("difference") or "").lower()


def summarize_math_checks(checks, metrics=None):
    # type: (Optional[List[Dict[str, Any]]], Optional[Dict[str, Any]]) -> Dict[str, Any]
    checks = checks or []
    metrics = metrics or {}
    summary = {"pass": 0, "fail": 0, "warn": 0, "info": 0, "ignored": 0, "total": len(checks), "blocking": []}
    for check in checks:
        status = str((check or {}).get("status") or "").lower()
        ignored = status == "fail" and _is_ignored_hold_alias_check(check, metrics)
        if ignored:
            summary["ignored"] += 1
            summary["info"] += 1
            continue
        if status == "fail" and _is_non_blocking_fail_check(check):
            summary["warn"] += 1
            continue
        if status in ("pass", "fail", "warn", "info"):
            summary[status] += 1
        if status == "fail":
            summary["blocking"].append({
                "check": check.get("check"),
                "difference": check.get("difference"),
                "formula": check.get("formula"),
            })
    return summary


def _parse_confidence(value, fallback):
    # type: (Any, float) -> float
    if value is None:
        return fallback
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return fallback
    return max(0.0, min(100.0, parsed))


def _critical_confidence_score(missing, unverified, conflicted, bad):
    # type: (int, int, int, int) -> float
    # Confidence should answer: "Can I trust the key underwriting facts?"
    # The broad verifier may audit 100+ narrative and optional fields, so its
    # raw score is useful color but too noisy to be the base deal confidence.
    score = 100.0
    score -= missing * 10
    score -= unverified * 5
    score -= conflicted * 18
    score -= bad * 14
    return max(0.0, min(100.0, score))


def _blend_confidence(critical_score, verification_score, verification_complete):
    # type: (float, float, bool) -> float
    if verification_complete:
        return critical_score * 0.85 + verification_score * 0.15
    return critical_score * 0.9 + verification_score * 0.1


def assess_data_quality(metrics, math_checks=None, require_verified=True):
    # type: (Optional[Dict[str, Any]], Optional[List[Dict[str, Any]]], bool) -> Dict[str, Any]
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

    critical = []  # type: List[Dict[str, Any]]
    missing = 0
    unverified = 0
    conflicted = 0
    bad = 0

    for canonical_path, label, fallback_paths in CRITICAL_FIELDS:
        actual_path, value = _pick_present_path(metrics, canonical_path, fallback_paths)
        present = _present(value)
        prov = provenance.get(actual_path) or {}
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
        elif status in REVIEW_STATUSES:
            severity = "review"
            reason = "needs source review"
            unverified += 1
        elif require_verified and not verified:
            severity = "review"
            reason = "not verified against source"
            unverified += 1

        critical.append({
            "path": canonical_path,
            "actual_path": actual_path,
            "label": label,
            "present": present,
            "status": status,
            "verified": verified,
            "severity": severity,
            "reason": reason,
        })

    math_summary = summarize_math_checks(math_checks, metrics)
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

    broad_verification_score = _parse_confidence(
        verification_confidence,
        35.0 if not verification_complete else 70.0,
    )
    critical_score = _critical_confidence_score(missing, unverified, conflicted, bad)
    confidence_score = _blend_confidence(critical_score, broad_verification_score, verification_complete)

    # Deterministic math failures are high-signal and should still gate trust.
    confidence_score -= math_summary["fail"] * 12
    confidence_score -= math_summary["warn"] * 1

    # If a deal is only provisional because verification has not finished, keep
    # it visibly below the verified range without claiming the extraction is bad.
    if require_verified and not verification_complete:
        confidence_score = min(confidence_score, 65.0)

    # Active blockers must remain obvious, but do not let a noisy broad verifier
    # turn otherwise reviewable data into a single-digit score by itself.
    if missing or bad:
        confidence_score = min(confidence_score, 60.0)
    if conflicted or has_math_failures:
        confidence_score = min(confidence_score, 55.0)

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
        "confidence_breakdown": {
            "critical_field_score": round(critical_score, 1),
            "broad_verification_score": round(broad_verification_score, 1),
            "math_failures": math_summary["fail"],
            "math_warnings": math_summary["warn"],
        },
    }

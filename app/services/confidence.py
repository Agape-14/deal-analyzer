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

# These are decision-useful, but they are not always stated in an offering memo
# or proforma in the exact field shape the app expects. They should create a
# review queue item, not make the whole deal look unreadable.
SUPPORTING_REVIEW_FIELDS = {
    "deal_structure.hold_period_years",
    "target_returns.target_equity_multiple",
    "target_returns.target_cash_on_cash",
    "financial_projections.stabilized_noi",
    "financial_projections.avg_rent_per_unit",
    "financial_projections.occupancy_assumption",
}

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


def _has_any_return_metric(metrics):
    # type: (Dict[str, Any]) -> bool
    paths = (
        "target_returns.target_irr",
        "target_returns.net_irr",
        "target_returns.target_cash_on_cash",
        "target_returns.distribution_yield",
        "target_returns.hold_scenario.cash_on_cash_return",
        "target_returns.sale_scenario.sale_irr",
    )
    return any(_present(_get_path(metrics, path)) for path in paths)


def _is_supporting_field(path, metrics):
    # type: (str, Dict[str, Any]) -> bool
    if path in SUPPORTING_REVIEW_FIELDS:
        return True
    if path == "target_returns.target_irr" and _has_any_return_metric(metrics):
        # If another return metric exists, a missing/unverifiable target_irr is
        # a mapping problem to review, not proof that the deal cannot be read.
        return True
    return False


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


def _critical_confidence_score(missing, unverified, conflicted, bad, review_only):
    # type: (int, int, int, int, int) -> float
    # Confidence should answer: "Can I trust the key underwriting facts?"
    # The broad verifier may audit 100+ narrative and optional fields, so its
    # raw score is useful color but too noisy to be the base deal confidence.
    score = 100.0
    score -= missing * 12
    score -= unverified * 4
    score -= conflicted * 20
    score -= bad * 16
    score -= review_only * 2
    return max(0.0, min(100.0, score))


def _blend_confidence(critical_score, verification_score, verification_complete):
    # type: (float, float, bool) -> float
    if verification_complete:
        return critical_score * 0.9 + verification_score * 0.1
    return critical_score * 0.95 + verification_score * 0.05


def _issue(severity, label, detail, action=None, count=None):
    # type: (str, str, str, Optional[str], Optional[int]) -> Dict[str, Any]
    item = {"severity": severity, "label": label, "detail": detail}
    if action:
        item["action"] = action
    if count is not None:
        item["count"] = count
    return item


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
    review_only = 0

    for canonical_path, label, fallback_paths in CRITICAL_FIELDS:
        actual_path, value = _pick_present_path(metrics, canonical_path, fallback_paths)
        present = _present(value)
        prov = provenance.get(actual_path) or {}
        status = str(prov.get("status") or ("extracted" if present else "missing")).lower()
        source = str(prov.get("source") or "").lower()
        verified = status in VERIFIED_STATUSES or source == "manual"
        conflict = bool(prov.get("conflict"))
        supporting = _is_supporting_field(canonical_path, metrics)

        severity = "ok"
        reason = None
        if not present:
            if supporting:
                severity = "review"
                reason = "supporting field missing"
                review_only += 1
            else:
                severity = "blocker"
                reason = "missing"
                missing += 1
        elif conflict:
            severity = "blocker"
            reason = "conflicting source values"
            conflicted += 1
        elif status in BAD_STATUSES:
            if supporting:
                severity = "review"
                reason = status
                review_only += 1
            else:
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
    pipeline = metrics.get("_pipeline") if isinstance(metrics.get("_pipeline"), dict) else {}
    pipeline_failed = str((pipeline or {}).get("status") or "").lower() == "failed"
    has_math_failures = math_summary["fail"] > 0
    has_blockers = missing > 0 or conflicted > 0 or bad > 0 or has_math_failures or pipeline_failed
    has_review_items = unverified > 0 or review_only > 0
    verification_complete = bool(verified_at)

    if pipeline_failed:
        stage = "pipeline_failed"
    elif conflicted:
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
    critical_score = _critical_confidence_score(missing, unverified, conflicted, bad, review_only)
    confidence_score = _blend_confidence(critical_score, broad_verification_score, verification_complete)

    # Deterministic math failures are high-signal and should still gate trust.
    confidence_score -= math_summary["fail"] * 12
    confidence_score -= math_summary["warn"] * 1

    # If a deal is only provisional because verification has not finished, keep
    # it visibly below the verified range without claiming the extraction is bad.
    if require_verified and not verification_complete:
        confidence_score = min(confidence_score, 65.0)
    if pipeline_failed:
        confidence_score = min(confidence_score, 55.0)

    # Active blockers must remain obvious, but do not let a noisy broad verifier
    # turn otherwise reviewable data into a single-digit score by itself.
    if missing or bad:
        confidence_score = min(confidence_score, 70.0)
    if conflicted or has_math_failures:
        confidence_score = min(confidence_score, 60.0)

    confidence_score = max(0, min(100, round(confidence_score, 1)))
    confidence_explanations = []
    next_actions = []

    if pipeline_failed:
        error = str((pipeline or {}).get("error") or (pipeline or {}).get("last_error") or "The last pipeline run did not finish.")
        confidence_explanations.append(
            _issue(
                "blocker",
                "Pipeline did not finish",
                error[:420],
                "Fix the provider/API issue, then re-run the pipeline.",
            )
        )
        next_actions.append("Re-run the pipeline after the provider/API issue is resolved.")
    if missing:
        labels = [c["label"] for c in critical if c.get("reason") == "missing"][:4]
        confidence_explanations.append(
            _issue(
                "blocker",
                "Missing critical source values",
                ", ".join(labels) if labels else "One or more critical values were not found.",
                "Upload the missing source document or enter the value manually.",
                missing,
            )
        )
        next_actions.append("Resolve missing critical fields in the review queue.")
    if conflicted:
        labels = [c["label"] for c in critical if c.get("reason") == "conflicting source values"][:4]
        confidence_explanations.append(
            _issue(
                "blocker",
                "Conflicting source values",
                ", ".join(labels) if labels else "The same metric has competing source values.",
                "Choose the trusted source or edit the value.",
                conflicted,
            )
        )
        next_actions.append("Resolve source conflicts before trusting the score.")
    if bad:
        labels = [c["label"] for c in critical if c.get("severity") == "blocker" and c.get("reason") in BAD_STATUSES][:4]
        confidence_explanations.append(
            _issue(
                "blocker",
                "Incorrect source values flagged",
                ", ".join(labels) if labels else "A verifier marked critical values wrong or missing.",
                "Correct the value or confirm the source.",
                bad,
            )
        )
    if has_math_failures:
        confidence_explanations.append(
            _issue(
                "blocker",
                "Math checks do not reconcile",
                f"{math_summary['fail']} deterministic check{'s' if math_summary['fail'] != 1 else ''} still fail.",
                "Review the input values used by the failed checks.",
                math_summary["fail"],
            )
        )
        next_actions.append("Fix or approve the failed math checks.")
    if has_review_items:
        confidence_explanations.append(
            _issue(
                "warning",
                "Some values still need analyst review",
                f"{unverified + review_only} source-backed value{'s' if (unverified + review_only) != 1 else ''} need confirmation.",
                "Confirm the values in the review queue when they are acceptable.",
                unverified + review_only,
            )
        )
    if require_verified and not verification_complete:
        confidence_explanations.append(
            _issue(
                "warning",
                "Source verification has not completed",
                "The score is provisional until extraction, verification, math checks, and scoring all finish.",
                "Run the full pipeline.",
            )
        )
        next_actions.append("Run the full pipeline.")
    if math_summary["warn"]:
        confidence_explanations.append(
            _issue(
                "info",
                "Analyst cautions remain",
                f"{math_summary['warn']} non-blocking check{'s' if math_summary['warn'] != 1 else ''} should be reviewed.",
                "Review warnings before investment committee use.",
                math_summary["warn"],
            )
        )
    if not confidence_explanations:
        confidence_explanations.append(
            _issue(
                "success",
                "Ready to trust",
                "Critical fields are verified and blocking math checks are clear.",
            )
        )

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
            "review_only": review_only,
            "verified": len(CRITICAL_FIELDS) - missing - unverified - conflicted - bad - review_only,
        },
        "math_summary": math_summary,
        "confidence_breakdown": {
            "critical_field_score": round(critical_score, 1),
            "broad_verification_score": round(broad_verification_score, 1),
            "math_failures": math_summary["fail"],
            "math_warnings": math_summary["warn"],
        },
        "confidence_explanations": confidence_explanations,
        "next_actions": next_actions,
    }

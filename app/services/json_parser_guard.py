"""Runtime guard for document-review JSON object shapes.

The extraction and verification code expects Claude JSON responses and stored
deal metrics to be dictionaries. Occasionally Claude returns a JSON object
double-encoded as a string, or older failed runs leave metrics or individual
metric sections stored in that shape. That is valid JSON, but it breaks
review/merge code with errors like "'str' object has no attribute 'keys'".
This guard normalizes those shapes before document review touches them.
"""

from __future__ import annotations

import json
import re
from typing import Any, Callable

METRIC_SECTIONS = {
    "deal_structure",
    "target_returns",
    "project_details",
    "construction_costs",
    "financial_projections",
    "market_location",
    "risk_assessment",
    "underwriting_checks",
    "sponsor_evaluation",
    "market_research",
}

DICT_META_KEYS = {
    "_provenance",
    "_verification",
    "_locks",
    "_math_checks",
    "_pipeline",
    "_canonical_returns",
    "_data_quality",
    "_review_resolutions",
    "_document_review_cache",
    "_verification_cache",
}

LIST_META_KEYS = {
    "validation_flags",
    "_extraction_history",
    "_field_history",
    "_shape_errors",
}

NUMERIC_FIELDS_BY_SECTION = {
    "deal_structure": {
        "minimum_investment",
        "total_equity_required",
        "total_project_cost",
        "construction_loan_amount",
        "permanent_loan_amount",
        "debt_amount",
        "ltv",
        "interest_rate",
        "hold_period_years",
        "preferred_return",
        "fees_dev_fee",
        "fees_asset_mgmt",
        "fees_acquisition",
        "fees_disposition",
        "fees_construction_mgmt",
        "gp_equity_coinvest_pct",
        "gp_cash_at_risk",
    },
    "target_returns": {
        "target_irr",
        "target_equity_multiple",
        "target_cash_on_cash",
        "target_avg_annual_return",
        "projected_profit",
        "gross_irr",
        "net_irr",
        "gross_equity_multiple",
        "net_equity_multiple",
        "distribution_yield",
        "total_fee_drag",
    },
    "project_details": {
        "unit_count",
        "total_sqft",
        "price_per_unit",
        "price_per_sqft",
        "construction_duration_months",
        "renovation_timeline_months",
        "current_occupancy",
        "current_avg_rent",
        "proforma_avg_rent",
    },
    "construction_costs": {
        "total_project_cost",
        "total_project_cost_per_unit",
        "hard_costs_total",
        "hard_costs_per_unit",
        "hard_costs_per_sqft",
        "land_cost_total",
        "land_cost_per_unit",
        "soft_costs_total",
        "soft_costs_per_unit",
        "site_work_total",
        "contingency_total",
        "contingency_pct",
        "financing_costs_total",
        "developer_fee_total",
        "reserves_total",
    },
    "financial_projections": {
        "stabilized_noi",
        "entry_cap_rate",
        "exit_cap_rate",
        "avg_rent_per_unit",
        "avg_rent_per_sqft",
        "rent_growth_assumption",
        "occupancy_assumption",
        "operating_expense_ratio",
        "construction_budget",
        "land_cost",
        "soft_costs",
        "hard_costs",
        "contingency",
    },
    "market_location": {
        "market_population",
        "market_job_growth",
        "market_rent_growth",
        "market_vacancy_rate",
        "walk_score",
    },
    "risk_assessment": {
        "market_risk_score",
        "execution_risk_score",
        "financial_risk_score",
        "entitlement_risk_score",
        "developer_risk_score",
        "overall_risk_score",
    },
    "underwriting_checks": {
        "break_even_occupancy",
        "dscr",
        "yield_on_cost",
        "expense_growth_assumption",
        "replacement_cost_per_unit",
        "revenue_per_unit",
        "operating_expense_per_unit",
        "management_fee_pct",
        "reserves_per_unit",
    },
    "sponsor_evaluation": {
        "sponsor_full_cycle_deals",
        "alignment_score",
    },
}

NESTED_NUMERIC_FIELDS = {
    ("target_returns", "hold_scenario"): {
        "cash_on_cash_return",
        "priority_return",
        "annual_cash_flow_per_share",
        "distribution_yield",
    },
    ("target_returns", "sale_scenario"): {
        "assumed_sale_year",
        "assumed_hold_years",
        "sale_irr",
        "sale_equity_multiple",
        "projected_profit_on_sale",
        "exit_cap_rate",
    },
}


def _try_parse_json(value: Any) -> Any:
    parsed = value
    for _ in range(3):
        if not isinstance(parsed, str):
            break
        candidate = parsed.strip()
        if not candidate:
            return {}
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            return value
    return parsed


def _coerce_json_object(value: Any, *, context: str) -> dict:
    parsed = _try_parse_json(value)
    if parsed is None:
        return {}
    if isinstance(parsed, dict):
        return parsed
    raise ValueError(f"{context} returned {type(parsed).__name__}, expected a JSON object.")


def _coerce_json_list(value: Any) -> list:
    parsed = _try_parse_json(value)
    if parsed is None:
        return []
    return parsed if isinstance(parsed, list) else []


def _is_meaningful(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str) and not value.strip():
        return False
    if isinstance(value, (dict, list)) and not value:
        return False
    return True


def _preview(value: Any) -> str:
    text = str(value)
    return text[:120] + ("..." if len(text) > 120 else "")


def _coerce_number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, str):
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    text = value.strip()
    if not text:
        return None
    lowered = text.lower()
    if lowered in {"na", "n/a", "none", "null", "unknown", "not stated", "not provided", "-"}:
        return None

    negative = lowered.startswith("(") and lowered.endswith(")")
    cleaned = lowered.strip("()")
    cleaned = cleaned.replace("$", "").replace("%", "").replace(",", "").replace("x", "").strip()
    suffix_matches = re.findall(r"(-?\d+(?:\.\d+)?)\s*([kmb])\b", cleaned)
    if len(suffix_matches) == 1:
        number = float(suffix_matches[0][0])
        suffix = suffix_matches[0][1]
        multiplier = {"k": 1_000.0, "m": 1_000_000.0, "b": 1_000_000_000.0}[suffix]
        return -number * multiplier if negative else number * multiplier
    if len(suffix_matches) > 1:
        return None

    matches = re.findall(r"-?\d+(?:\.\d+)?", cleaned)
    if len(matches) != 1:
        return None
    try:
        number = float(matches[0])
        return -number if negative else number
    except ValueError:
        return None


def _coerce_numeric_value(container: dict, key: str, path: str, shape_errors: list[dict]) -> None:
    if key not in container:
        return
    value = container.get(key)
    number = _coerce_number(value)
    if number is not None:
        container[key] = int(number) if number.is_integer() else number
        return
    if _is_meaningful(value):
        shape_errors.append({
            "path": path,
            "type": type(value).__name__,
            "expected": "number",
            "value": _preview(value),
        })
        container[key] = None


def _coerce_numeric_fields(metrics: dict, shape_errors: list[dict]) -> None:
    for section, keys in NUMERIC_FIELDS_BY_SECTION.items():
        values = metrics.get(section)
        if not isinstance(values, dict):
            continue
        for key in keys:
            _coerce_numeric_value(values, key, f"{section}.{key}", shape_errors)

    for (section, nested_key), keys in NESTED_NUMERIC_FIELDS.items():
        parent = metrics.get(section)
        if not isinstance(parent, dict):
            continue
        nested = parent.get(nested_key)
        if not isinstance(nested, dict):
            continue
        for key in keys:
            _coerce_numeric_value(nested, key, f"{section}.{nested_key}.{key}", shape_errors)


def normalize_metrics_tree(value: Any, *, context: str = "Stored deal metrics") -> dict:
    """Normalize top-level metrics and nested metric sections in place.

    Known metric sections and dict metadata must be dictionaries. Known list
    metadata must be lists. Unknown scalar keys are left alone for normal API
    reads, but smart_merge filters them out before calling the legacy merge
    routine so it cannot treat a scalar as a section and call `.keys()` on it.
    """
    metrics = _coerce_json_object(value, context=context)
    shape_errors = list(metrics.get("_shape_errors") or []) if isinstance(metrics.get("_shape_errors"), list) else []

    for key in list(metrics.keys()):
        item = metrics.get(key)
        parsed = _try_parse_json(item)
        if isinstance(parsed, dict):
            metrics[key] = parsed
            continue
        if isinstance(parsed, list):
            metrics[key] = parsed
            continue
        if key in METRIC_SECTIONS or key in DICT_META_KEYS:
            if item not in (None, "", {}):
                shape_errors.append({"path": key, "type": type(item).__name__})
            metrics[key] = {}
        elif key in LIST_META_KEYS:
            if item not in (None, "", []):
                shape_errors.append({"path": key, "type": type(item).__name__})
            metrics[key] = []

    for key in METRIC_SECTIONS:
        if key not in metrics or metrics[key] is None:
            metrics[key] = {}
        elif not isinstance(metrics[key], dict):
            shape_errors.append({"path": key, "type": type(metrics[key]).__name__})
            metrics[key] = {}

    for key in DICT_META_KEYS:
        if key in metrics and not isinstance(metrics[key], dict):
            shape_errors.append({"path": key, "type": type(metrics[key]).__name__})
            metrics[key] = {}

    for key in LIST_META_KEYS:
        if key in metrics and not isinstance(metrics[key], list):
            shape_errors.append({"path": key, "type": type(metrics[key]).__name__})
            metrics[key] = []

    _coerce_numeric_fields(metrics, shape_errors)

    if shape_errors:
        metrics["_shape_errors"] = shape_errors[-20:]
    return metrics


def _split_merge_payload(value: Any, *, context: str) -> tuple[dict, dict]:
    """Return (safe_merge_payload, passthrough_scalars).

    data_integrity.smart_merge treats every top-level key as either metadata or
    a section. Older deals can contain unknown top-level scalar/list keys. If
    those keys reach the legacy merge function, it can still call `.keys()` on a
    string/list. We remove them for the merge and restore them afterward.
    """
    metrics = normalize_metrics_tree(value, context=context)
    merge_payload: dict[str, Any] = {}
    passthrough: dict[str, Any] = {}

    for key, item in metrics.items():
        if key in METRIC_SECTIONS or key in DICT_META_KEYS or key in LIST_META_KEYS:
            merge_payload[key] = item
        elif isinstance(item, dict):
            merge_payload[key] = item
        else:
            passthrough[key] = item
    return merge_payload, passthrough


def _restore_passthrough(merged: dict, existing_passthrough: dict, incoming_passthrough: dict) -> dict:
    restored = dict(merged)
    for key, value in existing_passthrough.items():
        if key not in restored and _is_meaningful(value):
            restored[key] = value
    for key, value in incoming_passthrough.items():
        if _is_meaningful(value):
            restored[key] = value
    return restored


def install_deal_verifier_json_guard() -> None:
    """Patch review-time parsing and metric-shape normalization at startup."""
    from app.services import canonical_metrics, data_integrity, deal_extractor, deal_scorer, deal_validator, deal_verifier, math_checker

    current_parse: Callable[[str], Any] = deal_verifier._parse_json_defensively
    if not getattr(current_parse, "_json_object_guard", False):
        def guarded_parse(text: str) -> dict:
            parsed = current_parse(text)
            return _coerce_json_object(parsed, context="Claude response")

        guarded_parse._json_object_guard = True  # type: ignore[attr-defined]
        deal_verifier._parse_json_defensively = guarded_parse

    current_post_process = deal_extractor._post_process_metrics
    if not getattr(current_post_process, "_metrics_tree_guard", False):
        def guarded_post_process(metrics: dict) -> None:
            normalize_metrics_tree(metrics, context="Extracted metrics")
            current_post_process(metrics)

        guarded_post_process._metrics_tree_guard = True  # type: ignore[attr-defined]
        deal_extractor._post_process_metrics = guarded_post_process

    current_smart_merge = data_integrity.smart_merge
    if not getattr(current_smart_merge, "_metrics_tree_guard", False):
        def guarded_smart_merge(existing, incoming, *args, **kwargs):
            existing_safe, existing_passthrough = _split_merge_payload(existing, context="Existing deal metrics")
            incoming_safe, incoming_passthrough = _split_merge_payload(incoming, context="Incoming extracted metrics")
            merged, changes = current_smart_merge(existing_safe, incoming_safe, *args, **kwargs)
            return _restore_passthrough(merged, existing_passthrough, incoming_passthrough), changes

        guarded_smart_merge._metrics_tree_guard = True  # type: ignore[attr-defined]
        data_integrity.smart_merge = guarded_smart_merge

    current_iter = data_integrity._iter_metric_fields
    if not getattr(current_iter, "_metrics_tree_guard", False):
        def guarded_iter_metric_fields(metrics):
            yield from current_iter(normalize_metrics_tree(metrics, context="Metric field iterator"))

        guarded_iter_metric_fields._metrics_tree_guard = True  # type: ignore[attr-defined]
        data_integrity._iter_metric_fields = guarded_iter_metric_fields

    current_quality_summary = data_integrity.quality_summary
    if not getattr(current_quality_summary, "_metrics_tree_guard", False):
        def guarded_quality_summary(metrics):
            return current_quality_summary(normalize_metrics_tree(metrics, context="Quality summary metrics"))

        guarded_quality_summary._metrics_tree_guard = True  # type: ignore[attr-defined]
        data_integrity.quality_summary = guarded_quality_summary

    current_staleness_flags = data_integrity.staleness_flags
    if not getattr(current_staleness_flags, "_metrics_tree_guard", False):
        def guarded_staleness_flags(metrics, documents, *args, **kwargs):
            return current_staleness_flags(normalize_metrics_tree(metrics, context="Staleness metrics"), documents, *args, **kwargs)

        guarded_staleness_flags._metrics_tree_guard = True  # type: ignore[attr-defined]
        data_integrity.staleness_flags = guarded_staleness_flags

    current_annotate = canonical_metrics.annotate_canonical_metrics
    if not getattr(current_annotate, "_metrics_tree_guard", False):
        def guarded_annotate(metrics):
            return current_annotate(normalize_metrics_tree(metrics, context="Canonical metrics input"))

        guarded_annotate._metrics_tree_guard = True  # type: ignore[attr-defined]
        canonical_metrics.annotate_canonical_metrics = guarded_annotate

    current_validate = deal_validator.validate_deal_metrics
    if not getattr(current_validate, "_metrics_tree_guard", False):
        def guarded_validate_deal_metrics(metrics, *args, **kwargs):
            return current_validate(normalize_metrics_tree(metrics, context="Validation metrics"), *args, **kwargs)

        guarded_validate_deal_metrics._metrics_tree_guard = True  # type: ignore[attr-defined]
        deal_validator.validate_deal_metrics = guarded_validate_deal_metrics

    current_math = math_checker.run_math_checks
    if not getattr(current_math, "_metrics_tree_guard", False):
        def guarded_run_math_checks(metrics, *args, **kwargs):
            return current_math(normalize_metrics_tree(metrics, context="Math check metrics"), *args, **kwargs)

        guarded_run_math_checks._metrics_tree_guard = True  # type: ignore[attr-defined]
        math_checker.run_math_checks = guarded_run_math_checks

    current_score = deal_scorer.score_deal
    if not getattr(current_score, "_metrics_tree_guard", False):
        def guarded_score_deal(metrics, *args, **kwargs):
            return current_score(normalize_metrics_tree(metrics, context="Scoring metrics"), *args, **kwargs)

        guarded_score_deal._metrics_tree_guard = True  # type: ignore[attr-defined]
        deal_scorer.score_deal = guarded_score_deal

    current_verify = deal_verifier.verify_deal_metrics
    if not getattr(current_verify, "_metrics_object_guard", False):
        async def guarded_verify_deal_metrics(deal, db) -> dict:
            deal.metrics = normalize_metrics_tree(deal.metrics, context="Stored deal metrics")
            result = await current_verify(deal, db)
            return _coerce_json_object(result, context="Verification result")

        guarded_verify_deal_metrics._metrics_object_guard = True  # type: ignore[attr-defined]
        deal_verifier.verify_deal_metrics = guarded_verify_deal_metrics

    try:
        from app.routers import deal_pipeline
    except Exception:
        return

    current_ensure = getattr(deal_pipeline, "_ensure_metrics_dict", None)
    if current_ensure and not getattr(current_ensure, "_metrics_tree_guard", False):
        def guarded_ensure_metrics_dict(value, context: str) -> dict:
            return normalize_metrics_tree(value, context=context)

        guarded_ensure_metrics_dict._metrics_tree_guard = True  # type: ignore[attr-defined]
        deal_pipeline._ensure_metrics_dict = guarded_ensure_metrics_dict

    deal_pipeline.score_deal = deal_scorer.score_deal
    deal_pipeline.validate_deal_metrics = deal_validator.validate_deal_metrics
    deal_pipeline.run_math_checks = math_checker.run_math_checks

    # deal_pipeline imports several functions directly. Rebind those route-level
    # names so startup/import order cannot bypass the guard.
    deal_pipeline.smart_merge = data_integrity.smart_merge
    deal_pipeline.quality_summary = data_integrity.quality_summary
    deal_pipeline.staleness_flags = data_integrity.staleness_flags
    deal_pipeline.annotate_canonical_metrics = canonical_metrics.annotate_canonical_metrics
    deal_pipeline.verify_deal_metrics = deal_verifier.verify_deal_metrics

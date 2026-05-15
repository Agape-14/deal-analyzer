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
    "_shape_errors",
    "_review_resolutions",
}

LIST_META_KEYS = {
    "validation_flags",
    "_extraction_history",
    "_field_history",
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
    from app.services import canonical_metrics, data_integrity, deal_extractor, deal_verifier

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

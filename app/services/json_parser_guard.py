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


def normalize_metrics_tree(value: Any, *, context: str = "Stored deal metrics") -> dict:
    """Normalize top-level metrics and nested metric sections in place.

    The top-level object and known metric sections must be dictionaries. If a
    known section is a JSON-encoded object string, parse it. If it is a plain
    string or other invalid shape, replace it with an empty dict and preserve a
    small audit note under `_shape_errors` instead of crashing the review run.
    """
    metrics = _coerce_json_object(value, context=context)
    shape_errors = list(metrics.get("_shape_errors") or []) if isinstance(metrics.get("_shape_errors"), list) else []

    for key in list(metrics.keys()):
        item = metrics.get(key)
        parsed = _try_parse_json(item)
        if isinstance(parsed, dict):
            metrics[key] = parsed
            continue
        if key in METRIC_SECTIONS or key in DICT_META_KEYS:
            if item not in (None, "", {}):
                shape_errors.append({"path": key, "type": type(item).__name__})
            metrics[key] = {}

    for key in METRIC_SECTIONS:
        if key not in metrics or metrics[key] is None:
            metrics[key] = {}
        elif not isinstance(metrics[key], dict):
            shape_errors.append({"path": key, "type": type(metrics[key]).__name__})
            metrics[key] = {}

    if shape_errors:
        metrics["_shape_errors"] = shape_errors[-20:]
    return metrics


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
            return current_smart_merge(
                normalize_metrics_tree(existing, context="Existing deal metrics"),
                normalize_metrics_tree(incoming, context="Incoming extracted metrics"),
                *args,
                **kwargs,
            )

        guarded_smart_merge._metrics_tree_guard = True  # type: ignore[attr-defined]
        data_integrity.smart_merge = guarded_smart_merge

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

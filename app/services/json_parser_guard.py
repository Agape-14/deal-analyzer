"""Runtime guard for document-review JSON object shapes.

The extraction and verification code expects Claude JSON responses and stored
deal metrics to be dictionaries. Occasionally Claude returns a JSON object
double-encoded as a string, or older failed runs leave metrics stored in that
shape. That is valid JSON, but it breaks downstream review code with errors
like "'str' object has no attribute 'keys'". This guard normalizes those shapes
before document review touches them.
"""

from __future__ import annotations

import json
from typing import Any, Callable


def _coerce_json_object(value: Any, *, context: str) -> dict:
    parsed = value
    for _ in range(3):
        if not isinstance(parsed, str):
            break
        candidate = parsed.strip()
        if not candidate:
            return {}
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"{context} returned a JSON string that could not be parsed into an object: {exc}"
            ) from exc

    if parsed is None:
        return {}
    if isinstance(parsed, dict):
        return parsed
    raise ValueError(f"{context} returned {type(parsed).__name__}, expected a JSON object.")


def install_deal_verifier_json_guard() -> None:
    """Patch verifier parsing and stored metrics normalization at startup."""
    from app.services import deal_verifier

    current_parse: Callable[[str], Any] = deal_verifier._parse_json_defensively
    if not getattr(current_parse, "_json_object_guard", False):
        def guarded_parse(text: str) -> dict:
            parsed = current_parse(text)
            return _coerce_json_object(parsed, context="Claude response")

        guarded_parse._json_object_guard = True  # type: ignore[attr-defined]
        deal_verifier._parse_json_defensively = guarded_parse

    current_verify = deal_verifier.verify_deal_metrics
    if not getattr(current_verify, "_metrics_object_guard", False):
        async def guarded_verify_deal_metrics(deal, db) -> dict:
            deal.metrics = _coerce_json_object(deal.metrics, context="Stored deal metrics")
            result = await current_verify(deal, db)
            return _coerce_json_object(result, context="Verification result")

        guarded_verify_deal_metrics._metrics_object_guard = True  # type: ignore[attr-defined]
        deal_verifier.verify_deal_metrics = guarded_verify_deal_metrics

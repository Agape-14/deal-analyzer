"""Runtime guard for Claude JSON parser responses.

The extraction and verification code expects Claude JSON responses to parse
into dictionaries. Occasionally Claude returns a JSON object double-encoded as
a string. That is valid JSON, but it breaks downstream merge/review code with
errors like "'str' object has no attribute 'keys'". This guard normalizes that
shape without changing the large verifier module in-place.
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
            break
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"{context} returned a JSON string that could not be parsed into an object: {exc}"
            ) from exc

    if isinstance(parsed, dict):
        return parsed
    raise ValueError(f"{context} returned {type(parsed).__name__}, expected a JSON object.")


def install_deal_verifier_json_guard() -> None:
    """Patch deal_verifier._parse_json_defensively to always return a dict."""
    from app.services import deal_verifier

    current: Callable[[str], Any] = deal_verifier._parse_json_defensively
    if getattr(current, "_json_object_guard", False):
        return

    def guarded_parse(text: str) -> dict:
        parsed = current(text)
        return _coerce_json_object(parsed, context="Claude response")

    guarded_parse._json_object_guard = True  # type: ignore[attr-defined]
    deal_verifier._parse_json_defensively = guarded_parse

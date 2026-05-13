"""Field-level extraction accuracy evaluation.

This module compares an extracted deal metrics payload against a human-verified
answer key. It is intentionally pure Python so it can be used in tests, a CLI,
an admin endpoint, or a future batch evaluation job without touching the live
pipeline.

Expected answer-key shape:

{
    "case_id": "capalina_hold_model",
    "fields": [
        {
            "path": "target_returns.target_irr",
            "expected": "17.0%",
            "type": "pct",
            "tolerance": 0.1,
            "critical": true,
            "aliases": ["target_returns.net_irr"]
        }
    ]
}
"""

from __future__ import annotations

import math
import re
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence, Tuple

FieldSpec = Mapping[str, Any]
Metrics = Mapping[str, Any]

NUMERIC_TYPES = {"money", "pct", "percentage", "multiple", "integer", "number"}
DEFAULT_TOLERANCE = {
    "money": 1.0,
    "pct": 0.1,
    "percentage": 0.1,
    "multiple": 0.01,
    "integer": 0.0,
    "number": 0.0,
}
TRUTHY = {"true", "1", "yes", "y"}
FALSY = {"false", "0", "no", "n"}


def evaluate_answer_key(metrics: Metrics, answer_key: Mapping[str, Any]) -> Dict[str, Any]:
    """Compare extracted metrics with a human answer key.

    Returns a JSON-serializable report with per-field results plus aggregate
    accuracy. A report passes only when all critical required fields match.
    """

    fields = answer_key.get("fields") or []
    if not isinstance(fields, Sequence) or isinstance(fields, (str, bytes)):
        raise ValueError("answer_key.fields must be a list of field specs")

    results = [compare_field(metrics, field) for field in fields]
    scored = [r for r in results if r["status"] != "skipped"]
    critical = [r for r in scored if r["critical"]]
    failed = [r for r in scored if r["status"] in {"missing", "mismatch"}]
    critical_failed = [r for r in failed if r["critical"]]

    matched = sum(1 for r in scored if r["status"] == "match")
    mismatched = sum(1 for r in scored if r["status"] == "mismatch")
    missing = sum(1 for r in scored if r["status"] == "missing")
    skipped = sum(1 for r in results if r["status"] == "skipped")

    return {
        "case_id": answer_key.get("case_id"),
        "passed": len(critical_failed) == 0,
        "accuracy": _percent(matched, len(scored)),
        "critical_accuracy": _percent(sum(1 for r in critical if r["status"] == "match"), len(critical)),
        "summary": {
            "total": len(results),
            "scored": len(scored),
            "matched": matched,
            "mismatched": mismatched,
            "missing": missing,
            "skipped": skipped,
            "critical_failed": len(critical_failed),
        },
        "failed_fields": failed,
        "results": results,
    }


def compare_field(metrics: Metrics, field: FieldSpec) -> Dict[str, Any]:
    """Compare one answer-key field with the extracted metrics payload."""

    path = str(field.get("path") or "").strip()
    if not path:
        raise ValueError("field spec is missing path")

    expected = field.get("expected")
    required = bool(field.get("required", True))
    critical = bool(field.get("critical", True))
    aliases = _aliases(field)
    field_type = _field_type(field, expected)
    actual_path, actual = _first_present(metrics, (path, *aliases))
    provenance = _provenance(metrics, actual_path)

    base = {
        "path": path,
        "actual_path": actual_path,
        "label": field.get("label") or _humanize(path),
        "type": field_type,
        "expected": expected,
        "actual": actual,
        "critical": critical,
        "source_status": provenance.get("status") if provenance else None,
        "source": _source_label(provenance),
    }

    if not _present(expected) and not required:
        return {**base, "status": "skipped", "message": "No expected value supplied for optional field."}

    if not _present(actual):
        status = "missing" if required else "skipped"
        return {**base, "status": status, "message": "Extracted value is missing."}

    ok, details = _compare_values(
        actual,
        expected,
        field_type,
        tolerance=field.get("tolerance"),
        relative_tolerance=field.get("relative_tolerance"),
    )
    return {
        **base,
        "status": "match" if ok else "mismatch",
        **details,
    }


def _compare_values(
    actual: Any,
    expected: Any,
    field_type: str,
    *,
    tolerance: Any = None,
    relative_tolerance: Any = None,
) -> Tuple[bool, Dict[str, Any]]:
    if field_type in NUMERIC_TYPES:
        actual_num = _number(actual)
        expected_num = _number(expected)
        if actual_num is None or expected_num is None:
            return False, {"message": "Could not parse numeric comparison."}
        actual_num, expected_num = _align_percent_units(actual_num, expected_num, field_type)
        tolerance_num = _number(tolerance)
        if tolerance_num is None:
            tolerance_num = DEFAULT_TOLERANCE.get(field_type, 0.0)
        relative_tolerance_num = _number(relative_tolerance)
        difference = abs(actual_num - expected_num)
        relative_error = difference / abs(expected_num) if expected_num else (0.0 if difference == 0 else math.inf)
        ok = difference <= tolerance_num
        if relative_tolerance_num is not None:
            ok = ok or relative_error <= relative_tolerance_num
        return ok, {
            "actual_normalized": actual_num,
            "expected_normalized": expected_num,
            "difference": round(difference, 6),
            "relative_error": None if not math.isfinite(relative_error) else round(relative_error, 6),
            "tolerance": tolerance_num,
            "relative_tolerance": relative_tolerance_num,
            "message": "Matched within tolerance." if ok else "Extracted value differs from answer key.",
        }

    if field_type == "bool":
        actual_bool = _bool(actual)
        expected_bool = _bool(expected)
        ok = actual_bool is not None and actual_bool == expected_bool
        return ok, {"message": "Matched." if ok else "Boolean value differs from answer key."}

    actual_text = _normalize_text(actual)
    expected_text = _normalize_text(expected)
    ok = actual_text == expected_text
    return ok, {
        "actual_normalized": actual_text,
        "expected_normalized": expected_text,
        "message": "Matched." if ok else "Text value differs from answer key.",
    }


def _first_present(metrics: Metrics, paths: Iterable[str]) -> Tuple[str, Any]:
    first = ""
    for path in paths:
        if not first:
            first = path
        value = _get_path(metrics, path)
        if _present(value):
            return path, value
    return first, None


def _get_path(data: Mapping[str, Any], path: str) -> Any:
    current: Any = data
    for part in path.split("."):
        if not isinstance(current, Mapping):
            return None
        current = current.get(part)
    return current


def _provenance(metrics: Metrics, path: str) -> Dict[str, Any]:
    provenance = metrics.get("_provenance") if isinstance(metrics, Mapping) else None
    if isinstance(provenance, Mapping):
        value = provenance.get(path)
        if isinstance(value, Mapping):
            return dict(value)
    return {}


def _present(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    return value != []


def _field_type(field: FieldSpec, expected: Any) -> str:
    explicit = str(field.get("type") or field.get("format") or "").lower().strip()
    if explicit:
        return "pct" if explicit == "percentage" else explicit
    path = str(field.get("path") or "").lower()
    if any(token in path for token in ("irr", "rate", "ltv", "yield", "return", "occupancy", "margin", "pct")):
        return "pct"
    if any(token in path for token in ("amount", "cost", "noi", "rent", "investment", "equity", "debt", "price")):
        return "money"
    if "multiple" in path or "dscr" in path:
        return "multiple"
    if isinstance(expected, bool):
        return "bool"
    if isinstance(expected, (int, float)):
        return "number"
    return "text"


def _aliases(field: FieldSpec) -> Tuple[str, ...]:
    aliases = field.get("aliases") or field.get("actual_paths") or ()
    if isinstance(aliases, str):
        return (aliases,)
    if isinstance(aliases, Sequence):
        return tuple(str(alias) for alias in aliases if str(alias).strip())
    return ()


def _number(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        return float(value)
    if not isinstance(value, str):
        return None

    text = value.strip().lower().replace(",", "")
    if not text:
        return None
    text = text.replace("$", "").replace("%", "").replace("x", "")
    text = re.sub(r"\b(dollars?|usd|per unit|psf)\b", "", text).strip()
    match = re.match(r"^(-?\d+(?:\.\d+)?)\s*(k|m|mm|b|bn|million|billion)?$", text)
    if not match:
        return None
    amount = float(match.group(1))
    suffix = match.group(2) or ""
    multiplier = {
        "k": 1_000,
        "m": 1_000_000,
        "mm": 1_000_000,
        "million": 1_000_000,
        "b": 1_000_000_000,
        "bn": 1_000_000_000,
        "billion": 1_000_000_000,
    }.get(suffix, 1)
    return amount * multiplier


def _align_percent_units(actual: float, expected: float, field_type: str) -> Tuple[float, float]:
    if field_type not in {"pct", "percentage"}:
        return actual, expected
    if 0 <= actual <= 1 and expected > 1:
        actual *= 100
    elif 0 <= expected <= 1 and actual > 1:
        expected *= 100
    return actual, expected


def _bool(value: Any) -> Optional[bool]:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in TRUTHY:
            return True
        if normalized in FALSY:
            return False
    return None


def _normalize_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip().lower()


def _source_label(provenance: Mapping[str, Any]) -> Optional[str]:
    if not provenance:
        return None
    doc = provenance.get("source_doc_name")
    page = provenance.get("source_page")
    if doc and page:
        return f"{doc} p.{page}"
    return str(doc) if doc else None


def _humanize(path: str) -> str:
    return path.split(".")[-1].replace("_", " ").title()


def _percent(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 100.0
    return round((numerator / denominator) * 100, 1)

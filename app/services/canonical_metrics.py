"""Canonical metric selection helpers.

These helpers keep display/API/export choices aligned with the product labels.
A field labeled "Target IRR" should prefer target_returns.target_irr and only
fall back to investor net IRR when the target IRR is absent or explicitly bad.
"""

from typing import Any, Dict, Iterable, Optional

BAD_STATUSES = {"wrong", "missing", "unverifiable", "stale", "math_failed"}
REVIEWED_STATUSES = {"manual", "confirmed", "calculated"}


def get_path(data: Dict[str, Any] | None, path: str) -> Any:
    cur: Any = data or {}
    for part in path.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def present(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    return value != []


def bad_source(provenance: Optional[Dict[str, Any]]) -> bool:
    if not isinstance(provenance, dict):
        return False
    status = str(provenance.get("status") or "").lower()
    conflict = provenance.get("conflict")
    return status in BAD_STATUSES or bool(conflict)


def pick_metric(metrics: Dict[str, Any] | None, paths: Iterable[str]) -> Any:
    """Pick the first clean present metric, with reviewed values preferred."""
    metrics = metrics or {}
    provenance = metrics.get("_provenance") or {}
    candidates = []
    for path in paths:
        value = get_path(metrics, path)
        if present(value):
            prov = provenance.get(path) if isinstance(provenance, dict) else None
            candidates.append({"path": path, "value": value, "provenance": prov})

    if not candidates:
        return None

    clean = [candidate for candidate in candidates if not bad_source(candidate.get("provenance"))]
    reviewed = [
        candidate
        for candidate in clean
        if isinstance(candidate.get("provenance"), dict)
        and (
            candidate["provenance"].get("locked")
            or str(candidate["provenance"].get("source") or "").lower() == "manual"
            or str(candidate["provenance"].get("status") or "").lower() in REVIEWED_STATUSES
        )
    ]
    return (reviewed[0] if reviewed else clean[0] if clean else candidates[0])["value"]


def canonical_return_summary(metrics: Dict[str, Any] | None) -> Dict[str, Any]:
    """Return headline return metrics using one consistent rule."""
    return {
        "target_irr": pick_metric(metrics, ("target_returns.target_irr", "target_returns.net_irr")),
        "target_equity_multiple": pick_metric(
            metrics,
            ("target_returns.target_equity_multiple", "target_returns.net_equity_multiple"),
        ),
        "cash_on_cash": pick_metric(
            metrics,
            ("target_returns.target_cash_on_cash", "target_returns.distribution_yield"),
        ),
    }

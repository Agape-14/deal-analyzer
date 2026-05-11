"""Canonical metric selection helpers.

These helpers keep display/API/export choices aligned with the product labels.
A field labeled "Target IRR" must reflect the deal's stated primary strategy.
If the documents describe a long-term hold as the plan and also include a
hypothetical sale case, the hold yield is the headline metric and sale IRR stays
in the sale scenario.
"""

from typing import Any, Dict, Iterable, Optional

BAD_STATUSES = {"wrong", "missing", "unverifiable", "stale", "math_failed"}
REVIEWED_STATUSES = {"manual", "confirmed", "calculated"}
HOLD_STRATEGIES = {"hold", "long_term_hold", "hold_with_sale_option"}
SALE_STRATEGIES = {"sale", "merchant_build", "sale_after_stabilization"}


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


def primary_strategy(metrics: Dict[str, Any] | None) -> str:
    """Resolve the deal's primary strategy from explicit labels and scenario text."""
    metrics = metrics or {}
    tr = metrics.get("target_returns") or {}
    ds = metrics.get("deal_structure") or {}
    raw = str(tr.get("primary_strategy") or "").strip().lower().replace("-", "_").replace(" ", "_")

    sale = tr.get("sale_scenario") if isinstance(tr.get("sale_scenario"), dict) else {}
    hold = tr.get("hold_scenario") if isinstance(tr.get("hold_scenario"), dict) else {}
    sale_text = " ".join(
        str(sale.get(key) or "")
        for key in ("description", "notes", "assumptions")
    ).lower()
    hold_text = " ".join(
        str(value or "")
        for value in (
            hold.get("description"),
            hold.get("notes"),
            hold.get("assumptions"),
            ds.get("exit_strategies"),
            ds.get("business_plan"),
            ds.get("investment_strategy"),
            ds.get("investment_term_years"),
            ds.get("hold_period_years"),
        )
    ).lower()
    sale_is_hypothetical = sale.get("is_hypothetical") is True or any(
        phrase in sale_text
        for phrase in (
            "hypothetical",
            "theoretical",
            "for example",
            "illustrative",
            "for illustrative purposes",
            "illustration",
            "not the business plan",
            "not intended strategy",
            "not preferred plan",
            "business plan is to hold",
            "preferred plan is to hold",
            "example purposes",
        )
    )
    hold_is_stated = raw in HOLD_STRATEGIES or any(
        phrase in hold_text
        for phrase in (
            "long-term hold",
            "long term hold",
            "hold long-term",
            "hold long term",
            "hold for cash flow",
            "business plan is to hold",
            "preferred plan is to hold",
            "preferred plan",
            "preferred strategy",
            "base plan",
            "base case",
            "primary plan",
            "refi and hold",
            "refinance and hold",
        )
    )

    if hold_is_stated and (sale_is_hypothetical or present(sale)):
        return "hold_with_sale_option"
    if raw in HOLD_STRATEGIES or hold_is_stated:
        return "hold"
    if raw in SALE_STRATEGIES and not sale_is_hypothetical:
        return "sale"
    if sale_is_hypothetical and present(hold):
        return "hold_with_sale_option"
    if raw:
        return raw
    return "unknown"


def is_hold_strategy(metrics: Dict[str, Any] | None) -> bool:
    return primary_strategy(metrics) in {"hold", "hold_with_sale_option"}


def canonical_return_summary(metrics: Dict[str, Any] | None) -> Dict[str, Any]:
    """Return headline return metrics using one consistent strategy-aware rule."""
    strategy = primary_strategy(metrics)

    if strategy in {"hold", "hold_with_sale_option"}:
        return {
            "primary_strategy": strategy,
            "target_irr": pick_metric(
                metrics,
                (
                    "target_returns.hold_scenario.cash_on_cash_return",
                    "target_returns.target_cash_on_cash",
                    "target_returns.hold_scenario.distribution_yield",
                    "target_returns.distribution_yield",
                    "target_returns.hold_scenario.priority_return",
                    "deal_structure.preferred_return",
                ),
            ),
            "target_equity_multiple": pick_metric(
                metrics,
                (
                    "target_returns.target_equity_multiple",
                    "target_returns.net_equity_multiple",
                    "target_returns.sale_scenario.sale_equity_multiple",
                ),
            ),
            "cash_on_cash": pick_metric(
                metrics,
                (
                    "target_returns.hold_scenario.cash_on_cash_return",
                    "target_returns.target_cash_on_cash",
                    "target_returns.hold_scenario.distribution_yield",
                    "target_returns.distribution_yield",
                ),
            ),
        }

    if strategy == "sale":
        return {
            "primary_strategy": strategy,
            "target_irr": pick_metric(
                metrics,
                (
                    "target_returns.net_irr",
                    "target_returns.sale_scenario.sale_irr",
                    "target_returns.target_irr",
                    "target_returns.gross_irr",
                ),
            ),
            "target_equity_multiple": pick_metric(
                metrics,
                (
                    "target_returns.net_equity_multiple",
                    "target_returns.sale_scenario.sale_equity_multiple",
                    "target_returns.target_equity_multiple",
                    "target_returns.gross_equity_multiple",
                ),
            ),
            "cash_on_cash": pick_metric(
                metrics,
                ("target_returns.target_cash_on_cash", "target_returns.distribution_yield"),
            ),
        }

    return {
        "primary_strategy": strategy,
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

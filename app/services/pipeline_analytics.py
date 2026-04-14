"""
Pipeline analytics — dashboard widgets.

All derived from the Deal table on the fly. No new columns, no history
table. If you want long-term trend data later, snapshot this into a
new `deal_pipeline_snapshots` table via a cron.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone


def pipeline_summary(deals: list) -> dict:
    """Compute a headline snapshot for the dashboard.

    Inputs: ORM Deal rows (not serialized dicts).

    Returns a flat dict ready to JSON-serialize; every field has a
    sensible zero value so the UI doesn't have to null-check.
    """
    now = datetime.now(timezone.utc)

    alive = [d for d in deals if getattr(d, "deleted_at", None) is None]

    total = len(alive)
    by_status = defaultdict(int)
    for d in alive:
        by_status[d.status or "reviewing"] += 1

    # Velocity: deals created per month over the last 6 full months.
    # Keyed YYYY-MM for chart stability. Uses proper month arithmetic so
    # neither Feb nor Dec get skipped by the 31-day approximation.
    velocity: list[dict] = []
    current_year, current_month = now.year, now.month
    for i in range(5, -1, -1):
        ym = current_month - i
        y = current_year
        while ym <= 0:
            ym += 12
            y -= 1
        month_start = datetime(y, ym, 1, tzinfo=timezone.utc)
        next_year = y + (1 if ym == 12 else 0)
        next_month_n = 1 if ym == 12 else ym + 1
        next_month = datetime(next_year, next_month_n, 1, tzinfo=timezone.utc)
        label = month_start.strftime("%Y-%m")
        n = sum(
            1
            for d in alive
            if d.created_at and month_start <= _to_utc(d.created_at) < next_month
        )
        velocity.append({"month": label, "count": n})

    # Win rate: committed / (committed + passed) over the last 12 months.
    window = now - timedelta(days=365)
    committed = sum(
        1
        for d in alive
        if d.status == "committed" and d.created_at and _to_utc(d.created_at) >= window
    )
    passed = sum(
        1
        for d in alive
        if d.status == "passed" and d.created_at and _to_utc(d.created_at) >= window
    )
    total_decided = committed + passed
    win_rate = (committed / total_decided * 100) if total_decided > 0 else None

    # Aging: deals stuck in an open state > 30 days since created_at.
    open_states = {"reviewing", "interested"}
    aging_cutoff = now - timedelta(days=30)
    aging = [
        {
            "id": d.id,
            "project_name": d.project_name,
            "status": d.status,
            "days_open": (now - _to_utc(d.created_at)).days if d.created_at else None,
        }
        for d in alive
        if d.status in open_states and d.created_at and _to_utc(d.created_at) < aging_cutoff
    ]
    aging.sort(key=lambda x: x["days_open"] or 0, reverse=True)

    # Capital at risk / exposure: minimum investment across deals we've
    # actually committed to or closed on.
    def _min_invest(d) -> float:
        ds = (d.metrics or {}).get("deal_structure") or {}
        v = ds.get("minimum_investment")
        try:
            return float(v) if v is not None else 0.0
        except (TypeError, ValueError):
            return 0.0

    committed_or_closed = [d for d in alive if d.status in {"committed", "closed"}]
    capital_deployed = sum(_min_invest(d) for d in committed_or_closed)

    pipeline_under_review = sum(_min_invest(d) for d in alive if d.status in open_states)

    # Average analyst score across scored deals
    scores = [
        (d.scores or {}).get("overall")
        for d in alive
        if isinstance(d.scores, dict) and (d.scores or {}).get("overall") is not None
    ]
    scores = [s for s in scores if isinstance(s, (int, float))]
    avg_score = sum(scores) / len(scores) if scores else None

    return {
        "total_deals": total,
        "by_status": dict(by_status),
        "velocity_6mo": velocity,
        "win_rate_pct_12mo": win_rate,
        "committed_12mo": committed,
        "passed_12mo": passed,
        "aging_deals": aging[:10],          # cap for UI
        "aging_count": len(aging),
        "capital_deployed": capital_deployed,
        "pipeline_under_review": pipeline_under_review,
        "avg_score": avg_score,
    }


def _to_utc(dt: datetime) -> datetime:
    """Normalize naive datetimes (SQLite stores them naive) to UTC-aware."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt

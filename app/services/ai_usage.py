"""Persistent AI token and cost ledger.

The in-memory operation log is useful for immediate debugging, but it is
not enough to answer operator questions like "what did this review cost?".
This module mirrors completed AI operations into the database, estimates
provider cost from token counts, and summarizes usage by deal.
"""

from __future__ import annotations

import os
from collections import defaultdict
from contextvars import ContextVar
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import select

from app.database import async_session
from app.models import AIUsageEvent, DealDocument

_CURRENT_DEAL_ID: ContextVar[int | None] = ContextVar("ai_usage_deal_id", default=None)


def current_ai_deal_id() -> int | None:
    return _CURRENT_DEAL_ID.get()


class ai_usage_context:
    """Attach a deal id to downstream AI calls made in the current task."""

    def __init__(self, deal_id: int | None):
        self.deal_id = deal_id
        self._token = None

    def __enter__(self):
        self._token = _CURRENT_DEAL_ID.set(self.deal_id)
        return self

    def __exit__(self, exc_type, exc, tb):
        if self._token is not None:
            _CURRENT_DEAL_ID.reset(self._token)
        return False


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def price_for_model(model: str | None) -> dict[str, float]:
    """Return estimated USD price per million tokens for a model.

    Defaults are intentionally configurable. If Anthropic changes pricing or
    the app points at a different provider, set these environment variables:

    - AI_OPUS_INPUT_PER_MTOK / AI_OPUS_OUTPUT_PER_MTOK
    - AI_SONNET_INPUT_PER_MTOK / AI_SONNET_OUTPUT_PER_MTOK
    - AI_HAIKU_INPUT_PER_MTOK / AI_HAIKU_OUTPUT_PER_MTOK
    """
    name = (model or "").lower()
    if "haiku" in name:
        return {
            "input_per_mtok": _env_float("AI_HAIKU_INPUT_PER_MTOK", 0.25),
            "output_per_mtok": _env_float("AI_HAIKU_OUTPUT_PER_MTOK", 1.25),
        }
    if "sonnet" in name:
        return {
            "input_per_mtok": _env_float("AI_SONNET_INPUT_PER_MTOK", 3.0),
            "output_per_mtok": _env_float("AI_SONNET_OUTPUT_PER_MTOK", 15.0),
        }
    return {
        "input_per_mtok": _env_float("AI_OPUS_INPUT_PER_MTOK", 5.0),
        "output_per_mtok": _env_float("AI_OPUS_OUTPUT_PER_MTOK", 25.0),
    }


def estimate_cost_usd(model: str | None, input_tokens: int | None, output_tokens: int | None) -> float:
    prices = price_for_model(model)
    input_cost = ((input_tokens or 0) / 1_000_000) * prices["input_per_mtok"]
    output_cost = ((output_tokens or 0) / 1_000_000) * prices["output_per_mtok"]
    return round(input_cost + output_cost, 6)


def _safe_int(value: Any) -> int | None:
    try:
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


async def _infer_deal_id_from_docs(meta: dict[str, Any]) -> int | None:
    docs = meta.get("docs") if isinstance(meta, dict) else None
    if not isinstance(docs, list):
        return None
    names = [str(item).strip() for item in docs if str(item or "").strip()]
    if not names:
        return None

    async with async_session() as db:
        result = await db.execute(select(DealDocument.deal_id).where(DealDocument.filename.in_(names)))
        deal_ids = {row[0] for row in result.all() if row[0] is not None}
    return next(iter(deal_ids)) if len(deal_ids) == 1 else None


async def persist_operation_usage(entry: Any) -> None:
    """Persist token usage from an operation_log entry.

    This is best-effort observability. It must never break extraction or
    verification, so callers should swallow errors around it.
    """
    model = getattr(entry, "model", None)
    input_tokens = _safe_int(getattr(entry, "input_tokens", None))
    output_tokens = _safe_int(getattr(entry, "output_tokens", None))
    if not model and input_tokens is None and output_tokens is None:
        return

    meta = dict(getattr(entry, "meta", None) or {})
    deal_id = getattr(entry, "deal_id", None) or current_ai_deal_id()
    if deal_id is None:
        deal_id = await _infer_deal_id_from_docs(meta)

    prices = price_for_model(model)
    estimated_cost = estimate_cost_usd(model, input_tokens, output_tokens)
    meta.setdefault("pricing", prices)
    if getattr(entry, "id", None):
        meta.setdefault("operation_log_id", getattr(entry, "id"))

    event = AIUsageEvent(
        deal_id=deal_id,
        operation=str(getattr(entry, "operation", "ai") or "ai"),
        model=model or "unknown",
        status=str(getattr(entry, "status", "unknown") or "unknown"),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        estimated_cost_usd=estimated_cost,
        duration_ms=_safe_int(getattr(entry, "duration_ms", None)),
        error_message=getattr(entry, "error_message", None),
        meta=meta,
    )
    async with async_session() as db:
        db.add(event)
        await db.commit()


def _event_to_dict(event: AIUsageEvent) -> dict[str, Any]:
    return {
        "id": event.id,
        "deal_id": event.deal_id,
        "operation": event.operation,
        "model": event.model,
        "status": event.status,
        "input_tokens": event.input_tokens or 0,
        "output_tokens": event.output_tokens or 0,
        "total_tokens": (event.input_tokens or 0) + (event.output_tokens or 0),
        "estimated_cost_usd": float(event.estimated_cost_usd or 0),
        "duration_ms": event.duration_ms,
        "error_message": event.error_message,
        "meta": event.meta or {},
        "created_at": event.created_at.isoformat() if event.created_at else None,
    }


async def summarize_usage(*, deal_id: int | None = None, limit: int = 100) -> dict[str, Any]:
    async with async_session() as db:
        q = select(AIUsageEvent).order_by(AIUsageEvent.created_at.desc(), AIUsageEvent.id.desc())
        if deal_id is not None:
            q = q.where(AIUsageEvent.deal_id == deal_id)
        result = await db.execute(q.limit(limit))
        events = result.scalars().all()

        today_start = datetime.combine(date.today(), datetime.min.time(), tzinfo=timezone.utc)
        today_q = select(AIUsageEvent)
        if deal_id is not None:
            today_q = today_q.where(AIUsageEvent.deal_id == deal_id)
        today_q = today_q.where(AIUsageEvent.created_at >= today_start)
        today_result = await db.execute(today_q)
        today_events = today_result.scalars().all()

    by_operation: dict[str, dict[str, Any]] = defaultdict(lambda: {
        "calls": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "estimated_cost_usd": 0.0,
    })
    for event in events:
        key = event.operation or "ai"
        bucket = by_operation[key]
        bucket["calls"] += 1
        bucket["input_tokens"] += event.input_tokens or 0
        bucket["output_tokens"] += event.output_tokens or 0
        bucket["estimated_cost_usd"] += float(event.estimated_cost_usd or 0)

    def totals(items: list[AIUsageEvent]) -> dict[str, Any]:
        return {
            "calls": len(items),
            "input_tokens": sum(item.input_tokens or 0 for item in items),
            "output_tokens": sum(item.output_tokens or 0 for item in items),
            "total_tokens": sum((item.input_tokens or 0) + (item.output_tokens or 0) for item in items),
            "estimated_cost_usd": round(sum(float(item.estimated_cost_usd or 0) for item in items), 4),
        }

    return {
        "deal_id": deal_id,
        "totals": totals(events),
        "today": totals(today_events),
        "by_operation": {
            key: {**value, "estimated_cost_usd": round(value["estimated_cost_usd"], 4)}
            for key, value in by_operation.items()
        },
        "events": [_event_to_dict(event) for event in events],
    }

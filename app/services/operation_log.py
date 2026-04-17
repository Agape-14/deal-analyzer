"""In-memory operation log for AI pipeline observability.

The production complaint that spawned this module: Claude returned
200 OK on the Anthropic side, but the UI showed "extraction failed"
with no actionable detail. The real error was buried under the
service restart cycle in Railway's log UI, which doesn't preserve
context across deploys.

This module keeps a ring buffer of the last N operations in memory.
Every extract / verify / chat call is wrapped in a context manager
that records: start time, duration, status, parameters, token counts
(if returned by the SDK), and — critically — the full exception type
+ message + traceback when something blows up. The `/api/admin/
diagnostics` endpoint exposes the buffer as JSON so an operator can
instantly see what went wrong without SSH-ing anywhere.

Design notes:

- In-memory only. Restart-of-process loses history. Acceptable because
  the whole point is "what happened in the last few minutes"; older
  errors should be addressed long before they age out of a 100-slot
  buffer. Persisting would add a migration and a hot write path for
  something that's purely diagnostic.
- Thread-safe via asyncio.Lock so concurrent requests don't scramble
  the buffer (uvicorn is single-process but uses a worker pool).
- Redacts the prompt/response bodies by default — they can be huge
  and may contain sensitive deal data. The operator can opt into a
  preview via `?full=1` on the endpoint.
"""

from __future__ import annotations

import asyncio
import logging
import time
import traceback
import uuid
from collections import deque
from contextlib import asynccontextmanager
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Optional


MAX_ENTRIES = 100

# Mirror every completed operation to the regular log stream so errors
# survive even when the in-memory buffer is wiped by a restart. Keeps
# the diagnostics UI as the primary surface but guarantees Railway
# Deploy Logs also has the exception if the buffer is lost.
logger = logging.getLogger("kenyon.ops")


@dataclass
class OperationEntry:
    """One recorded operation.

    Fields are JSON-serializable so the diagnostics endpoint can
    return them directly without a custom serializer.
    """

    id: str
    operation: str                         # e.g. "extract", "verify", "chat"
    started_at: str                        # ISO-8601 UTC
    duration_ms: Optional[int] = None      # filled in when complete
    status: str = "in_progress"            # "ok" | "error" | "in_progress"
    deal_id: Optional[int] = None
    doc_id: Optional[int] = None
    model: Optional[str] = None
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    error_class: Optional[str] = None
    error_message: Optional[str] = None
    traceback_excerpt: Optional[str] = None
    note: Optional[str] = None             # free-form stage marker
    meta: dict[str, Any] = field(default_factory=dict)

    # Optional large fields — kept separately so we can redact by default.
    prompt_preview: Optional[str] = None
    response_preview: Optional[str] = None


class _OperationLog:
    """Thread-safe ring buffer of operation entries."""

    def __init__(self, max_entries: int = MAX_ENTRIES) -> None:
        self._entries: deque[OperationEntry] = deque(maxlen=max_entries)
        self._lock = asyncio.Lock()

    async def append(self, entry: OperationEntry) -> None:
        async with self._lock:
            self._entries.append(entry)

    async def snapshot(self) -> list[OperationEntry]:
        async with self._lock:
            # Return newest first so the most recent errors are at the top.
            return list(reversed(self._entries))

    async def clear(self) -> None:
        async with self._lock:
            self._entries.clear()


_STORE = _OperationLog()


def _traceback_excerpt(exc: BaseException, max_frames: int = 8) -> str:
    """Format the last few frames of a traceback for display.

    Full tracebacks can be thousands of lines when SQLAlchemy or
    httpx is in the chain; we only need the bottom of the stack
    where the actual error occurred.
    """
    tb = traceback.format_exception(type(exc), exc, exc.__traceback__)
    # Each frame is typically 2 lines ("File …\n    code"). Keep the
    # last `max_frames * 2` lines plus the final exception summary.
    lines = "".join(tb).rstrip().split("\n")
    if len(lines) > max_frames * 2 + 2:
        lines = ["  [...]"] + lines[-(max_frames * 2 + 2):]
    return "\n".join(lines)


@asynccontextmanager
async def record(
    operation: str,
    *,
    deal_id: Optional[int] = None,
    doc_id: Optional[int] = None,
    model: Optional[str] = None,
    note: Optional[str] = None,
    meta: Optional[dict[str, Any]] = None,
) -> AsyncIterator[OperationEntry]:
    """Context manager that records an operation to the buffer.

    Usage:

        async with record("extract", deal_id=42, model="claude-opus-4-7") as op:
            result = await call_anthropic(...)
            op.input_tokens = result.usage.input_tokens
            op.output_tokens = result.usage.output_tokens
            op.response_preview = result.content[0].text[:500]

    On exception, the entry is stamped with error_class / _message /
    traceback_excerpt and re-raised. Callers can mutate the yielded
    `OperationEntry` in-flight to attach token counts, previews, etc.
    """
    entry = OperationEntry(
        id=uuid.uuid4().hex[:10],
        operation=operation,
        started_at=datetime.now(timezone.utc).isoformat(),
        deal_id=deal_id,
        doc_id=doc_id,
        model=model,
        note=note,
        meta=meta or {},
    )
    start = time.monotonic()
    try:
        yield entry
        entry.status = "ok"
    except BaseException as exc:
        entry.status = "error"
        entry.error_class = type(exc).__name__
        entry.error_message = str(exc) or repr(exc)
        entry.traceback_excerpt = _traceback_excerpt(exc)
        # Emit to stderr immediately so the record survives if the
        # worker dies before the buffer append below, OR if the
        # buffer is later wiped by a redeploy.
        logger.exception(
            "[op:%s] %s failed: %s",
            entry.id, operation, entry.error_message,
        )
        raise
    finally:
        entry.duration_ms = int((time.monotonic() - start) * 1000)
        # Even on the error path we want the entry in the buffer —
        # that's the whole point. `append` in a finally is safe here
        # because we don't swallow the exception.
        try:
            await _STORE.append(entry)
        except Exception:
            # Last-ditch: if even the buffer append fails, make sure
            # stderr has the record. Never let diagnostic plumbing
            # mask the original error.
            logger.error(
                "[op:%s] failed to append diagnostics entry: %r",
                entry.id, entry,
            )


async def snapshot_entries(include_full_bodies: bool = False) -> list[dict]:
    """Dump the buffer as plain dicts for JSON serialization.

    When `include_full_bodies` is False (default) we strip
    prompt_preview / response_preview to keep response sizes sane
    and avoid leaking document text into shared tooling.
    """
    entries = await _STORE.snapshot()
    out = []
    for e in entries:
        d = asdict(e)
        if not include_full_bodies:
            d.pop("prompt_preview", None)
            d.pop("response_preview", None)
        out.append(d)
    return out


async def clear_entries() -> None:
    await _STORE.clear()

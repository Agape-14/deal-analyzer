"""Admin-only diagnostics endpoints.

Read-only visibility into the live process — the operation buffer
populated by `app/services/operation_log.py`. Sits behind the same
auth that protects the rest of /api/*; no separate admin role (this
is a single-operator tool).

Not part of the public OpenAPI spec. It's here so the operator can
answer "why did that extraction fail?" in 5 seconds instead of
grepping Railway logs.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.auth import require_auth
from app.services.operation_log import clear_entries, snapshot_entries


router = APIRouter()


@router.get(
    "/diagnostics",
    summary="Recent AI operations — successes, failures, tracebacks",
    dependencies=[Depends(require_auth)],
)
async def diagnostics(
    full: bool = Query(False, description="Include truncated prompt/response bodies"),
    only_errors: bool = Query(False, description="Filter to failed operations only"),
    operation: str | None = Query(None, description="Filter by operation name (extract/verify/chat)"),
    limit: int = Query(50, ge=1, le=200, description="Max entries to return"),
):
    """Return the last N AI-pipeline operations in reverse-chronological order.

    Each entry has timing, status, model, token usage, and — for
    failures — the exception class, message, and a traceback excerpt
    so the operator can see exactly why an extraction or verify
    call fell over.

    ```bash
    # Most recent errors, one glance:
    curl '.../api/admin/diagnostics?only_errors=1&limit=10'

    # Include the first 2 KB of the prompt and Claude's response:
    curl '.../api/admin/diagnostics?full=1&limit=5'
    ```
    """
    entries = await snapshot_entries(include_full_bodies=full)

    if only_errors:
        entries = [e for e in entries if e.get("status") == "error"]
    if operation:
        entries = [e for e in entries if e.get("operation") == operation]

    entries = entries[:limit]

    counts = {
        "total_in_buffer": len(await snapshot_entries()),
        "returned": len(entries),
        "errors_in_buffer": sum(
            1 for e in await snapshot_entries() if e.get("status") == "error"
        ),
    }

    return {
        "counts": counts,
        "entries": entries,
    }


@router.post(
    "/diagnostics/clear",
    summary="Clear the operation buffer (diagnostics only)",
    dependencies=[Depends(require_auth)],
)
async def clear_diagnostics():
    await clear_entries()
    return {"ok": True, "message": "operation buffer cleared"}

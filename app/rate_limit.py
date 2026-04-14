"""
Token-bucket rate limiter.

In-memory, per-process. Good enough for a single-worker deployment
(our current Railway setup). When scaling out, replace the bucket
store with Redis — the public API here stays identical.

Usage in a route:

    @router.post("/some-ai-path", dependencies=[Depends(limit("ai"))])
    async def handler(...): ...

Policies are registered in `POLICIES` below and keyed by bucket name.
Each request consumes one token; a missing / over-capacity bucket
returns HTTP 429 with a Retry-After header.

Keyed by (bucket, user) — or (bucket, client_ip) when auth is off.
Keeps one user's burst from impacting another user's quota.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Callable

from fastapi import HTTPException, Request, Response


@dataclass
class Policy:
    """A token-bucket policy.

    capacity: max tokens in the bucket (i.e. allowed burst).
    refill_per_second: tokens added per second. capacity / refill = time
    to fully refill from empty.
    """

    capacity: int
    refill_per_second: float

    def per_minute(self) -> float:
        return self.refill_per_second * 60.0


# Policies tuned for the kind of operator traffic we expect. AI paths
# are the most expensive — throttle hardest.
POLICIES: dict[str, Policy] = {
    "ai":      Policy(capacity=10, refill_per_second=10 / 60.0),   # 10 per min burst, 10/min sustained
    "upload":  Policy(capacity=20, refill_per_second=20 / 60.0),   # 20 uploads/min
    "write":   Policy(capacity=60, refill_per_second=60 / 60.0),   # 60 writes/min
    "read":    Policy(capacity=300, refill_per_second=300 / 60.0), # 5 reads/sec sustained
    "auth":    Policy(capacity=8, refill_per_second=8 / 60.0),     # brute-force shield on /login
}


@dataclass
class _Bucket:
    tokens: float
    last_refill: float


class InMemoryLimiter:
    """Thread-safe-ish token bucket store. For a single async worker
    we can skip actual locks; asyncio serializes between awaits, and
    our ops are synchronous between yields."""

    def __init__(self) -> None:
        self._buckets: dict[tuple[str, str], _Bucket] = {}
        self._lock = asyncio.Lock()

    async def allow(self, bucket: str, key: str, policy: Policy) -> tuple[bool, float]:
        """Try to consume a token. Returns (allowed, retry_after_seconds)."""
        now = time.monotonic()
        async with self._lock:
            b = self._buckets.get((bucket, key))
            if b is None:
                b = _Bucket(tokens=float(policy.capacity), last_refill=now)
                self._buckets[(bucket, key)] = b
            # Refill
            elapsed = now - b.last_refill
            if elapsed > 0:
                b.tokens = min(policy.capacity, b.tokens + elapsed * policy.refill_per_second)
                b.last_refill = now
            if b.tokens >= 1:
                b.tokens -= 1
                return True, 0.0
            # Not enough — estimate when one token will be available
            retry = (1 - b.tokens) / policy.refill_per_second if policy.refill_per_second else 60.0
            return False, max(retry, 1.0)


_STORE = InMemoryLimiter()


def _client_key(request: Request) -> str:
    """Identify the caller for bucket keying.

    Prefer the session user when we have one (so a shared IP doesn't
    collide). Fall back to the first forwarded IP, then client.host.
    """
    session = getattr(request, "session", None) or {}
    user = (session.get("kenyon_user") or {}).get("u") if isinstance(session, dict) else None
    if user:
        return f"u:{user}"
    fwd = request.headers.get("x-forwarded-for") or ""
    if fwd:
        return "ip:" + fwd.split(",")[0].strip()
    client = request.client
    return "ip:" + (client.host if client else "unknown")


def limit(bucket: str) -> Callable:
    """FastAPI dependency factory for a named policy."""
    if bucket not in POLICIES:
        raise KeyError(f"unknown rate-limit bucket: {bucket}")
    policy = POLICIES[bucket]

    async def _dep(request: Request, response: Response) -> None:
        key = _client_key(request)
        allowed, retry = await _STORE.allow(bucket, key, policy)
        # Always expose the live quota state so the UI can show "X/Y used"
        # without a second call. Browser tools also show this on 429.
        response.headers["X-RateLimit-Bucket"] = bucket
        response.headers["X-RateLimit-Limit"] = str(policy.capacity)
        if not allowed:
            raise HTTPException(
                status_code=429,
                detail=f"Rate limit exceeded for '{bucket}'. Try again in ~{int(retry)}s.",
                headers={"Retry-After": str(int(retry))},
            )

    return _dep


def describe_policies() -> dict[str, dict]:
    """For /api/healthz — gives operators visibility into what's throttled."""
    return {
        name: {"capacity": p.capacity, "per_minute": round(p.per_minute(), 1)}
        for name, p in POLICIES.items()
    }

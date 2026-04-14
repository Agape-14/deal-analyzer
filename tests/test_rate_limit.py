"""Tests for the token-bucket rate limiter."""

import asyncio
import time

import pytest

from app.rate_limit import InMemoryLimiter, Policy


@pytest.mark.asyncio
async def test_allow_within_capacity():
    lim = InMemoryLimiter()
    p = Policy(capacity=3, refill_per_second=1)
    for i in range(3):
        ok, _ = await lim.allow("b", "k", p)
        assert ok, f"call {i + 1} should succeed"
    ok, retry = await lim.allow("b", "k", p)
    assert not ok and retry > 0


@pytest.mark.asyncio
async def test_refill_grants_new_tokens():
    lim = InMemoryLimiter()
    p = Policy(capacity=2, refill_per_second=10)  # fast refill for test
    # Drain bucket
    await lim.allow("b", "k", p)
    await lim.allow("b", "k", p)
    ok, _ = await lim.allow("b", "k", p)
    assert not ok
    # After 0.25s we should have ~2.5 tokens back (1/0.1s)
    await asyncio.sleep(0.25)
    ok, _ = await lim.allow("b", "k", p)
    assert ok


@pytest.mark.asyncio
async def test_buckets_isolated_per_key():
    lim = InMemoryLimiter()
    p = Policy(capacity=1, refill_per_second=0.001)
    ok_a, _ = await lim.allow("b", "alice", p)
    ok_b, _ = await lim.allow("b", "bob", p)
    assert ok_a and ok_b, "different keys must not share a bucket"


@pytest.mark.asyncio
async def test_buckets_isolated_per_bucket_name():
    lim = InMemoryLimiter()
    p = Policy(capacity=1, refill_per_second=0.001)
    ok_ai, _ = await lim.allow("ai", "k", p)
    ok_write, _ = await lim.allow("write", "k", p)
    assert ok_ai and ok_write, "different bucket names must not share"

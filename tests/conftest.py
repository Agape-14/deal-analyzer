"""Pytest fixtures shared across test modules."""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient


# Put the repo root on sys.path so "app" imports work without an install.
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


@pytest.fixture(scope="session")
def event_loop():
    """Single event loop for the session to avoid async fixture churn."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture
async def client(tmp_path, monkeypatch):
    """A fresh FastAPI test client backed by a per-test SQLite file.

    Auth is disabled for convenience in route tests; the auth module
    has its own dedicated tests that configure AUTH_PASSWORD_HASH.
    """
    db_dir = tmp_path / "data"
    db_dir.mkdir()
    monkeypatch.setenv("DB_DIR", str(db_dir))
    monkeypatch.setenv("AUTH_DISABLED", "1")

    # Force re-import of database / models so they pick up the new DB path.
    for mod in list(sys.modules):
        if mod.startswith("app"):
            sys.modules.pop(mod, None)

    from app.main import app  # noqa: E402  (late import on purpose)
    from app.database import init_db  # noqa: E402

    await init_db()

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac

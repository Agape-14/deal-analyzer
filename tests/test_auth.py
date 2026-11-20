"""Authentication checks and session lifecycle with synthetic accounts."""

from types import SimpleNamespace

import pytest
from starlette.requests import Request

from app.auth import (
    authentication_check,
    check_login,
    hash_password,
    is_public_path,
    verify_password,
)


def test_hash_password_is_bcrypt():
    h = hash_password("hunter2")
    assert h.startswith("$2b$")
    assert len(h) >= 60


def test_verify_password_correct_and_wrong():
    h = hash_password("s3cret")
    assert verify_password("s3cret", h) is True
    assert verify_password("nope", h) is False
    assert verify_password("", h) is False


def test_check_login_disabled_accepts_anything(monkeypatch):
    # With AUTH_PASSWORD_HASH unset, auth is disabled → check returns True.
    monkeypatch.delenv("AUTH_PASSWORD_HASH", raising=False)
    monkeypatch.delenv("AUTH_DISABLED", raising=False)
    assert check_login("anybody", "whatever") is True


def test_check_login_enabled_requires_correct_creds(monkeypatch):
    h = hash_password("demo123")
    monkeypatch.setenv("AUTH_USERNAME", "admin")
    monkeypatch.setenv("AUTH_PASSWORD_HASH", h)
    monkeypatch.delenv("AUTH_DISABLED", raising=False)
    assert check_login("admin", "demo123") is True
    assert check_login("admin", "wrong") is False
    assert check_login("not-admin", "demo123") is False


def test_is_public_path_whitelist():
    assert is_public_path("/")
    assert is_public_path("/api/healthz")
    assert is_public_path("/api/healthz/ready")
    assert is_public_path("/api/auth/login")
    assert is_public_path("/static/anything.js")
    assert is_public_path("/legacy")
    assert not is_public_path("/api/deals")
    assert not is_public_path("/api/deals/1")
    assert not is_public_path("/api/investments/")
    assert not is_public_path("/api/auth/new-endpoint")
    assert not is_public_path("/api/healthz/other")


@pytest.mark.parametrize("environment", [
    "RAILWAY_ENVIRONMENT",
    "RAILWAY_ENVIRONMENT_NAME",
    "RAILWAY_ENVIRONMENT_ID",
    "RAILWAY_PROJECT_ID",
    "RAILWAY_SERVICE_ID",
    "RAILWAY_DEPLOYMENT_ID",
    "APP_ENV",
    "PRODUCTION",
])
def test_deployed_auth_cannot_be_disabled(monkeypatch, environment):
    value = {"APP_ENV": "production", "PRODUCTION": "true"}.get(environment, "synthetic")
    monkeypatch.setenv(environment, value)
    monkeypatch.setenv("AUTH_DISABLED", "1")
    assert authentication_check()["code"] == "deployment_auth_disabled"
    assert not check_login("synthetic", "synthetic")


def test_deployed_auth_requires_usable_config(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("AUTH_DISABLED", "0")
    for key in ("AUTH_PASSWORD", "AUTH_PASSWORD_HASH", "VIEWER_PASSWORD", "VIEWER_PASSWORD_HASH",
                "TEAM_PASSWORD", "TEAM_PASSWORD_HASH", "AUTH_SECRET"):
        monkeypatch.delenv(key, raising=False)
    assert authentication_check()["code"] == "auth_credentials_missing"
    monkeypatch.setenv("AUTH_PASSWORD_HASH", "malformed-test-hash")
    assert authentication_check()["code"] == "auth_credentials_invalid"
    monkeypatch.delenv("AUTH_PASSWORD_HASH")
    monkeypatch.setenv("AUTH_PASSWORD", "synthetic-admin-password")
    assert authentication_check()["code"] == "auth_secret_invalid"
    monkeypatch.setenv("AUTH_SECRET", "synthetic-deployment-signing-secret")
    assert authentication_check()["code"] == "auth_configured"


def test_credential_bound_session_expires(monkeypatch):
    from app import auth

    monkeypatch.setenv("AUTH_DISABLED", "0")
    monkeypatch.setenv("AUTH_USERNAME", "synthetic-admin")
    monkeypatch.setenv("AUTH_PASSWORD_HASH", hash_password("synthetic-admin-password"))
    monkeypatch.setenv("AUTH_SECRET", "synthetic-deployment-signing-secret")
    clock = SimpleNamespace(time=lambda: 100)
    monkeypatch.setattr(auth, "time", clock)
    identity = auth.login_identity("synthetic-admin", "synthetic-admin-password")
    assert identity is not None
    request = Request({"type": "http", "session": {}})
    auth.set_session(request, identity)
    user = auth.current_user(request)
    assert user is not None and user["r"] == "admin"
    clock.time = lambda: user["exp"]
    assert auth.current_user(request) is None


@pytest.mark.asyncio
async def test_deployed_auth_failure_is_closed_with_or_without_lifespan(client, monkeypatch):
    from app import main

    monkeypatch.setenv("RAILWAY_SERVICE_ID", "synthetic-service")
    with pytest.raises(RuntimeError, match="deployment_auth_disabled"):
        async with main.lifespan(main.app):
            pytest.fail("startup should reject invalid auth configuration")

    assert (await client.get("/api/deals")).status_code == 503
    assert (await client.get("/api/auth/me")).json() == {"authenticated": False}
    login = await client.post("/api/auth/login", json={"username": "synthetic", "password": "synthetic"})
    assert login.status_code == 503
    ready = await client.get("/api/healthz/ready")
    assert ready.status_code == 503 and ready.json() == {"status": "not_ready"}


@pytest.mark.asyncio
async def test_active_sessions_follow_credential_rotation_and_account_removal(client, monkeypatch):
    monkeypatch.setenv("AUTH_DISABLED", "0")
    monkeypatch.setenv("AUTH_USERNAME", "synthetic-operator")
    monkeypatch.delenv("AUTH_PASSWORD_HASH", raising=False)
    monkeypatch.setenv("AUTH_PASSWORD", "synthetic-original-password")
    monkeypatch.setenv("TEAM_USERNAME", "synthetic-reviewer")
    monkeypatch.setenv("TEAM_PASSWORD_HASH", hash_password("synthetic-viewer-password"))

    async def login(username, password):
        return await client.post("/api/auth/login", json={"username": username, "password": password})

    assert (await login("synthetic-operator", "synthetic-original-password")).json()["role"] == "admin"
    assert (await client.get("/api/auth/me")).json()["authenticated"] is True
    monkeypatch.setenv("AUTH_PASSWORD", "synthetic-rotated-password")
    assert (await client.get("/api/auth/me")).json() == {"authenticated": False}
    assert (await login("synthetic-operator", "synthetic-original-password")).status_code == 401
    assert (await login("synthetic-operator", "synthetic-rotated-password")).status_code == 200
    assert (await login("synthetic-reviewer", "synthetic-viewer-password")).json()["role"] == "viewer"
    assert (await client.get("/api/auth/me")).json()["role"] == "viewer"
    monkeypatch.delenv("TEAM_PASSWORD_HASH")
    assert (await client.get("/api/auth/me")).json() == {"authenticated": False}

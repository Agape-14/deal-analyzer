"""Tests for the auth module — pure functions, no DB."""

from app.auth import (
    SESSION_KEY,
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
    assert is_public_path("/api/auth/login")
    assert is_public_path("/static/anything.js")
    assert is_public_path("/legacy")
    assert not is_public_path("/api/deals")
    assert not is_public_path("/api/deals/1")
    assert not is_public_path("/api/investments/")

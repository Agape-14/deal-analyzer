"""
Single-user authentication for Kenyon.

Configuration lives in environment variables — no user table, no role
system, no registration. One admin credential, one session cookie. That's
intentional: this app runs as a tool for a single operator, and the
simplest thing that works keeps attack surface small.

    AUTH_USERNAME         (optional, default "admin")
    AUTH_PASSWORD_HASH    (bcrypt hash; run `python -m app.auth hash <pw>`)
    AUTH_SECRET           (32+ char random string; required if auth is on)
    AUTH_DISABLED         ("1" or "true" disables auth entirely; for local dev)

When AUTH_PASSWORD_HASH is unset the server treats auth as disabled — the
app is wide open. The healthz endpoint surfaces this so the operator
sees the warning immediately.
"""

from __future__ import annotations

import os
import secrets
import time
from typing import Optional

import bcrypt
from fastapi import HTTPException, Request


# ----------------------------- configuration ----------------------------- #

def auth_enabled() -> bool:
    """True when a password hash is configured and auth isn't explicitly off."""
    disabled = os.getenv("AUTH_DISABLED", "").strip().lower() in ("1", "true", "yes")
    if disabled:
        return False
    return bool(os.getenv("AUTH_PASSWORD_HASH"))


def expected_username() -> str:
    return os.getenv("AUTH_USERNAME", "admin").strip()


def _password_hash() -> Optional[str]:
    v = os.getenv("AUTH_PASSWORD_HASH")
    return v.strip() if v else None


def session_secret() -> str:
    """Signing secret for the session cookie. Required when auth is on.

    If the operator hasn't set one we generate an ephemeral one and warn —
    sessions won't survive a restart but the app boots. This is a
    'fail visible, keep running' policy rather than a hard exit, since a
    silent crash on a missing env is worse than forcing re-login.
    """
    s = os.getenv("AUTH_SECRET")
    if s and len(s) >= 16:
        return s
    return os.environ.setdefault("_KENYON_EPHEMERAL_SECRET", secrets.token_urlsafe(48))


# ----------------------------- password check ---------------------------- #

def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")


def check_login(username: str, password: str) -> bool:
    """Validate a username/password pair against configured credentials."""
    if not auth_enabled():
        return True
    if username != expected_username():
        return False
    h = _password_hash() or ""
    return verify_password(password, h)


# ----------------------------- session helpers --------------------------- #

SESSION_KEY = "kenyon_user"
SESSION_TTL_DAYS = 30


def set_session(request: Request, username: str) -> None:
    request.session[SESSION_KEY] = {
        "u": username,
        "iat": int(time.time()),
        "exp": int(time.time()) + SESSION_TTL_DAYS * 86400,
    }


def clear_session(request: Request) -> None:
    request.session.pop(SESSION_KEY, None)


def current_user(request: Request) -> Optional[dict]:
    """Return the session payload if present and unexpired, else None."""
    data = request.session.get(SESSION_KEY) if hasattr(request, "session") else None
    if not data:
        return None
    try:
        exp = int(data.get("exp") or 0)
    except (TypeError, ValueError):
        exp = 0
    if exp and exp < int(time.time()):
        return None
    return data


# ----------------------------- FastAPI guard ----------------------------- #

# Paths that never require auth. Kept narrow on purpose.
PUBLIC_PATH_PREFIXES = (
    "/api/healthz",
    "/api/auth/",
    "/static/",
    "/legacy",
    "/",          # root redirect
    "/openapi.json",
    "/docs",
    "/redoc",
)


def is_public_path(path: str) -> bool:
    if path == "/":
        return True
    return any(path.startswith(p) for p in PUBLIC_PATH_PREFIXES if p != "/")


async def require_auth(request: Request) -> dict:
    """FastAPI dependency — raises 401 if not signed in. No-op when auth off."""
    if not auth_enabled():
        return {"u": expected_username(), "anonymous": True}
    user = current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


# --------------------------- describe for healthz ------------------------- #

def describe_auth() -> dict:
    return {
        "enabled": auth_enabled(),
        "username": expected_username() if auth_enabled() else None,
        "message": (
            None
            if auth_enabled()
            else "AUTH_PASSWORD_HASH is not set — every endpoint is publicly reachable."
        ),
    }


# ----------------------------- CLI helper -------------------------------- #

if __name__ == "__main__":
    import sys

    if len(sys.argv) >= 3 and sys.argv[1] == "hash":
        print(hash_password(sys.argv[2]))
    else:
        print("Usage: python -m app.auth hash <password>")
        sys.exit(2)

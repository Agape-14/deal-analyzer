"""
Role-aware authentication for Kenyon.

Configuration lives in environment variables — no registration flow and no
user-management screen. The app supports one operator account and one optional
read-only viewer account so deal reviewers can see clean summaries without the
analysis/editing tools.

    AUTH_USERNAME          (admin username, optional, default "admin")
    AUTH_PASSWORD          (admin plaintext password; hashed in memory)
    AUTH_PASSWORD_HASH     (admin bcrypt hash; explicit hash wins)

    VIEWER_USERNAME        (viewer username, optional, default "team")
    VIEWER_PASSWORD        (viewer plaintext password; hashed in memory)
    VIEWER_PASSWORD_HASH   (viewer bcrypt hash; explicit hash wins)

    TEAM_USERNAME          (accepted alias for VIEWER_USERNAME)
    TEAM_PASSWORD          (accepted alias for VIEWER_PASSWORD)
    TEAM_PASSWORD_HASH     (accepted alias for VIEWER_PASSWORD_HASH)

    AUTH_SECRET            (32+ char random string; required if auth is on)
    AUTH_DISABLED          ("1" or "true" disables auth entirely; local dev)

When neither an admin nor viewer password is configured, auth is treated as
disabled and the health endpoint surfaces a warning.
"""

from __future__ import annotations

import os
import secrets
import time
from typing import Literal, Optional, TypedDict

import bcrypt
from fastapi import HTTPException, Request

UserRole = Literal["admin", "analyst", "viewer"]


class LoginIdentity(TypedDict):
    u: str
    r: UserRole


# ----------------------------- configuration ----------------------------- #

def _disabled() -> bool:
    return os.getenv("AUTH_DISABLED", "").strip().lower() in ("1", "true", "yes")


def expected_username() -> str:
    return os.getenv("AUTH_USERNAME", "admin").strip() or "admin"


def viewer_username() -> str:
    return (os.getenv("VIEWER_USERNAME") or os.getenv("TEAM_USERNAME") or "team").strip() or "team"


def _hashed_credential(hash_keys: tuple[str, ...], password_keys: tuple[str, ...], cache_key: str) -> Optional[str]:
    for key in hash_keys:
        explicit = os.getenv(key)
        if explicit and explicit.strip():
            return explicit.strip()

    for key in password_keys:
        plain = os.getenv(key)
        if plain:
            cached = os.environ.get(cache_key)
            if cached:
                return cached
            hashed = hash_password(plain)
            os.environ[cache_key] = hashed
            return hashed

    return None


def _admin_password_hash() -> Optional[str]:
    return _hashed_credential(("AUTH_PASSWORD_HASH",), ("AUTH_PASSWORD",), "_KENYON_ADMIN_PASSWORD_HASH_CACHE")


def _viewer_password_hash() -> Optional[str]:
    return _hashed_credential(
        ("VIEWER_PASSWORD_HASH", "TEAM_PASSWORD_HASH"),
        ("VIEWER_PASSWORD", "TEAM_PASSWORD"),
        "_KENYON_VIEWER_PASSWORD_HASH_CACHE",
    )


def configured_accounts() -> list[dict[str, str]]:
    """Return configured login identities.

    Admin is checked first. If someone accidentally configures the same
    username for both roles, the admin credential wins rather than silently
    downgrading the operator to read-only access.
    """
    accounts: list[dict[str, str]] = []
    admin_hash = _admin_password_hash()
    if admin_hash:
        accounts.append({"username": expected_username(), "role": "admin", "hash": admin_hash})

    viewer_hash = _viewer_password_hash()
    if viewer_hash:
        accounts.append({"username": viewer_username(), "role": "viewer", "hash": viewer_hash})

    return accounts


def auth_enabled() -> bool:
    """True when any credential is configured and auth isn't explicitly off."""
    if _disabled():
        return False
    return bool(configured_accounts())


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


def login_identity(username: str, password: str) -> Optional[LoginIdentity]:
    """Validate credentials and return the session identity."""
    if not auth_enabled():
        return {"u": expected_username(), "r": "admin"}

    submitted = username.strip()
    for account in configured_accounts():
        if submitted != account["username"]:
            continue
        if verify_password(password, account["hash"]):
            role = _normalize_role(account["role"])
            return {"u": account["username"], "r": role}
    return None


def check_login(username: str, password: str) -> bool:
    """Backward-compatible boolean login check."""
    return login_identity(username, password) is not None


# ----------------------------- session helpers --------------------------- #

SESSION_KEY = "kenyon_user"
SESSION_TTL_DAYS = 30


def _normalize_role(role: object) -> UserRole:
    value = str(role or "admin").strip().lower()
    if value in ("admin", "analyst"):
        return "admin"
    return "viewer"


def set_session(request: Request, username: str, role: UserRole = "admin") -> None:
    request.session[SESSION_KEY] = {
        "u": username,
        "r": _normalize_role(role),
        "iat": int(time.time()),
        "exp": int(time.time()) + SESSION_TTL_DAYS * 86400,
    }


def clear_session(request: Request) -> None:
    request.session.pop(SESSION_KEY, None)


def current_user(request: Request) -> Optional[dict]:
    """Return the normalized session payload if present and unexpired."""
    data = request.session.get(SESSION_KEY) if hasattr(request, "session") else None
    if not data:
        return None
    try:
        exp = int(data.get("exp") or 0)
    except (TypeError, ValueError):
        exp = 0
    if exp and exp < int(time.time()):
        return None
    normalized = dict(data)
    normalized["r"] = _normalize_role(normalized.get("r"))
    return normalized


def is_analyst(user: Optional[dict]) -> bool:
    return bool(user and _normalize_role(user.get("r")) == "admin")


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
        return {"u": expected_username(), "r": "admin", "anonymous": True}
    user = current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


# --------------------------- describe for healthz ------------------------- #

def describe_auth() -> dict:
    enabled = auth_enabled()
    roles = {
        "admin": bool(_admin_password_hash()),
        "viewer": bool(_viewer_password_hash()),
    }
    return {
        "enabled": enabled,
        "username": expected_username() if enabled else None,
        "viewer_username": viewer_username() if roles["viewer"] else None,
        "roles": roles,
        "message": (
            None
            if enabled
            else "No admin or viewer password is configured — every endpoint is publicly reachable."
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

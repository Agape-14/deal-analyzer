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

    AUTH_SECRET            (random string of at least 16 chars; required on deploy)
    AUTH_DISABLED          ("1" or "true" disables auth entirely; local dev)

Local development can run without authentication. Deployments require
configured credentials and a stable signing secret.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import time
from functools import lru_cache
from typing import Literal, NamedTuple, Optional, TypedDict

import bcrypt
from fastapi import HTTPException, Request
from sqlalchemy import delete, select
from sqlalchemy.exc import SQLAlchemyError

UserRole = Literal["admin", "analyst", "viewer"]
MAX_USERNAME_LENGTH = 120


class LoginIdentity(TypedDict):
    u: str
    r: UserRole
    binding: str | None


class _Account(NamedTuple):
    username: str
    role: UserRole
    credential: str
    is_hash: bool


# ----------------------------- configuration ----------------------------- #

_TRUE_VALUES = {"1", "true", "yes"}
_RAILWAY_RUNTIME_MARKERS = (
    "RAILWAY_PROJECT_ID",
    "RAILWAY_ENVIRONMENT",
    "RAILWAY_ENVIRONMENT_NAME",
    "RAILWAY_ENVIRONMENT_ID",
    "RAILWAY_SERVICE_ID",
    "RAILWAY_DEPLOYMENT_ID",
)
_EPHEMERAL_SECRET = secrets.token_urlsafe(48)
# The final character in each bcrypt field must have zero unused bits.
_BCRYPT_HASH = re.compile(
    r"\$2[aby]\$(?:0[4-9]|[12][0-9]|3[01])\$"
    r"[./0-9A-Za-z]{21}[.Oeu][./0-9A-Za-z]{30}[.CGKOSWaeimquy26]"
)


def deployment_auth_required() -> bool:
    return (
        any(os.getenv(key) for key in _RAILWAY_RUNTIME_MARKERS)
        or os.getenv("PRODUCTION", "").strip().lower() in _TRUE_VALUES
        or os.getenv("APP_ENV", "").strip().lower() in {"prod", "production", "staging"}
    )


def _disabled() -> bool:
    return os.getenv("AUTH_DISABLED", "").strip().lower() in _TRUE_VALUES


def expected_username() -> str:
    return os.getenv("AUTH_USERNAME", "admin").strip() or "admin"


def viewer_username() -> str:
    return (os.getenv("VIEWER_USERNAME") or os.getenv("TEAM_USERNAME") or "team").strip() or "team"


def _credential(hash_keys: tuple[str, ...], password_keys: tuple[str, ...]) -> tuple[str, bool] | None:
    for key in hash_keys:
        explicit = os.getenv(key, "").strip()
        if explicit:
            return explicit, True

    for key in password_keys:
        plain = os.getenv(key)
        if plain:
            return plain, False

    return None


def _configured_accounts() -> list[_Account]:
    accounts: list[_Account] = []
    admin = _credential(("AUTH_PASSWORD_HASH",), ("AUTH_PASSWORD",))
    viewer = _credential(
        ("VIEWER_PASSWORD_HASH", "TEAM_PASSWORD_HASH"),
        ("VIEWER_PASSWORD", "TEAM_PASSWORD"),
    )
    if admin:
        accounts.append(_Account(expected_username(), "admin", *admin))
    if viewer:
        accounts.append(_Account(viewer_username(), "viewer", *viewer))
    return accounts


def _credential_is_usable(account: _Account) -> bool:
    if len(account.username) > MAX_USERNAME_LENGTH:
        return False
    if account.is_hash:
        return _BCRYPT_HASH.fullmatch(account.credential) is not None
    return bool(account.credential.strip()) and len(account.credential.encode("utf-8")) <= 72


def _configured_secret() -> str | None:
    secret = os.getenv("AUTH_SECRET", "")
    return secret if len(secret.strip()) >= 16 else None


def authentication_check() -> dict[str, str]:
    """Describe auth availability without disclosing credentials or identities."""
    required = deployment_auth_required()
    accounts = _configured_accounts()
    if not required and (_disabled() or not accounts):
        return {"status": "ok", "code": "local_auth_disabled"}
    if _disabled():
        return {"status": "error", "code": "deployment_auth_disabled"}
    if not accounts:
        return {"status": "error", "code": "auth_credentials_missing"}
    if any(not _credential_is_usable(account) for account in accounts):
        return {"status": "error", "code": "auth_credentials_invalid"}
    if required and not _configured_secret():
        return {"status": "error", "code": "auth_secret_invalid"}
    return {"status": "ok", "code": "auth_configured"}


def session_secret() -> str:
    """Signing key for session middleware, with an ephemeral local default."""
    return _configured_secret() or _EPHEMERAL_SECRET


# ----------------------------- password check ---------------------------- #

def verify_password(plain: str, hashed: str) -> bool:
    encoded = plain.encode("utf-8")
    if len(encoded) > 72:
        return False
    try:
        return bcrypt.checkpw(encoded, hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")


@lru_cache(maxsize=2)
def _hash_plaintext_credential(plain: str) -> str:
    return hash_password(plain)


def _credential_binding(account: _Account) -> str:
    # Bind to the configured credential, so plaintext credentials work across
    # restarts and replicas without sharing a randomly salted bcrypt cache.
    message = json.dumps(["kenyon-auth-v2", *account]).encode("utf-8")
    return hmac.digest(session_secret().encode("utf-8"), message, "sha256").hex()


def login_identity(username: str, password: str) -> Optional[LoginIdentity]:
    """Validate credentials and return the session identity."""
    check = authentication_check()
    if check["code"] == "local_auth_disabled":
        return {"u": expected_username(), "r": "admin", "binding": None}
    if check["status"] == "error":
        return None

    submitted = username.strip()
    for account in _configured_accounts():
        if submitted != account.username:
            continue
        hashed = account.credential if account.is_hash else _hash_plaintext_credential(account.credential)
        if verify_password(password, hashed):
            return {"u": account.username, "r": account.role, "binding": _credential_binding(account)}
    return None


def check_login(username: str, password: str) -> bool:
    """Backward-compatible boolean login check."""
    return login_identity(username, password) is not None


# ----------------------------- session helpers --------------------------- #

SESSION_KEY = "kenyon_user"
SESSION_TTL_DAYS = 30
_REQUEST_USER = "_kenyon_verified_user"
_SESSION_IDENTIFIER = re.compile(r"[a-f0-9]{64}")


def _session_digest(request: Request) -> str | None:
    data = request.scope.get("session", {}).get(SESSION_KEY)
    token = data.get("sid") if isinstance(data, dict) else None
    if isinstance(token, str) and _SESSION_IDENTIFIER.fullmatch(token):
        return hashlib.sha256(token.encode("ascii")).hexdigest()
    return None


async def set_session(request: Request, identity: LoginIdentity) -> None:
    if identity["binding"] is None:
        await clear_session(request)
        return
    from app.database import async_session
    from app.models import AuthSession

    now = int(time.time())
    expires_at = now + SESSION_TTL_DAYS * 86400
    previous = _session_digest(request)
    token = secrets.token_hex(32)
    try:
        async with async_session.begin() as db:
            await db.execute(delete(AuthSession).where(AuthSession.expires_at <= now))
            if previous:
                await db.execute(delete(AuthSession).where(AuthSession.token_hash == previous))
            db.add(AuthSession(token_hash=hashlib.sha256(token.encode("ascii")).hexdigest(), expires_at=expires_at))
    except SQLAlchemyError:
        raise HTTPException(status_code=503, detail="Sign-in is temporarily unavailable") from None

    request.session[SESSION_KEY] = {
        **identity,
        "sid": token,
        "iat": now,
        "exp": expires_at,
    }


async def clear_session(request: Request) -> None:
    token_hash = _session_digest(request)
    if token_hash:
        from app.database import async_session
        from app.models import AuthSession

        try:
            async with async_session.begin() as db:
                await db.execute(delete(AuthSession).where(AuthSession.token_hash == token_hash))
        except SQLAlchemyError:
            raise HTTPException(status_code=503, detail="Sign-out could not be saved. Please try again.") from None

    request.session.pop(SESSION_KEY, None)
    setattr(request.state, _REQUEST_USER, None)


def _bound_identity(request: Request) -> Optional[dict]:
    """Check the signed cookie against the current configured account."""
    data = request.scope.get("session", {}).get(SESSION_KEY)
    if not isinstance(data, dict) or authentication_check()["code"] != "auth_configured":
        return None
    exp = data.get("exp")
    iat = data.get("iat")
    binding = data.get("binding")
    if type(exp) is not int or type(iat) is not int or not iat <= int(time.time()) < exp:
        return None
    if not isinstance(binding, str) or not binding.isascii():
        return None
    for account in _configured_accounts():
        if data.get("u") == account.username and data.get("r") == account.role:
            if hmac.compare_digest(binding, _credential_binding(account)):
                return {"u": account.username, "r": account.role, "iat": iat, "exp": exp}
    return None


def current_user(request: Request) -> Optional[dict]:
    """Read the identity already verified for this request."""
    return getattr(request.state, _REQUEST_USER, None)


async def authenticate_request(request: Request) -> Optional[dict]:
    """Verify credential binding and the shared session record once per request."""
    if hasattr(request.state, _REQUEST_USER):
        return current_user(request)

    identity = _bound_identity(request)
    token_hash = _session_digest(request)
    user = None
    if identity and token_hash:
        from app.database import async_session
        from app.models import AuthSession

        try:
            async with async_session() as db:
                expires_at = await db.scalar(select(AuthSession.expires_at).where(AuthSession.token_hash == token_hash))
        except SQLAlchemyError:
            raise HTTPException(status_code=503, detail="Authentication unavailable") from None
        if expires_at == identity["exp"] and expires_at > int(time.time()):
            user = identity

    if user is None:
        request.scope.get("session", {}).pop(SESSION_KEY, None)
    setattr(request.state, _REQUEST_USER, user)
    return user


def is_analyst(user: Optional[dict]) -> bool:
    return bool(user and user.get("r") in ("admin", "analyst"))


# ----------------------------- FastAPI guard ----------------------------- #

# Only explicitly public API endpoints are exempt from auth.
PUBLIC_PATHS = {
    "/api/healthz",
    "/api/healthz/ready",
    "/api/auth/login",
    "/api/auth/logout",
    "/api/auth/me",
    "/legacy",
    "/",
    "/openapi.json",
    "/docs",
    "/docs/oauth2-redirect",
    "/redoc",
}


def is_public_path(path: str) -> bool:
    return path in PUBLIC_PATHS or path.startswith("/static/")


async def require_auth(request: Request) -> dict:
    """FastAPI dependency requiring a valid session outside local bypass."""
    check = authentication_check()
    if check["status"] == "error":
        raise HTTPException(status_code=503, detail="Authentication unavailable")
    if check["code"] == "local_auth_disabled":
        return {"u": expected_username(), "r": "admin", "anonymous": True}
    user = await authenticate_request(request)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


# --------------------------- describe for healthz ------------------------- #

def describe_auth() -> dict:
    check = authentication_check()
    enabled = check["code"] == "auth_configured"
    configured_roles = {account.role for account in _configured_accounts()}
    roles = {"admin": "admin" in configured_roles, "viewer": "viewer" in configured_roles}
    message = None
    if check["status"] == "error":
        message = "Authentication is unavailable. Review deployment configuration."
    elif not enabled:
        message = "Authentication is disabled for local development."
    return {
        "enabled": enabled,
        "username": expected_username() if enabled else None,
        "viewer_username": viewer_username() if roles["viewer"] else None,
        "roles": roles,
        "message": message,
    }


# ----------------------------- CLI helper -------------------------------- #

if __name__ == "__main__":
    import sys

    if len(sys.argv) >= 3 and sys.argv[1] == "hash":
        print(hash_password(sys.argv[2]))
    else:
        print("Usage: python -m app.auth hash <password>")
        sys.exit(2)

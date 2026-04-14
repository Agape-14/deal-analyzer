"""Auth endpoints. Always public — the rest of /api/* sits behind
`require_auth` (or the global session middleware). Kept in its own router
so it can be included before any protection middleware runs."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.auth import (
    auth_enabled,
    check_login,
    clear_session,
    current_user,
    expected_username,
    set_session,
)
from app.rate_limit import limit

router = APIRouter()


class LoginIn(BaseModel):
    username: str = Field(..., min_length=1, max_length=120)
    password: str = Field(..., min_length=1, max_length=256)


@router.post("/login", dependencies=[Depends(limit("auth"))])
async def login(data: LoginIn, request: Request):
    """Validate credentials and start a session.

    A small constant-time delay on failure to slow down brute-force.
    """
    ok = check_login(data.username, data.password)
    if not ok:
        # Uniform delay makes timing attacks useless.
        await asyncio.sleep(0.5)
        raise HTTPException(status_code=401, detail="Invalid username or password")
    set_session(request, data.username)
    return {"message": "Signed in", "username": data.username}


@router.post("/logout")
async def logout(request: Request):
    clear_session(request)
    return {"message": "Signed out"}


@router.get("/me")
async def me(request: Request):
    """Identity probe used by the frontend to decide whether to show
    the login page. Always returns 200 — the caller interprets the
    `authenticated` flag.
    """
    if not auth_enabled():
        return {"authenticated": True, "username": expected_username(), "auth_disabled": True}
    user = current_user(request)
    if not user:
        return {"authenticated": False}
    return {
        "authenticated": True,
        "username": user.get("u"),
        "issued_at": user.get("iat"),
        "expires_at": user.get("exp"),
    }

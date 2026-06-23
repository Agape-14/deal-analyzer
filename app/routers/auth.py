"""Auth endpoints. Always public — the rest of /api/* sits behind
`require_auth` (or the global session middleware). Kept in its own router
so it can be included before any protection middleware runs."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.auth import (
    auth_enabled,
    clear_session,
    current_user,
    expected_username,
    login_identity,
    set_session,
)
from app.rate_limit import limit

router = APIRouter()


class LoginIn(BaseModel):
    username: str = Field(..., min_length=1, max_length=120)
    password: str = Field(..., min_length=1, max_length=256)


@router.post("/login", dependencies=[Depends(limit("auth"))])
async def login(data: LoginIn, request: Request):
    """Validate credentials and start a role-aware session.

    A small constant-time delay on failure slows down brute-force attempts.
    """
    identity = login_identity(data.username, data.password)
    if not identity:
        await asyncio.sleep(0.5)
        raise HTTPException(status_code=401, detail="Invalid username or password")
    set_session(request, identity["u"], identity["r"])
    return {"message": "Signed in", "username": identity["u"], "role": identity["r"]}


@router.post("/logout")
async def logout(request: Request):
    clear_session(request)
    return {"message": "Signed out"}


@router.get("/me")
async def me(request: Request):
    """Identity probe used by the frontend to decide which tools to show.

    Always returns 200 — the caller interprets the `authenticated` flag.
    """
    if not auth_enabled():
        return {
            "authenticated": True,
            "username": expected_username(),
            "role": "admin",
            "auth_disabled": True,
        }
    user = current_user(request)
    if not user:
        return {"authenticated": False}
    return {
        "authenticated": True,
        "username": user.get("u"),
        "role": user.get("r", "admin"),
        "issued_at": user.get("iat"),
        "expires_at": user.get("exp"),
    }

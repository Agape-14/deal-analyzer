import sys
import os
import logging

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from fastapi import FastAPI, Request as FastRequest
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.requests import Request
from fastapi.responses import RedirectResponse, JSONResponse
from starlette.middleware.sessions import SessionMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from contextlib import asynccontextmanager
from app.database import init_db
from app.routers import developers, deals, chat, investments, reports, auth as auth_router
from app.config import describe_models, environment_status
from app.auth import (
    auth_enabled,
    current_user,
    describe_auth,
    is_public_path,
    session_secret,
)
from app.rate_limit import describe_policies


# ----------------------------- logging setup ----------------------------- #
# Simple, uniform stdout logging. One line per log record so it plays nicely
# with Railway / Docker / k8s log collectors. Uvicorn's own loggers are left
# untouched; our services use the "kenyon" hierarchy.
logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger("kenyon.boot")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    # Surface environment configuration at boot so operators don't discover
    # missing keys by user bug reports.
    status = environment_status()
    models = describe_models()
    auth = describe_auth()
    log.info("Kenyon API starting · models=%s", models)
    for svc, info in status.items():
        msg = info.get("message")
        if msg:
            log.warning("[env] %s: %s", svc, msg)
        else:
            log.info("[env] %s: ok", svc)
    if auth.get("enabled"):
        log.info("[auth] enabled for user '%s'", auth.get("username"))
    else:
        log.warning("[auth] %s", auth.get("message"))
    yield


app = FastAPI(title="Kenyon Investment Dashboard", version="1.0.0", lifespan=lifespan)


class EnforceAuthMiddleware(BaseHTTPMiddleware):
    """Reject unauthenticated requests to protected /api/* paths.

    Runs *after* SessionMiddleware so `request.session` is populated.
    Public paths (healthz, auth, static, legacy, root) pass through
    untouched. If auth is globally disabled this is a no-op.
    """

    async def dispatch(self, request: FastRequest, call_next):
        if not auth_enabled():
            return await call_next(request)

        path = request.url.path or "/"
        if not path.startswith("/api/") or is_public_path(path):
            return await call_next(request)

        if not current_user(request):
            return JSONResponse({"detail": "Not authenticated"}, status_code=401)
        return await call_next(request)


# Middleware ordering note: `add_middleware` registers in reverse — the
# LAST one added is the OUTERMOST layer (first to see the request). So
# SessionMiddleware must be added LAST so it runs before EnforceAuth and
# populates `request.session`.
app.add_middleware(EnforceAuthMiddleware)
app.add_middleware(
    SessionMiddleware,
    secret_key=session_secret(),
    session_cookie="kenyon_session",
    max_age=60 * 60 * 24 * 30,          # 30 days
    same_site="lax",
    https_only=False,                    # Railway terminates TLS at the edge
)


base_dir = os.path.dirname(os.path.dirname(__file__))
app.mount("/static", StaticFiles(directory=os.path.join(base_dir, "static")), name="static")
templates = Jinja2Templates(directory=os.path.join(base_dir, "templates"))

# Auth FIRST so it's reachable even when other routers are behind the middleware.
app.include_router(auth_router.router, prefix="/api/auth", tags=["auth"])
app.include_router(developers.router, prefix="/api/developers", tags=["developers"])
app.include_router(deals.router, prefix="/api/deals", tags=["deals"])
app.include_router(chat.router, prefix="/api/chat", tags=["chat"])
app.include_router(investments.router, prefix="/api/investments", tags=["investments"])
app.include_router(reports.router, prefix="/api/reports", tags=["reports"])


@app.get("/api/healthz")
async def healthz():
    """Liveness + configuration probe.

    Returns:
      - status: "ok" | "degraded" — degraded if any required env is missing
      - models: active Anthropic model assignments
      - environment: per-service configuration status (anthropic, brave, db)
        each with a human-readable `message` when misconfigured.

    A dashboard banner can consume this to warn users before they click a
    button that would 503.
    """
    env = environment_status()
    auth = describe_auth()
    degraded = any(not info.get("configured", True) for info in env.values() if "configured" in info)
    # Auth being off isn't a crash but it's a real security concern — surface
    # it on healthz so the banner can warn even on an otherwise clean deploy.
    if not auth.get("enabled"):
        degraded = True
    return {
        "status": "degraded" if degraded else "ok",
        "models": describe_models(),
        "environment": env,
        "auth": auth,
        "rate_limits": describe_policies(),
    }


@app.get("/")
async def root_redirect():
    """FastAPI now serves the legacy UI at /legacy. The new Next.js app (at
    web/) is expected to sit in front in production. During local FastAPI-only
    runs we redirect / → /legacy so the legacy UI is still reachable."""
    return RedirectResponse(url="/legacy")


@app.get("/legacy")
async def legacy_index(request: Request):
    return templates.TemplateResponse(request, "index.html")

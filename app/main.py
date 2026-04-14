import sys
import os
import logging

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.requests import Request
from fastapi.responses import RedirectResponse
from contextlib import asynccontextmanager
from app.database import init_db
from app.routers import developers, deals, chat, investments, reports
from app.config import describe_models, environment_status


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
    log.info("Kenyon API starting · models=%s", models)
    for svc, info in status.items():
        msg = info.get("message")
        if msg:
            log.warning("[env] %s: %s", svc, msg)
        else:
            log.info("[env] %s: ok", svc)
    yield


app = FastAPI(title="Kenyon Investment Dashboard", version="1.0.0", lifespan=lifespan)

base_dir = os.path.dirname(os.path.dirname(__file__))
app.mount("/static", StaticFiles(directory=os.path.join(base_dir, "static")), name="static")
templates = Jinja2Templates(directory=os.path.join(base_dir, "templates"))

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
    degraded = any(not info.get("configured", True) for info in env.values() if "configured" in info)
    return {
        "status": "degraded" if degraded else "ok",
        "models": describe_models(),
        "environment": env,
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

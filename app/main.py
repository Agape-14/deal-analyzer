import sys
import os
import logging
import asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from fastapi import Depends, FastAPI, HTTPException, Request as FastRequest
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.requests import Request
from fastapi.responses import RedirectResponse, JSONResponse
from starlette.middleware.sessions import SessionMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.gzip import GZipMiddleware
from app.security_headers import SecurityHeadersMiddleware
from contextlib import asynccontextmanager, suppress
from app.database import init_db
from app.routers import (
    developers,
    deals,
    deal_uploads,
    field_edits,
    deal_pipeline,
    chat,
    investments,
    reports,
    auth as auth_router,
    notifications as notifications_router,
    admin as admin_router,
)
from app.config import describe_models, environment_status
from app.auth import (
    SESSION_TTL_DAYS,
    authentication_check,
    current_user,
    deployment_auth_required,
    describe_auth,
    is_public_path,
    is_analyst,
    require_auth,
    session_secret,
)
from app.rate_limit import describe_policies
from app.services.json_parser_guard import install_deal_verifier_json_guard
from app.services.pipeline_runner import start_pipeline_runner, stop_pipeline_runner
from app.routers import analysis as analysis_router
from app.routers import financing_measures as financing_measures_router
from app.routers import review_drafts as review_drafts_router
from app.routers import return_schedules as return_schedules_router
from sqlalchemy.orm.exc import StaleDataError
from app.services.review_jobs import start_review_worker, stop_review_worker
from app.services.operational_readiness import readiness_report


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

# Install review-time JSON and metrics-shape guards after routers import so
# route-level direct imports are patched too. This prevents one malformed saved
# value from crashing document review with errors like "str has no keys".
install_deal_verifier_json_guard()


@asynccontextmanager
async def lifespan(app: FastAPI):
    auth_check = authentication_check()
    if auth_check["status"] == "error":
        raise RuntimeError(f"Authentication configuration is invalid ({auth_check['code']})")
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
        log.info("[auth] enabled for user '%s' roles=%s", auth.get("username"), auth.get("roles"))
    else:
        log.warning("[auth] %s", auth.get("message"))
    workers_enabled = os.getenv("REVIEW_WORKERS_ENABLED", "1").lower() not in {"0", "false", "no"}
    pipeline_task = start_pipeline_runner() if workers_enabled else None
    review_task = start_review_worker() if workers_enabled else None
    backfill_task = None
    if os.getenv("KENYON_SOURCE_REPLAY"):
        from scripts.release_review_backfill import start_source_replay
        backfill_task = start_source_replay()
    elif os.getenv("KENYON_REVIEW_REPAIR"):
        from scripts.release_review_backfill import start_review_repair
        backfill_task = start_review_repair()
    elif os.getenv("KENYON_REVIEW_BACKFILL_PLAN"):
        from scripts.release_review_backfill import start_review_backfill
        backfill_task = start_review_backfill()
    try:
        yield
    finally:
        if backfill_task and not backfill_task.done():
            backfill_task.cancel()
            with suppress(asyncio.CancelledError):
                await backfill_task
        if review_task:
            await stop_review_worker(review_task)
        if pipeline_task:
            await stop_pipeline_runner(pipeline_task)


app = FastAPI(title="Kenyon Investment Dashboard", version="1.0.0", lifespan=lifespan)


@app.exception_handler(StaleDataError)
async def stale_analysis_handler(request, exc):
    return JSONResponse(status_code=409, content={"detail": "The deal changed during this operation. Reload and retry; no older result was saved."})


app.include_router(analysis_router.router, prefix="/api/deals", tags=["analysis"])
app.include_router(financing_measures_router.router, prefix="/api/deals", tags=["analysis"])
app.include_router(review_drafts_router.router, prefix="/api/deals", tags=["review"])
app.include_router(return_schedules_router.router, prefix="/api/deals", tags=["analysis"])


class EnforceAuthMiddleware(BaseHTTPMiddleware):
    """Reject unauthenticated requests to protected /api/* paths.

    Runs *after* SessionMiddleware so `request.session` is populated.
    Public paths (healthz, auth, static, legacy, root) pass through
    untouched. Auth bypass is available only in local development.
    """

    VIEWER_BLOCKED_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
    VIEWER_READONLY_POSTS = {
        "/api/deals/compare",
        "/api/deals/compare/export",
    }

    async def dispatch(self, request: FastRequest, call_next):
        path = request.url.path or "/"
        if (path != "/api" and not path.startswith("/api/")) or is_public_path(path):
            return await call_next(request)

        check = authentication_check()
        if check["status"] == "error":
            return JSONResponse({"detail": "Authentication unavailable"}, status_code=503)
        if check["code"] == "local_auth_disabled":
            return await call_next(request)

        user = current_user(request)
        if not user:
            return JSONResponse({"detail": "Not authenticated"}, status_code=401)

        role = user["r"]
        method = request.method.upper()
        if role == "viewer" and method in self.VIEWER_BLOCKED_METHODS and path not in self.VIEWER_READONLY_POSTS:
            return JSONResponse({"detail": "Viewer accounts are read-only"}, status_code=403)

        return await call_next(request)


# Deployments always use Secure cookies. Local HTTPS can opt in.
_session_https_only = deployment_auth_required() or os.getenv("SESSION_HTTPS_ONLY", "").strip().lower() in (
    "1", "true", "yes",
)

# Middleware ordering note: `add_middleware` registers in reverse — the
# LAST one added is the OUTERMOST layer (first to see the request). So
# SessionMiddleware must be added LAST so it runs before EnforceAuth and
# populates `request.session`.
#
# Gzip runs innermost (gets to see the final body) so we set minimum
# size to 1 KB — below that the overhead outweighs the wire savings.
app.add_middleware(GZipMiddleware, minimum_size=1024)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(EnforceAuthMiddleware)
app.add_middleware(
    SessionMiddleware,
    secret_key=session_secret(),
    session_cookie="kenyon_session",
    max_age=SESSION_TTL_DAYS * 86400,
    same_site="lax",
    https_only=_session_https_only,
)


base_dir = os.path.dirname(os.path.dirname(__file__))
app.mount("/static", StaticFiles(directory=os.path.join(base_dir, "static")), name="static")
templates = Jinja2Templates(directory=os.path.join(base_dir, "templates"))

# Auth FIRST so it's reachable even when other routers are behind the middleware.
app.include_router(auth_router.router, prefix="/api/auth", tags=["auth"])
app.include_router(developers.router, prefix="/api/developers", tags=["developers"])
# Excel-aware upload routes, persistence-safe field edits, and visible pipeline
# routes must be registered before the legacy deals router, which still exposes
# older handlers at some of the same paths.
app.include_router(deal_uploads.router, prefix="/api/deals", tags=["deal uploads"])
app.include_router(field_edits.router, prefix="/api/deals", tags=["field edits"])
app.include_router(deal_pipeline.router, prefix="/api/deals", tags=["deal pipeline"])
app.include_router(deals.router, prefix="/api/deals", tags=["deals"])
app.include_router(chat.router, prefix="/api/chat", tags=["chat"])
app.include_router(investments.router, prefix="/api/investments", tags=["investments"])
app.include_router(reports.router, prefix="/api/reports", tags=["reports"])
app.include_router(notifications_router.router, prefix="/api/notifications", tags=["notifications"])
app.include_router(admin_router.router, prefix="/api/admin", tags=["admin"])


def _dedupe_document_routes() -> None:
    """Keep the Excel-aware document handlers and remove legacy duplicates."""
    preferred = {
        ("/api/deals/{deal_id}/documents/upload", frozenset({"POST"})),
        ("/api/deals/documents/{doc_id}/reprocess", frozenset({"POST"})),
        ("/api/deals/documents/{doc_id}/file", frozenset({"GET"})),
    }
    seen_preferred: set[tuple[str, frozenset[str]]] = set()
    routes = []
    for route in app.router.routes:
        methods = frozenset(getattr(route, "methods", set()) or set())
        key = (getattr(route, "path", ""), methods)
        if key in preferred:
            endpoint_module = getattr(getattr(route, "endpoint", None), "__module__", "")
            if endpoint_module == "app.routers.deal_uploads":
                seen_preferred.add(key)
                routes.append(route)
            elif key not in seen_preferred:
                routes.append(route)
            continue
        routes.append(route)
    app.router.routes[:] = routes


_dedupe_document_routes()


@app.get("/api/healthz")
async def healthz():
    """Liveness + configuration probe.

    Returns:
      - status: "ok" | "degraded" — degraded if any required env is missing
      - models: active Anthropic model assignments
      - environment: per-service configuration status (anthropic, brave, db)
        each with a human-readable `message` when misconfigured.

    A dashboard banner can consume this to warn users before they click a
    button that would 503. Cached for 10s so every route visit in a
    short period shares one response.
    """
    env = environment_status()
    auth = describe_auth()
    degraded = any(not info.get("configured", True) for name, info in env.items()
                   if name != "anthropic" or not {"openai", "codex"}.intersection(env))
    # Auth being off isn't a crash but it's a real security concern — surface
    # it on healthz so the banner can warn even on an otherwise clean deploy.
    if not auth.get("enabled"):
        degraded = True
    body = {
        "status": "degraded" if degraded else "ok",
        "models": describe_models(),
        "environment": env,
        "auth": auth,
        "rate_limits": describe_policies(),
    }
    from app.version import release_identity
    body["release"] = release_identity()
    body["provider_readiness"] = "Configuration only; credits and semantic accuracy are not verified by this probe."
    return JSONResponse(body, headers={"Cache-Control": "private, max-age=10"})


@app.get("/api/healthz/ready", include_in_schema=False)
async def deployment_readiness():
    """Minimal deployment probe; detailed operational checks require an admin."""
    report = await readiness_report()
    return JSONResponse({"status": "ready" if report["deploy_ready"] else "not_ready"},
                        status_code=200 if report["deploy_ready"] else 503,
                        headers={"Cache-Control": "no-store"})


@app.get("/api/admin/readiness", include_in_schema=False)
async def operational_readiness(user: dict = Depends(require_auth)):
    if not is_analyst(user):
        raise HTTPException(status_code=403, detail="Admin access is required")
    report = await readiness_report()
    return JSONResponse(report, status_code=200 if report["deploy_ready"] else 503,
                        headers={"Cache-Control": "no-store"})


@app.get("/")
async def root_redirect():
    """The application UI is served by Next.js; direct API visits show retirement information."""
    return RedirectResponse(url="/legacy")


@app.get("/legacy")
async def legacy_index(request: Request):
    return JSONResponse({"detail": "This screen has been retired. Open the main app for the current reviewed analysis."}, status_code=410)

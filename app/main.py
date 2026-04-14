import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.requests import Request
from contextlib import asynccontextmanager
from app.database import init_db
from app.routers import developers, deals, chat, investments, reports


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
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
    """Liveness probe for Railway + load balancers."""
    return {"status": "ok"}


from fastapi.responses import RedirectResponse


@app.get("/")
async def root_redirect():
    """FastAPI now serves the legacy UI at /legacy. The new Next.js app (at
    web/) is expected to sit in front in production. During local FastAPI-only
    runs we redirect / → /legacy so the legacy UI is still reachable."""
    return RedirectResponse(url="/legacy")


@app.get("/legacy")
async def legacy_index(request: Request):
    return templates.TemplateResponse(request, "index.html")

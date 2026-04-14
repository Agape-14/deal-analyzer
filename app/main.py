import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.requests import Request
from contextlib import asynccontextmanager
from app.database import init_db
from app.routers import developers, deals, chat, investments


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


@app.get("/")
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

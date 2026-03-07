"""LeadPulse – FastAPI application entry point."""

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import APP_TITLE, APP_DESCRIPTION, APP_VERSION
from app.database import engine, Base

# ── Models must be imported so SQLAlchemy knows about them ────────────────────
from app.models import company, lead, job  # noqa: F401

# ── Routes ────────────────────────────────────────────────────────────────────
from app.routes import dashboard, search, leads, export, analytics

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
)
logger = logging.getLogger(__name__)

# ── Create tables ─────────────────────────────────────────────────────────────
Base.metadata.create_all(bind=engine)

# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(
    title=APP_TITLE,
    description=APP_DESCRIPTION,
    version=APP_VERSION,
)

# Templates & static files
_BASE = Path(__file__).resolve().parent
app.mount("/static", StaticFiles(directory=str(_BASE / "static")), name="static")
templates = Jinja2Templates(directory=str(_BASE / "templates"))
app.state.templates = templates  # shared via request.app.state

# ── IST timezone filter ──────────────────────────────────────────────────────
_IST = timezone(timedelta(hours=5, minutes=30))


def _to_ist(dt: datetime, fmt: str = "%b %d, %Y %H:%M") -> str:
    """Convert a datetime to IST and format it."""
    if dt is None:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(_IST).strftime(fmt)


templates.env.filters["ist"] = _to_ist

# ── Register routers ─────────────────────────────────────────────────────────
app.include_router(dashboard.router)
app.include_router(search.router)
app.include_router(leads.router)
app.include_router(export.router)
app.include_router(analytics.router)


# ── Health check ──────────────────────────────────────────────────────────────
@app.get("/health")
async def health():
    return {"status": "ok"}


logger.info("LeadPulse %s started", APP_VERSION)

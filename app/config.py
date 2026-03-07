"""Application configuration loaded from environment variables with sensible defaults."""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

DATABASE_URL: str = os.getenv("DATABASE_URL", f"sqlite:///{BASE_DIR / 'leads.db'}")

# Neon / Heroku-style URLs use "postgres://" which SQLAlchemy doesn't accept.
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

# ── Pipeline limits ──────────────────────────────────────────────────────────
MAX_COMPANIES_PER_JOB: int = int(os.getenv("MAX_COMPANIES_PER_JOB", "30"))
MAX_PAGES_PER_SITE: int = int(os.getenv("MAX_PAGES_PER_SITE", "5"))
REQUEST_TIMEOUT: int = int(os.getenv("REQUEST_TIMEOUT", "10"))
CRAWL_DELAY: float = float(os.getenv("CRAWL_DELAY", "1.0"))

# ── Quality thresholds ───────────────────────────────────────────────────────
MIN_LEAD_SCORE: int = int(os.getenv("MIN_LEAD_SCORE", "30"))

# ── App metadata ─────────────────────────────────────────────────────────────
APP_TITLE: str = "LeadPulse"
APP_DESCRIPTION: str = "Automated Business Lead Intelligence Platform"
APP_VERSION: str = "1.0.0"

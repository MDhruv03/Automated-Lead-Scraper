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
CRAWL_DELAY: float = float(os.getenv("CRAWL_DELAY", "1.5"))
MAX_RETRIES: int = int(os.getenv("MAX_RETRIES", "2"))

# ── Quality thresholds ───────────────────────────────────────────────────────
MIN_LEAD_SCORE: int = int(os.getenv("MIN_LEAD_SCORE", "40"))

# ── Industry keyword expansion (search term → relevant keywords) ─────────────
INDUSTRY_KEYWORDS: dict[str, list[str]] = {
    "healthcare": ["clinic", "hospital", "medical", "pharma", "diagnostic", "health", "wellness", "biotech", "therapeutics", "surgical", "dental", "nursing", "patient", "doctor", "physician"],
    "technology": ["software", "saas", "cloud", "tech", "digital", "app", "platform", "api", "devops", "cyber", "data", "computing"],
    "fintech": ["fintech", "payment", "banking", "finance", "insurance", "lending", "neobank", "invest", "trading", "credit"],
    "education": ["education", "edtech", "learning", "university", "school", "training", "course", "academy", "tutor"],
    "ecommerce": ["ecommerce", "e-commerce", "retail", "shop", "marketplace", "store", "cart", "fulfillment"],
    "marketing": ["marketing", "advertising", "seo", "content", "brand", "media", "creative", "agency", "campaign"],
    "real estate": ["real estate", "property", "housing", "construction", "architect", "realty", "builder", "developer"],
    "consulting": ["consulting", "advisory", "strategy", "management", "analyst", "audit"],
    "logistics": ["logistics", "supply chain", "shipping", "freight", "warehouse", "delivery", "cargo", "transport"],
    "manufacturing": ["manufacturing", "factory", "industrial", "production", "assembly", "machinery", "plant"],
    "food": ["food", "restaurant", "catering", "bakery", "beverage", "kitchen", "dining", "chef"],
    "automotive": ["automotive", "auto", "car", "vehicle", "motor", "automobile", "dealer"],
    "legal": ["legal", "law", "attorney", "lawyer", "advocate", "solicitor", "litigation", "counsel"],
    "agriculture": ["agriculture", "agri", "farm", "crop", "seed", "fertilizer", "dairy", "harvest"],
    "energy": ["energy", "solar", "wind", "power", "renewable", "oil", "gas", "electric", "utility"],
    "travel": ["travel", "tourism", "hotel", "hospitality", "flight", "booking", "resort", "tour"],
    "ai": ["artificial intelligence", "machine learning", "ai", "ml", "deep learning", "nlp", "data science", "neural"],
}

# ── App metadata ─────────────────────────────────────────────────────────────
APP_TITLE: str = "LeadPulse"
APP_DESCRIPTION: str = "Automated Business Lead Intelligence Platform"
APP_VERSION: str = "1.0.0"

# System Architecture

## High-Level Overview

LeadPulse is a full-stack web application built with **FastAPI** (Python) that automates business lead discovery. It finds companies via search engines, crawls their websites for contact information, enriches the data with NLP, scores each lead, and exports results to Excel.

```
┌──────────────┐       ┌──────────────────────────────────────────────┐
│   Browser    │──────▶│           FastAPI Application                │
│  (Tailwind)  │◀──────│   Jinja2 Templates · REST API · Static      │
└──────────────┘       │                                              │
                       │  ┌──────────┐  ┌──────────┐  ┌───────────┐  │
                       │  │Dashboard │  │  Search   │  │   Leads   │  │
                       │  │Analytics │  │  Jobs     │  │   Export  │  │
                       │  └──────────┘  └──────────┘  └───────────┘  │
                       │         │             │             │        │
                       │         ▼             ▼             ▼        │
                       │  ┌──────────────────────────────────────┐   │
                       │  │         SQLAlchemy ORM               │   │
                       │  │   SQLite (local) / PostgreSQL (prod) │   │
                       │  └──────────────────────────────────────┘   │
                       └──────────────────────────────────────────────┘
                                          │
                                          │ /api/worker/*
                                          ▼
                       ┌──────────────────────────────────────────────┐
                       │            Worker Daemon (worker.py)         │
                       │   Polls for jobs · Runs pipeline locally     │
                       │   Submits results back via REST API          │
                       └──────────────────────────────────────────────┘
```

## Technology Stack

| Layer | Technology | Why |
|-------|-----------|-----|
| Backend | FastAPI + Uvicorn | Async-capable, auto-generated OpenAPI docs, Pydantic validation |
| ORM | SQLAlchemy 2.x | Mature, supports SQLite + PostgreSQL with same models |
| Templates | Jinja2 + Tailwind CSS (CDN) | Server-rendered HTML, no build step, rapid iteration |
| Charts | Chart.js 4.4.7 | Client-side analytics with gradient fills, responsive |
| NLP | spaCy `en_core_web_sm` | Lightweight English model for NER, sentence segmentation |
| Scraping | Requests + BeautifulSoup (lxml) | Synchronous HTTP + fast HTML parsing |
| Search | Brave, DuckDuckGo, Google | Multi-engine fallback for resilience |
| DNS | dnspython | MX record lookup for email validation |
| Export | pandas + openpyxl | DataFrame-based Excel generation |
| Package Manager | uv | Fast dependency resolution, lockfile support |
| Deployment | Docker + Render | Containerized, free-tier PaaS |

## Database Schema

Three core tables with two relationship chains:

```
┌────────────────────┐
│       jobs         │
├────────────────────┤
│ id (PK)            │
│ query              │     ┌────────────────────┐
│ location           │     │    companies        │
│ status             │     ├────────────────────┤
│ total_companies    │     │ id (PK)            │
│ processed_companies│     │ name               │     ┌────────────────────┐
│ current_stage      │     │ website            │     │      leads         │
│ duration_seconds   │     │ domain             │     ├────────────────────┤
│ max_companies      │     │ industry           │     │ id (PK)            │
│ max_pages          │     │ city, country      │     │ company_id (FK)    │
│ min_score          │     │ description        │     │ email              │
│ created_at         │     │ tech_stack (JSON)  │     │ phone              │
│ completed_at       │     │ meta_description   │     │ address            │
└────────────────────┘     │ logo_url           │     │ linkedin           │
         │                 │ employee_estimate  │     │ lead_score         │
         │ 1:N             │ keywords (JSON)    │     │ email_valid        │
         ▼                 │ job_id (FK) ───────┤     │ role               │
    companies              │ created_at         │     │ score_breakdown    │
                           └────────────────────┘     │ extra_emails (JSON)│
                                    │                 │ source_url         │
                                    │ 1:N             │ created_at         │
                                    ▼                 └────────────────────┘
                               leads
```

### Key Design Choices

- **JSON columns** (`tech_stack`, `keywords`, `score_breakdown`, `extra_emails`) store variable-length lists without extra join tables. Deserialized via Python `@property` accessors on the ORM models.
- **Cascade deletes** — deleting a company auto-deletes its leads; deleting a job can cascade through companies.
- **Per-job settings** — `max_companies`, `max_pages`, `min_score` are stored on each job so users can tune pipeline behavior without changing environment config.

### Database Compatibility

The app works with both SQLite and PostgreSQL:
- **SQLite** — zero-config, file-based (`leads.db`), great for local development. Limited to single-writer.
- **PostgreSQL** — production-ready, supports concurrent connections. Neon-compatible (auto-converts `postgres://` → `postgresql://` in config).

Lightweight migrations run on startup in `app/main.py` using raw `ALTER TABLE` statements wrapped in try/except to add columns to existing tables without a migration framework.

## Request Flow

### Web UI Flow (Search → Results)

```
1. GET /search
   → Render search.html with default pipeline settings

2. POST /search (form data: industry, location, max_companies, max_pages, min_score)
   → Validate & clamp inputs
   → Create Job row (status="pending")
   → Redirect to /jobs/{id}

3. GET /jobs/{id}
   → Render job_status.html
   → JS polls GET /api/jobs/{id} every 3s
   → Shows stage progress bar (discovering → crawling → extracting → enriching → scoring)

4. Job completed → "View Leads" button appears
   → GET /leads?job_id={id}
   → Paginated lead table with filters
```

### API Flow (Programmatic Access)

```
POST /api/search     → {"job_id": 1, "status": "pending"}
GET  /api/jobs/1     → {"status": "running", "current_stage": "crawling", ...}
GET  /api/leads      → {"total": 25, "leads": [...]}
GET  /export         → leads_export.xlsx binary download
```

### Worker Flow

```
Worker daemon (worker.py) runs separately:

1. POST /api/worker/heartbeat    (every 25s, Bearer token auth)
2. GET  /api/worker/jobs          → list of pending jobs
3. POST /api/worker/claim/{id}   → mark job as "running"
4. [runs pipeline locally]
5. POST /api/worker/job/{id}/progress  (stage updates during execution)
6. POST /api/worker/job/{id}/results   (final companies + leads)
```

## Deployment Model

### Local Development
```bash
uv sync
uv run uvicorn app.main:app --reload
# SQLite auto-created at ./leads.db
```

### Production (Render)
- `render.yaml` defines a Docker web service
- PostgreSQL via Neon (DATABASE_URL env var)
- Worker runs as a separate process with WORKER_TOKEN auth
- Free tier: spins down after 15 min inactivity

### Docker
```dockerfile
FROM python:3.11-slim
# Install uv, sync deps, download spaCy model
# CMD: uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

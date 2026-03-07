# LeadPulse — Automated Business Lead Intelligence Platform

A web-based system that automatically discovers companies based on industry and location, crawls company websites, extracts contact information such as emails and phone numbers, enriches the data using NLP, validates emails, scores leads, and exports structured lead datasets for sales outreach.

---

## Features

| Capability | Detail |
|---|---|
| **Business Discovery** | Searches DuckDuckGo to find companies matching an industry + location query |
| **Website Crawling** | Visits homepage, contact, about & team pages (up to 5 per site) |
| **Contact Extraction** | Pulls emails, phone numbers, physical addresses and social-media profiles |
| **Email Validation** | Syntax checking + MX record lookup via DNS |
| **NLP Enrichment** | Industry detection, description generation and keyword extraction (spaCy) |
| **Lead Scoring** | 0–100 composite quality score based on data completeness |
| **Deduplication** | Domain-level and fuzzy company-name matching |
| **Excel Export** | One-click download of all leads as a formatted `.xlsx` file |
| **Live Job Tracking** | Real-time progress polling on the job-status page |

## Tech Stack

- **Backend** — Python 3.11, FastAPI, SQLAlchemy, Jinja2, Pydantic
- **Scraping** — Requests, BeautifulSoup4, lxml
- **NLP** — spaCy (`en_core_web_sm`)
- **Data** — pandas, openpyxl, tldextract, dnspython
- **Frontend** — TailwindCSS (CDN), Jinja templates
- **Database** — SQLite (zero-config, Render-compatible)
- **Deployment** — Docker, Render free tier

## Architecture

```
Browser  ──▶  FastAPI Web App
                 ├── Jinja Pages (Dashboard, Search, Leads)
                 ├── REST API (/api/search, /api/jobs, /api/leads)
                 └── BackgroundTasks Pipeline
                       ├── Business Discovery (DuckDuckGo)
                       ├── Website Crawler
                       ├── Contact Extraction
                       ├── NLP Enrichment
                       ├── Lead Scoring
                       └── Deduplication
                 ──▶  SQLite  ──▶  Excel Export
```

Everything runs inside a **single process** — no Redis, no Celery, no workers.

## Getting Started

### Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) (recommended)

### Install

```bash
uv sync
uv pip install en-core-web-sm@https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.7.1/en_core_web_sm-3.7.1-py3-none-any.whl
```

### Run

```bash
uv run uvicorn app.main:app --reload
```

Open [http://localhost:8000](http://localhost:8000).

### Environment Variables

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | `sqlite:///./leads.db` | Database connection string |
| `MAX_COMPANIES_PER_JOB` | `30` | Max companies discovered per search |
| `MAX_PAGES_PER_SITE` | `5` | Max pages crawled per website |
| `REQUEST_TIMEOUT` | `10` | HTTP request timeout in seconds |
| `CRAWL_DELAY` | `1.0` | Delay between requests in seconds |

## Deploy to Render

1. Push to GitHub
2. Connect repo on [Render](https://render.com)
3. The included `render.yaml` auto-configures a free Docker web service

## Project Structure

```
├── app/
│   ├── main.py              # FastAPI entry point
│   ├── config.py            # Environment config
│   ├── database.py          # SQLAlchemy setup
│   ├── models/              # ORM models (Company, Lead, Job)
│   ├── routes/              # Web + API routes
│   ├── services/            # Core pipeline services
│   │   ├── pipeline.py      # Orchestrator (BackgroundTasks)
│   │   ├── discovery_service.py
│   │   ├── crawler_service.py
│   │   ├── extraction_service.py
│   │   ├── enrichment_service.py
│   │   ├── scoring_service.py
│   │   └── dedupe_service.py
│   ├── utils/               # Email, phone & text helpers
│   └── templates/           # Jinja2 + Tailwind HTML
├── exports/                 # Excel export utility
├── pyproject.toml
├── uv.lock
├── Dockerfile
├── render.yaml
└── README.md
```

## Future Improvements

- Google Maps API integration
- LinkedIn company data enrichment
- CRM export (HubSpot, Salesforce)
- Automated email outreach sequences
- AI-powered lead ranking with ML models

---

*Built with FastAPI, Tailwind CSS & spaCy.*

# Design Decisions

Key trade-offs and technical choices made during the development of LeadPulse, and the reasoning behind them. Useful for interview discussions.

## 1. Why FastAPI over Flask/Django?

**Decision:** FastAPI with Jinja2 templates.

**Reasoning:**
- **Auto-generated OpenAPI** — free API documentation without extra effort
- **Pydantic validation** — request/response schema enforcement at the framework level
- **Async support** — though the pipeline uses synchronous requests (BeautifulSoup/lxml are sync), the web layer benefits from async request handling
- **Modern Python** — type hints, dataclasses, and Python 3.11 features are first-class

**Trade-off:** Django would provide an admin panel and ORM migrations out of the box. We compensated with lightweight `ALTER TABLE` migrations on startup.

## 2. Why Synchronous Scraping?

**Decision:** Synchronous `requests` library instead of `aiohttp` or Scrapy.

**Reasoning:**
- **Deliberate rate limiting** — we need `CRAWL_DELAY` between requests to avoid being blocked. Async concurrency would defeat this purpose.
- **Simpler error handling** — synchronous try/except is straightforward; async error propagation across tasks is complex.
- **robots.txt compliance** — Python's `RobotFileParser` is synchronous.
- **BeautifulSoup + lxml** — the fastest HTML parser for Python, and it's synchronous.

**Trade-off:** A single company's 5 pages are crawled sequentially (~7.5s per company at 1.5s delay). For 30 companies, this dominates pipeline time. But scraping faster would trigger anti-bot defenses.

## 3. Why Multi-Engine Search Fallback?

**Decision:** Brave → DuckDuckGo API → DDG HTML → Google scrape, with directory scraping first.

**Reasoning:**
- **No single reliable free search API** — Brave has rate limits, DDG API is unofficial, Google blocks automated queries
- **Resilience** — if one engine is down or rate-limited, the next one picks up
- **Directory scraping first** — listing pages (Builtin, Crunchbase) yield pre-curated real businesses. They're higher quality than individual search results.
- **Diverse results** — different engines return different companies, improving coverage

**Trade-off:** More complex code. Directory scraping adds latency. Google scraping is fragile (HTML structure changes).

## 4. Why One Lead Per Company?

**Decision:** Store only the best-scoring lead per company domain. Extra emails go in `extra_emails` JSON column.

**Reasoning:**
- **Data quality** — generic emails (`info@`, `contact@`) and role-specific emails (`careers@`, `press@`) have very different value. Picking the best one avoids cluttering the export.
- **Dedup simplicity** — domain-level dedup is a clean, unambiguous rule
- **Export usability** — sales teams want one row per company, not multiple rows per email

**Trade-off:** Some companies have multiple valuable contacts. The `extra_emails` column preserves these for users who want them.

## 5. Why Per-Job Settings Instead of Global Config?

**Decision:** `max_companies`, `max_pages`, `min_score` are stored per-job. Global env vars serve as fallback defaults.

**Reasoning:**
- **Different searches need different settings** — a quick exploratory search might want 10 companies, while a thorough research run wants 100
- **API users expect parameters** — programmatic clients should control behavior per-request
- **No env restarts** — changing settings shouldn't require redeploying the server

**Trade-off:** Slightly more complex plumbing (settings must thread through API → job → worker → pipeline → each service).

## 6. Why Worker Daemon Instead of Celery/Background Tasks?

**Decision:** Standalone `worker.py` that polls a REST API.

**Reasoning:**
- **No Redis/RabbitMQ dependency** — Render free tier doesn't provide a message broker
- **Decoupled execution** — worker can run on any machine (local laptop, VPS, separate container)
- **HTTP-only protocol** — no special infrastructure; worker talks to the same REST API as the web UI
- **Simple scaling** — run multiple workers and they compete for pending jobs (claim-based locking)

**Trade-off:** Polling is less efficient than push-based queues. The 30-second poll interval adds latency between job creation and execution start. Could be improved with WebSocket notification, but HTTP polling is simpler and more reliable.

## 7. Why SQLite + PostgreSQL Dual Support?

**Decision:** SQLAlchemy ORM with both SQLite and PostgreSQL backends.

**Reasoning:**
- **Zero-config local development** — SQLite needs no server installation
- **Production-ready scaling** — PostgreSQL handles concurrent connections from server + worker
- **Neon compatibility** — free PostgreSQL hosting with connection pooling

**Trade-off:** SQLite doesn't support concurrent writers. In production with a worker daemon, PostgreSQL is necessary for reliable concurrent job processing.

## 8. Why spaCy with Fallback?

**Decision:** Use spaCy `en_core_web_sm` for NLP, with pure-regex fallback.

**Reasoning:**
- **Quality** — spaCy's NER and sentence segmentation produce significantly better industry classification and descriptions than regex alone
- **Lightweight model** — `en_core_web_sm` is ~12MB, fits in free-tier containers
- **Resilience** — if spaCy install fails (e.g., missing model download), the pipeline still works with degraded quality rather than failing entirely

**Trade-off:** spaCy adds ~100MB to Docker image and ~1s per company for inference. English-only model means non-English sites get weaker enrichment.

## 9. Why Score Breakdown Transparency?

**Decision:** Store detailed score factor JSON alongside the numeric score.

**Reasoning:**
- **Explainability** — users can see exactly why a lead scored 85 vs 40
- **Debugging** — when scores seem wrong, the breakdown immediately shows which factor failed
- **No recomputation** — analytics can aggregate by factor without re-running the scoring logic

**Trade-off:** Extra storage per lead (~200 bytes JSON). Worth it for the UX benefit.

## 10. Why Aggressive Filtering Over Permissive Collection?

**Decision:** 9 quality gates that reject ~65-75% of discovered companies.

**Reasoning:**
- **Sales team trust** — a list of 25 high-quality leads is more valuable than 100 leads where 75 are junk
- **Email reputation** — sending outreach to invalid/irrelevant contacts hurts sender reputation
- **Signal-to-noise** — without strict filtering, results are dominated by blog posts, directories, and unrelated businesses

**Trade-off:** Some real companies get filtered out (false negatives). The `min_score` parameter lets users loosen the threshold when they want broader coverage.

## Known Limitations

1. **JavaScript-rendered sites** — pages that require JS execution (React SPAs with no SSR) yield empty HTML. This affects ~10-15% of modern websites.
2. **Non-English content** — spaCy model is English-only. Companies with non-English websites get weaker enrichment and may fail industry keyword matching.
3. **Search engine fragility** — Google and DuckDuckGo HTML scraping breaks when they change their page structure. Brave API is more stable but has stricter rate limits.
4. **Email deliverability ≠ MX records** — MX lookup confirms the domain accepts mail but says nothing about whether a specific mailbox exists or whether emails will land in inbox.
5. **No JS-based contact forms** — many modern sites use JavaScript contact forms instead of exposing email addresses. These contacts are invisible to HTML parsing.
6. **Rate limiting at scale** — running many searches in quick succession will trigger rate limits on search engines and potentially on target websites.
7. **SQLite write contention** — if the server and worker both write to the same SQLite file simultaneously, one will get a "database is locked" error. Use PostgreSQL for production.

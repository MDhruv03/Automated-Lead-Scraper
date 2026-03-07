# Worker Architecture

The worker daemon (`worker.py`) enables distributed pipeline execution. The web server accepts search jobs and stores them in the database; the worker polls for pending jobs, runs the pipeline locally, and submits results back via REST API.

## Why a Worker?

Free-tier hosting (Render, Railway) has two constraints:
1. **Request timeouts** — web requests must respond within 30–60 seconds. The pipeline takes 4–10 minutes.
2. **Single-process limits** — background threads in the web process compete for CPU with request handling.

The worker solves both: the web server responds instantly (creates a "pending" job), and the worker executes the pipeline asynchronously in a separate process.

## Architecture

```
┌─────────────────────┐                    ┌─────────────────────┐
│   Web Server         │  /api/worker/*    │   Worker Daemon      │
│   (Render/Docker)    │◀──────────────────│   (Local / VPS)      │
│                      │──────────────────▶│                      │
│  - Accepts searches  │  Bearer token     │  - Polls for jobs    │
│  - Stores jobs in DB │  authentication   │  - Runs pipeline     │
│  - Serves UI/API     │                   │  - Submits results   │
│  - Worker API routes │                   │  - Sends heartbeats  │
└─────────────────────┘                    └─────────────────────┘
```

## Server-Side API (app/routes/worker.py)

All endpoints are under `/api/worker/` and require Bearer token authentication (except `/status`).

### Authentication

```python
def _verify_secret(authorization: str):
    # Expects: "Bearer {WORKER_SECRET}"
    # WORKER_SECRET is set via environment variable
    # Returns 403 if token doesn't match
```

### Endpoints

| Method | Endpoint | Auth | Purpose |
|--------|----------|------|---------|
| POST | `/heartbeat` | Yes | Worker sends this every 25s to signal it's alive |
| GET | `/status` | No | Returns `{online: bool}` based on heartbeat freshness |
| GET | `/jobs` | Yes | Returns list of "pending" jobs with per-job settings |
| POST | `/claim/{job_id}` | Yes | Atomically marks job as "running", returns 409 if already claimed |
| POST | `/job/{id}/progress` | Yes | Updates `current_stage`, `total_companies`, `processed_companies` |
| POST | `/job/{id}/results` | Yes | Accepts companies + leads arrays, creates DB records, marks "completed" |
| POST | `/job/{id}/fail` | Yes | Marks job as "failed" with error message |

### Worker Online Detection

```python
_last_heartbeat: datetime | None = None

def is_worker_online() -> bool:
    if _last_heartbeat is None:
        return False
    return (utcnow() - _last_heartbeat).total_seconds() < WORKER_HEARTBEAT_TIMEOUT  # 90s
```

The dashboard displays a green/red status indicator based on this.

## Worker Daemon (worker.py)

### ServerClient Class

HTTP client wrapper that handles:
- **Multi-URL failover** — accepts a list of base URLs; tries each in order on failure
- **Bearer token auth** — adds `Authorization: Bearer {token}` to all requests
- **Connection pooling** — uses `requests.Session` for TCP reuse

```python
class ServerClient:
    def __init__(self, base_urls: list[str], secret: str):
        self.base_urls = base_urls
        self.session = requests.Session()
        self.session.headers["Authorization"] = f"Bearer {secret}"
    
    def heartbeat(self) -> bool
    def get_pending_jobs(self) -> list[dict]
    def claim(self, job_id: int) -> bool
    def progress(self, job_id: int, stage: str, total: int, processed: int) -> None
    def submit_results(self, job_id: int, companies: list, duration: float) -> None
    def fail(self, job_id: int, error: str) -> None
```

### Main Loop

```python
def main():
    # Parse args: --server, --secret, --interval
    client = ServerClient(base_urls, secret)
    
    # Start heartbeat thread (daemon)
    threading.Thread(target=_heartbeat_loop, args=(client, 25), daemon=True).start()
    
    while True:
        jobs = client.get_pending_jobs()
        if jobs:
            job = jobs[0]
            if client.claim(job["id"]):
                try:
                    run_local_pipeline(
                        client, job["id"], job["query"], job["location"],
                        max_companies=job.get("max_companies", 30),
                        max_pages=job.get("max_pages", 5),
                        min_score=job.get("min_score", 40)
                    )
                except Exception as e:
                    client.fail(job["id"], str(e))
        
        time.sleep(poll_interval)  # default 30s
```

### Pipeline Execution

`run_local_pipeline()` mirrors `app/services/pipeline.py` exactly:

1. **Discovery** — `discover_companies(query, location, max_results=max_companies)`
2. **Progress update** — `client.progress(job_id, "crawling", total, 0)`
3. **Per-company loop:**
   - Crawl website (max_pages)
   - Extract contacts
   - Validate business (≥3 signals)
   - Check location relevance
   - Check negative industry
   - Detect tech stack + metadata
   - Enrich with NLP
   - Score lead
   - Apply min_score threshold
   - Deduplicate
   - Progress update after each company
4. **Submit results** — `client.submit_results(job_id, companies_data, duration)`

### Heartbeat Thread

```python
def _heartbeat_loop(client: ServerClient, interval: int = 25):
    while True:
        client.heartbeat()  # POST /api/worker/heartbeat
        time.sleep(interval)
```

Runs as a daemon thread — dies when the main thread exits.

### Graceful Shutdown

```python
signal.signal(signal.SIGINT, _shutdown)
signal.signal(signal.SIGTERM, _shutdown)

def _shutdown(sig, frame):
    log.info("Shutting down worker...")
    sys.exit(0)
```

## Data Submission Protocol

When the pipeline completes, the worker sends all results in a single POST:

```json
POST /api/worker/job/{id}/results
{
  "companies": [
    {
      "name": "Acme Corp",
      "website": "https://acme.com",
      "domain": "acme.com",
      "industry": "SaaS",
      "city": "San Francisco",
      "description": "Cloud infrastructure platform...",
      "tech_stack": ["React", "AWS", "Stripe"],
      "meta_description": "Acme builds cloud tools...",
      "logo_url": "https://acme.com/og-image.png",
      "employee_estimate": "51-200",
      "keywords": ["cloud", "infrastructure", "DevOps"],
      "leads": [
        {
          "email": "hello@acme.com",
          "phone": "+1-415-555-0123",
          "address": "123 Market St, SF",
          "linkedin": "https://linkedin.com/company/acme",
          "lead_score": 85.0,
          "email_valid": true,
          "role": "General",
          "score_breakdown": "{\"email_mx\": 15, ...}",
          "source_url": "https://acme.com/contact",
          "extra_emails": "[\"sales@acme.com\", \"info@acme.com\"]"
        }
      ]
    }
  ],
  "duration_seconds": 245.7
}
```

The server creates Company and Lead records for each item and marks the job as "completed".

## Configuration

| Env Variable | Default | Purpose |
|-------------|---------|---------|
| `WORKER_SERVER_URL` | — | Base URL(s) of the LeadPulse server (comma-separated for failover) |
| `WORKER_TOKEN` / `WORKER_SECRET` | — | Shared secret for Bearer auth |
| `--interval` (CLI) | 30 | Seconds between job polls |

## Error Handling

- **Network failures:** retried across all base URLs before giving up
- **Pipeline exceptions:** caught and reported via `/api/worker/job/{id}/fail`
- **Server unavailable:** worker logs error and continues polling
- **Job already claimed:** server returns 409 Conflict; worker skips and polls again

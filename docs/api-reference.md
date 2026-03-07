# API Reference

All REST endpoints exposed by LeadPulse, grouped by function.

## Public Web Pages

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | Dashboard — stats, recent jobs, top leads |
| GET | `/search` | Search form with pipeline settings |
| POST | `/search` | Submit search (form data) → redirect to job status |
| GET | `/jobs/{id}` | Job status page (polls API for progress) |
| GET | `/leads` | Paginated leads table with filters |
| GET | `/analytics` | Analytics dashboard with charts |
| GET | `/export` | Download all leads as `leads_export.xlsx` |
| GET | `/health` | Health check → `{"status": "ok"}` |

## Search API

### Start a Search

```
POST /api/search
Content-Type: application/json
```

**Request Body:**
```json
{
  "industry": "SaaS",
  "location": "New York",
  "max_companies": 30,
  "max_pages": 5,
  "min_score": 40
}
```

| Field | Type | Required | Range | Default |
|-------|------|----------|-------|---------|
| `industry` | string | yes | — | — |
| `location` | string | yes | — | — |
| `max_companies` | int | no | 5–100 | 30 |
| `max_pages` | int | no | 1–10 | 5 |
| `min_score` | int | no | 0–100 | 40 |

**Response (201):**
```json
{
  "job_id": 1,
  "status": "pending"
}
```

### Check Job Status

```
GET /api/jobs/{job_id}
```

**Response (200):**
```json
{
  "id": 1,
  "query": "SaaS",
  "location": "New York",
  "status": "running",
  "current_stage": "crawling",
  "stage_index": 2,
  "total_companies": 30,
  "processed_companies": 12,
  "max_companies": 30,
  "max_pages": 5,
  "min_score": 40,
  "created_at": "2025-01-15T10:30:00",
  "completed_at": null,
  "duration": null
}
```

**Status values:** `pending`, `running`, `completed`, `failed`

**Stage values (in order):** `queued` → `discovering` → `crawling` → `extracting` → `enriching` → `scoring` → `completed`

### Delete a Job

```
POST /jobs/{job_id}/delete
```

Cascades: deletes all companies and leads associated with the job.

### Delete All Jobs

```
POST /jobs/delete-all
```

Truncates all jobs, companies, and leads tables. Resets auto-increment sequences.

## Leads API

### List Leads

```
GET /api/leads?page=1&min_score=60&industry=SaaS&city=New+York&job_id=1
```

| Param | Type | Description |
|-------|------|-------------|
| `page` | int | Page number (1-indexed, 20 per page) |
| `min_score` | float | Minimum lead score filter |
| `industry` | string | Filter by industry (ILIKE match) |
| `city` | string | Filter by city (ILIKE match) |
| `job_id` | int | Filter by originating job |

**Response (200):**
```json
{
  "total": 45,
  "page": 1,
  "per_page": 20,
  "leads": [
    {
      "id": 1,
      "company": "Acme Corp",
      "website": "https://acme.com",
      "domain": "acme.com",
      "email": "hello@acme.com",
      "email_valid": true,
      "phone": "+1-415-555-0123",
      "linkedin": "https://linkedin.com/company/acme",
      "address": "123 Market St, SF",
      "industry": "SaaS",
      "city": "San Francisco",
      "lead_score": 85.0,
      "role": "General",
      "tech_stack": ["React", "AWS", "Stripe"],
      "source_url": "https://acme.com/contact"
    }
  ]
}
```

Leads are sorted by `lead_score` descending.

### Delete a Lead

```
POST /leads/{lead_id}/delete
```

### Delete All Leads

```
POST /leads/delete-all
```

## Export

### Download Excel

```
GET /export
```

Returns: `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`

**Excel columns (16):**
Company Name, Website, Domain, Email, Extra Emails, Email Valid, Contact Role, Phone, LinkedIn, Address, Industry, City, Tech Stack, Employee Estimate, Lead Score, Source URL

## Worker API

All endpoints except `/status` require Bearer token authentication.

```
Authorization: Bearer {WORKER_SECRET}
```

### Heartbeat

```
POST /api/worker/heartbeat
```
Response: `{"ok": true}`

### Worker Status (public)

```
GET /api/worker/status
```
Response: `{"online": true}` or `{"online": false}`

Online = heartbeat received within last 90 seconds.

### Get Pending Jobs

```
GET /api/worker/jobs
```

**Response:**
```json
[
  {
    "id": 1,
    "query": "SaaS",
    "location": "New York",
    "max_companies": 30,
    "max_pages": 5,
    "min_score": 40
  }
]
```

### Claim a Job

```
POST /api/worker/claim/{job_id}
```

Atomically sets `status="running"`, `current_stage="discovering"`.

Returns 409 if job is no longer in "pending" status (another worker claimed it).

### Update Progress

```
POST /api/worker/job/{job_id}/progress
Content-Type: application/json
```

```json
{
  "current_stage": "crawling",
  "total_companies": 30,
  "processed_companies": 12
}
```

### Submit Results

```
POST /api/worker/job/{job_id}/results
Content-Type: application/json
```

```json
{
  "companies": [
    {
      "name": "Acme Corp",
      "website": "https://acme.com",
      "domain": "acme.com",
      "industry": "SaaS",
      "city": "San Francisco",
      "country": "US",
      "description": "Cloud platform...",
      "tech_stack": ["React", "AWS"],
      "meta_description": "...",
      "logo_url": "...",
      "employee_estimate": "51-200",
      "keywords": ["cloud", "infrastructure"],
      "leads": [
        {
          "email": "hello@acme.com",
          "phone": "+1-415-555-0123",
          "address": "123 Market St",
          "linkedin": "...",
          "lead_score": 85.0,
          "email_valid": true,
          "role": "General",
          "score_breakdown": "{...}",
          "source_url": "https://acme.com/contact",
          "extra_emails": "[\"sales@acme.com\"]"
        }
      ]
    }
  ],
  "duration_seconds": 245.7
}
```

Creates Company + Lead records in DB. Sets `job.status="completed"`, records duration.

### Fail a Job

```
POST /api/worker/job/{job_id}/fail
Content-Type: application/json
```

```json
{
  "error": "Pipeline timeout after 600s"
}
```

Sets `job.status="failed"`.

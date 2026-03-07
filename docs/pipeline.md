# Pipeline Deep Dive

The pipeline is the core of LeadPulse — an 8-stage sequential process that transforms a search query into scored, validated leads. It runs either server-side (`app/services/pipeline.py`) or on the worker daemon (`worker.py`).

## Pipeline Stages

```
┌─────────────┐   ┌─────────────┐   ┌─────────────┐   ┌─────────────┐
│  Discovery   │──▶│   Crawling   │──▶│  Extraction  │──▶│  Tech Detect │
│ (search +    │   │ (homepage +  │   │ (emails,     │   │ (40+ tech    │
│  scraping)   │   │  sub-pages)  │   │  phones,     │   │  signatures) │
└─────────────┘   └─────────────┘   │  addresses)  │   └─────────────┘
                                     └─────────────┘          │
                                                               ▼
┌─────────────┐   ┌─────────────┐   ┌─────────────┐   ┌─────────────┐
│   Export     │◀──│   Dedup      │◀──│   Scoring    │◀──│  Enrichment  │
│ (Excel /     │   │ (domain +    │   │ (0-100       │   │ (spaCy NLP:  │
│  API)        │   │  fuzzy name) │   │  composite)  │   │  industry,   │
└─────────────┘   └─────────────┘   └─────────────┘   │  keywords)  │
                                                       └─────────────┘
```

## Stage Details

### 1. Discovery

**File:** `app/services/discovery_service.py`

Finds businesses matching the user's industry + location query.

**Strategy:**
1. Build search queries: `"{industry} companies in {location}"`, `"{industry} startups {location}"`, etc.
2. First, search for **directory/listing pages** and scrape individual company links from them
3. If still under target count, use multi-engine search: **Brave → DuckDuckGo API → DuckDuckGo HTML → Google scrape**
4. Each result is filtered by domain denylist, title relevance, and article URL patterns

**Per-job setting:** `max_companies` (default 30, range 5–100)

### 2. Crawling

**File:** `app/services/crawler_service.py`

Fetches key pages from each discovered company website.

**Pages crawled:**
- Homepage (`/`)
- Business sub-pages: `/contact`, `/about`, `/team`, `/company`, `/about-us`, `/contact-us`
- Stops at the per-job `max_pages` limit

**Quality controls:**
- Respects `robots.txt` (fetches and parses via `RobotFileParser`)
- Exponential backoff on 429/503 (wait = `CRAWL_DELAY × 2^attempt`)
- Realistic browser headers (Chrome User-Agent)
- Configurable request timeout and crawl delay

**Per-job setting:** `max_pages` (default 5, range 1–10)

### 3. Extraction

**File:** `app/services/extraction_service.py`

Pulls structured contact data from raw HTML.

**Extracted fields:**
- **Emails** — regex + deobfuscation (`[at]` → `@`, `[dot]` → `.`) + denylist filtering
- **Phones** — international regex (7–15 digits), normalized formatting
- **Addresses** — US/India street address patterns (up to 5 per company)
- **Social links** — LinkedIn, Twitter/X, Facebook URL patterns

**Cross-page merge:** contacts from all crawled pages are merged and deduplicated. Emails are case-insensitive deduped; phones are deduped by digit-only key.

### 4. Tech Detection

**File:** `app/services/techdetect_service.py`

Identifies technologies used by the company from HTML content.

**40+ signatures across categories:**
- CMS: WordPress, Shopify, Wix, Squarespace, Webflow, Drupal, Joomla
- JS Frameworks: React, Next.js, Vue, Angular, Svelte
- Analytics: Google Analytics, GTM, Hotjar, Mixpanel, Segment
- Infrastructure: Cloudflare, AWS, Vercel, Netlify
- Support: Intercom, Zendesk, Drift
- Payments: Stripe, PayPal, Razorpay

**Also extracts:** meta description, OG tags, logo URL, employee estimate (regex patterns for "X employees" / "team of X").

### 5. Enrichment

**File:** `app/services/enrichment_service.py`

NLP-based enrichment using spaCy `en_core_web_sm`.

**Outputs:**
- **Industry classification** — matches site text against 10 keyword categories; if spaCy available, uses entity context for disambiguation
- **Description** — extracts 1–2 meaningful sentences (>30 chars) from page text, caps at 500 chars
- **Keywords** — spaCy NER (ORG, PRODUCT, GPE) + noun chunks; fallback: frequency of capitalized words, top 8

**Graceful fallback:** if spaCy model is unavailable (e.g., not installed), all three functions fall back to pure-regex heuristics.

### 6. Scoring

**File:** `app/services/scoring_service.py`

Assigns a 0–100 composite quality score with a detailed breakdown.

| Factor | Points | Condition |
|--------|--------|-----------|
| Valid MX Email | 15 | Email exists AND domain has MX record |
| Phone Present | 10 | At least one phone number extracted |
| Contact Page | 15 | /contact, /about, or /team page found |
| Industry Keyword | 15 | Industry term appears in site text |
| Location Match | 15 | Location term appears in site text |
| Active Website | 10 | ≥1 page crawled successfully |
| Multiple Contacts | 10 | Both email AND phone found |
| Domain Legitimacy | 10 | Domain <50 chars, <3 hyphens |
| High-Risk Domain | -15 | Penalty for suspicious domains |
| **Max Total** | **100** | `max(0, sum)` |

The breakdown is serialized to JSON and stored in `leads.score_breakdown` for transparency.

**Email validation:** DNS MX record lookup via `dnspython` with 5-second timeout. Confirms the domain accepts mail (doesn't verify individual mailboxes).

### 7. Deduplication

**File:** `app/services/dedupe_service.py`

Prevents duplicate companies and leads.

**Two-level dedup:**
1. **Domain-level** — exact match on registered domain (via tldextract)
2. **Fuzzy name** — `SequenceMatcher` with ≥0.85 similarity against the most recent 200 companies. Names are normalized: lowercased, punctuation stripped, whitespace collapsed.

**One lead per company:** the pipeline picks the best-scoring email per company domain. Additional emails are stored in `extra_emails` JSON column.

### 8. Export

**File:** `exports/exporter.py` + `app/routes/export.py`

Generates a formatted `.xlsx` file with 16 columns including company info, contacts, scores, and tech stack.

## Quality Gates

Between stages, the pipeline applies multiple filters. A company is **skipped** if any gate fails:

```
Domain not in denylist?             → skip "blocked domain"
≥1 page crawled?                    → skip "crawl failed"
URL not an article/blog?            → skip "article URL"
Business validation ≥3 signals?     → skip "not a business page"
Location term in site text?         → skip "location mismatch"
Industry keyword in site text?      → skip "no industry relevance"
Not an agency/recruiter site?       → skip "negative industry"
≥1 contact (email OR phone)?        → skip "no contacts"
Lead score ≥ min_score threshold?   → skip "score too low"
Domain not already in DB?           → skip "duplicate"
```

All skip reasons are logged with the company name for debugging.

## Per-Job Settings

Users can configure three pipeline parameters per search job:

| Setting | Default | Range | Affects |
|---------|---------|-------|---------|
| `max_companies` | 30 | 5–100 | Number of companies the discovery stage finds |
| `max_pages` | 5 | 1–10 | Pages crawled per company website |
| `min_score` | 40 | 0–100 | Score threshold; leads below this are discarded |

These are stored on the `jobs` table and passed through the entire pipeline. They override the global env config values (`MAX_COMPANIES_PER_JOB`, `MAX_PAGES_PER_SITE`, `MIN_LEAD_SCORE`), which now serve only as fallback defaults.

## Timing Estimates

Rough per-stage timings (varies by network and site response times):

| Stage | ~Time |
|-------|-------|
| Discovery | 20–40 seconds (search engine queries + directory scraping) |
| Crawling | `companies × pages × 1.5s` (dominated by CRAWL_DELAY) |
| Extraction | <1s per company (regex on cached HTML) |
| Tech Detection | <0.5s per company (regex on cached HTML) |
| Enrichment | ~1s per company (spaCy model inference) |
| Scoring | <0.5s per company (DNS MX lookup is the bottleneck) |
| Dedup | <0.1s per company (in-memory comparison) |

**Example:** 30 companies × 5 pages ≈ 30s discovery + 225s crawling + 30s processing ≈ **4–6 minutes total**.

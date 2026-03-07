# Data Extraction

This document covers how LeadPulse extracts structured data from raw HTML: contacts, technology stack, metadata, and social profiles.

## Contact Extraction

**File:** `app/services/extraction_service.py`

### Email Extraction

1. **Deobfuscation** — before regex, common obfuscation patterns are reversed:
   - `[at]`, `(at)`, ` at ` → `@`
   - `[dot]`, `(dot)`, ` dot ` → `.`
   - This catches emails like `info[at]company[dot]com`

2. **Regex** — a permissive RFC-5322-ish pattern captures emails from the deobfuscated text

3. **Filtering:**
   - Remove denylist prefixes: `noreply`, `no-reply`, `admin`, `postmaster`, `mailer-daemon`, `webmaster`
   - Remove denylist domains: `example.com`, `sentry.io`, `googleapis.com`, `wixpress.com`
   - Remove asset filenames: anything ending in `.png`, `.jpg`, `.gif`, `.svg`, `.css`, `.js`
   - Case-insensitive deduplication

4. **Role classification** — each email's local part is categorized:
   - Executive: `ceo`, `cto`, `founder`, `director`, `vp`, `chief`
   - Sales: `sales`, `partnerships`, `revenue`
   - Marketing: `marketing`, `seo`, `content`, `brand`
   - Support: `support`, `help`, `customer`
   - HR: `recruiting`, `talent`, `careers`
   - Technical: `dev`, `engineer`, `devops`
   - Finance: `finance`, `accounting`, `invoice`
   - Legal: `legal`, `compliance`, `privacy`
   - General: `info`, `contact`, `team`
   - Personal: detected via `first.last` pattern
   - Default: "Unknown"

### Phone Extraction

**File:** `app/utils/phone_utils.py`

- **Regex:** matches international phone formats (7–15 digits with optional `+`, spaces, hyphens, parentheses)
- **Dedup:** by digit-only key (strips all formatting before comparing)
- **Normalization:** excess whitespace and dangling hyphens are cleaned

### Address Extraction

- **US pattern:** `123 Street Name Avenue/Road/Drive, City, State ZIP`
- **India pattern:** `Sector/Nagar/Colony, City` format
- Capped at 5 addresses per company to prevent noise from directories

### Social Links

**File:** `app/utils/text_utils.py`

Regex extraction from `<a href="...">` attributes:
- LinkedIn: `/linkedin\.com\/(in|company)\//`
- Twitter/X: `/twitter\.com\/|x\.com\//`
- Facebook: `/facebook\.com\//`

### Cross-Page Merging

The `merge_contacts()` function consolidates data from all crawled pages:
- Emails: case-insensitive set union
- Phones: digit-only key dedup
- Addresses: append up to cap of 5
- LinkedIn: keep first found
- Source URL: keep the page with the most contacts

## Technology Detection

**File:** `app/services/techdetect_service.py`

### HTML Signature Matching

Each technology has one or more HTML patterns it looks for:

| Category | Technology | HTML Signature |
|----------|-----------|---------------|
| CMS | WordPress | `wp-content/`, `wordpress` |
| CMS | Shopify | `cdn.shopify.com`, `Shopify.` |
| CMS | Wix | `wix.com`, `wixstatic.com` |
| CMS | Squarespace | `squarespace.com`, `sqsp.` |
| CMS | Webflow | `webflow.com` |
| Framework | React | `react.`, `__NEXT_DATA__`, `ReactDOM` |
| Framework | Next.js | `_next/`, `__NEXT` |
| Framework | Vue.js | `vue.`, `__vue` |
| Framework | Angular | `ng-`, `angular.` |
| Library | jQuery | `jquery` |
| Library | Bootstrap | `bootstrap` |
| Library | Tailwind | `tailwind` |
| Analytics | Google Analytics | `gtag(`, `google-analytics`, `GoogleAnalyticsObject` |
| Analytics | GTM | `googletagmanager.com` |
| Analytics | Hotjar | `hotjar.com` |
| Analytics | Mixpanel | `mixpanel.com` |
| Infra | Cloudflare | `cloudflare`, `cf-ray` |
| Infra | AWS | `amazonaws.com` |
| Infra | Vercel | `vercel`, `_vercel` |
| Support | Intercom | `intercom`, `intercomSettings` |
| Support | Zendesk | `zendesk`, `zdassets` |
| Payments | Stripe | `stripe.com`, `Stripe(` |
| Payments | PayPal | `paypal.com` |
| Payments | Razorpay | `razorpay.com` |

### Header-Based Detection

If HTTP response headers are available:
- `Server: nginx` → Nginx
- `Server: Apache` → Apache
- `Server: cloudflare` → Cloudflare
- `X-Powered-By: PHP` → PHP
- `X-Powered-By: Express` → Express.js
- `X-Powered-By: ASP.NET` → ASP.NET

### Metadata Extraction

From `<meta>` and `<og:>` tags:
- `meta_description` — `<meta name="description" content="...">`
- `og_title` — `<meta property="og:title" content="...">`
- `og_description` — `<meta property="og:description" content="...">`
- `og_image` — `<meta property="og:image" content="...">` (used as logo URL)

### Company Size Estimation

Regex heuristics on page text:
- `"\d+ employees"` or `"team of \d+"` → map to ranges:
  - 1–10, 11–50, 51–200, 201–1K, 1K–10K, 10K+
- Keyword heuristics:
  - `"enterprise"` → 201–1K
  - `"startup"` → 1–10
  - `"founded 202X"` → 1–10

## NLP Enrichment

**File:** `app/services/enrichment_service.py`

### Industry Classification

**spaCy path:**
- Process combined page text through `en_core_web_sm`
- Count occurrences of industry keywords (16 categories × 10–15 keywords each)
- Highest count wins; ties broken by order

**Fallback (no spaCy):**
- Same keyword counting on raw text
- No entity context, slightly noisier

### Description Generation

**spaCy path:**
- Use `doc.sents` to extract sentences
- Filter: length >30 chars, not starting with "Home", "Menu", "Skip"
- Join first 2 qualifying sentences, cap at 500 chars

**Fallback:**
- Split text by `.!?` punctuation
- Same filtering and joining logic

### Keyword Extraction

**spaCy path:**
- Extract named entities: ORG, PRODUCT, GPE, NORP, WORK_OF_ART
- Extract noun chunks (>3 chars, not stopwords)
- Deduplicate and return top 8 by frequency

**Fallback:**
- Find capitalized words ≥3 chars
- Score by frequency, return top 8

# Scoring & Validation

This document covers the lead scoring algorithm, business validation, location relevance checking, and negative industry filtering — the quality gates that separate genuine leads from noise.

## Lead Scoring Algorithm

**File:** `app/services/scoring_service.py`

Every lead receives a composite score from 0 to 100. The score is the sum of individual factors:

### Score Factors

| Factor | Points | Logic |
|--------|--------|-------|
| **Valid MX Email** | +15 | Email is present AND domain has an MX record (DNS lookup) |
| **Phone Present** | +10 | At least one phone number was extracted |
| **Contact Page Found** | +15 | At least one of /contact, /about, /team was crawled successfully |
| **Industry Keyword** | +15 | At least one term from the query industry appears in the combined page text |
| **Location Match** | +15 | At least one location term (city, state, country aliases) appears in the text |
| **Active Website** | +10 | At least 1 page was crawled with HTTP 200 |
| **Multiple Contacts** | +10 | Both email AND phone are present (indicates a real, reachable business) |
| **Domain Legitimacy** | +10 | Domain is <50 chars and has <3 hyphens |
| **High-Risk Domain** | -15 | Penalty if domain looks suspicious (many hyphens, very long, unusual TLD) |

**Final score:** `max(0, sum_of_all_factors)` — never goes negative.

### Score Breakdown Storage

Each factor's contribution is serialized to JSON and stored in `leads.score_breakdown`:

```json
{
  "email_mx": 15,
  "phone": 10,
  "contact_page": 15,
  "industry_keyword": 0,
  "location_match": 15,
  "active_site": 10,
  "multiple_contacts": 10,
  "domain_legit": 10,
  "high_risk": 0
}
```

This enables transparency — users can see exactly why a lead scored the way it did.

### Quality Tiers (used in analytics)

| Tier | Score Range | Typical Characteristics |
|------|-------------|------------------------|
| High | ≥70 | Valid email, phone, location match, industry match |
| Medium | 40–69 | Some contacts, partial validation passes |
| Low | <40 | Missing contacts or failed validation |

### Email Validation (MX Lookup)

```python
dns.resolver.resolve(domain, "MX", lifetime=5)
```

- Extracts the domain from the email address
- Queries DNS for MX records with a 5-second timeout
- If MX records exist → domain accepts email → `email_valid = True`
- Does NOT verify individual mailboxes (impossible without sending a test email)
- Timeout/NXDOMAIN/NoAnswer → `email_valid = False`

## Business Validation

**File:** `app/services/validation_service.py`

### Purpose

Not every website that appears in search results is a real business. Blog posts, listicle articles, personal portfolios, and documentation sites all need to be filtered out.

### Algorithm: `validate_business(html)`

1. **Count business signals** — scan the HTML text for 18 indicator phrases:
   - "about us", "our services", "contact us", "our team"
   - "careers", "testimonials", "partners", "copyright"
   - "privacy policy", "terms of service", "headquarters"
   - "case studies", "portfolio", "solutions", "pricing"
   - "clients", "our mission", "founded"

2. **Count anti-signals** — 17 phrases that indicate non-business content:
   - "subscribe", "posted by", "written by", "comment"
   - "how to", "tutorial", "advertisement", "sponsored"
   - "share this", "read more", "related posts"
   - "author bio", "tags:", "filed under", "next article"
   - "table of contents", "disclaimer"

3. **Calculate confidence:**
   ```
   score = business_signals - 0.5 × anti_signals
   confidence = score / max(1, business_signals + anti_signals)
   ```

4. **Pass/fail:** requires **≥3 business signals** AND **confidence > 0.2**

5. **Returns:** `(is_business: bool, confidence: float, signals_found: list[str])`

### Why This Works

Real company websites almost always have "about us", "contact us", "privacy policy" footer links. Blog posts and articles typically have "posted by", "comments", "related posts" instead. The 0.5 weighting on anti-signals means a site can have a few blog indicators and still pass if it has strong business signals.

## Location Relevance

**File:** `app/services/validation_service.py`

### Purpose

If a user searches for "SaaS companies in Bangalore", we need to verify the discovered company actually has a presence in Bangalore — not just that it appeared in search results about Bangalore.

### Algorithm: `check_location_relevance(text, location_terms)`

1. **Expand location:** `get_location_terms("Bangalore")` returns:
   - `["bangalore", "bengaluru", "karnataka", "india"]`
   
2. **Alias map** (20 cities with alternate names):
   - Bangalore → bengaluru
   - New York → nyc, manhattan
   - Mumbai → bombay
   - San Francisco → sf, bay area
   - London → uk, united kingdom
   - etc.

3. **Check:** case-insensitive search for any term in the combined page text

4. **Returns:** `True` if any location term is found

This catches companies that mention "Bengaluru" (official name) when the user searched for "Bangalore", or "NYC" when searching for "New York".

## Negative Industry Filter

**File:** `app/services/validation_service.py`

### Purpose

The pipeline needs to reject companies that match the search terms but are in a "wrong" industry — typically agencies, recruiters, and insurance products that SEO-optimize for industry keywords.

### Algorithm: `check_negative_industry(text, query_industry)`

**Agency detection (20+ patterns):**
- "seo agency", "digital marketing agency", "recruiting agency"
- "consulting firm", "lead generation services", "web design agency"
- "branding agency", "pr agency", "staffing agency"
- "outsourcing company", "freelance marketplace"

**Bypass:** if the user explicitly searches for marketing, SEO, or consulting, the agency filter is skipped (they want agencies).

**Insurance product detection (10+ patterns):**
- "health insurance plans", "insurance premium", "insurance quote"
- "compare plans", "buy insurance", "term insurance"
- "claim settlement", "premium calculator"

**Bypass:** if the user searches for "insurance" or "insurtech", the filter is skipped.

**Returns:** `(should_reject: bool, reason: str)`

### Why This Matters

Without this filter, a search for "SaaS companies in London" might return digital marketing agencies that serve SaaS companies, or a search for "healthcare in Mumbai" might return insurance comparison portals. The negative filter catches these using keyword patterns specific to service-provider and comparison sites.

## Quality Gate Summary

The pipeline applies all validation checks in sequence. Here's the complete filter chain with typical rejection rates:

```
100 discovered companies
  ├── Domain denylist filter          → ~5% rejected  (social media, news, etc.)
  ├── Article URL filter              → ~10% rejected (blog posts, careers pages)
  ├── Business validation (≥3 signals) → ~15% rejected (portfolios, docs, forums)
  ├── Location relevance              → ~10% rejected (no location mention on site)
  ├── Industry keyword match          → ~5% rejected  (unrelated businesses)
  ├── Negative industry filter        → ~5% rejected  (agencies, recruiters)
  ├── Contact presence (email/phone)  → ~10% rejected (no extractable contacts)
  ├── Score threshold (≥ min_score)   → ~10% rejected (low-quality leads)
  └── Deduplication                   → ~5% rejected  (already in DB)
  
  ≈ 25-35 leads from 100 companies (typical yield)
```

Rejection rates vary significantly by industry and location. Well-established tech hubs (e.g., "SaaS in San Francisco") yield higher rates than niche searches.

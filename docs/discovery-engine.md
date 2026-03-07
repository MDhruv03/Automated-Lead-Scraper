# Discovery Engine

The discovery service (`app/services/discovery_service.py`) is responsible for finding real businesses that match a user's industry + location query. It's the most complex service in the pipeline due to multiple search strategies, aggressive filtering, and fallback chains.

## Search Strategy

### Phase 1: Directory Scraping

Before hitting search engines for individual companies, the system first looks for **directory/listing pages** that aggregate companies.

1. Search for listing pages using queries like `"top {industry} companies in {location} list"`, `"{industry} startups {location} directory"`
2. Fetch each listing page HTML
3. Extract all `<a>` tags that link to external company websites
4. Filter extracted links through the same domain denylist and relevance checks

This approach yields higher-quality results because directory sites like Builtin, Crunchbase, and GoodFirms curate real businesses.

### Phase 2: Multi-Engine Search

For remaining quota, search engines are queried in a **fallback chain:**

```
Brave Search API  ──(fail)──▶  DuckDuckGo API  ──(fail)──▶  DDG HTML Scrape  ──(fail)──▶  Google HTML Scrape
```

Each engine returns `(title, url)` pairs. The system:
1. Extracts the registered domain via `tldextract`
2. Checks against denylist
3. Checks title relevance
4. Checks article URL patterns
5. Deduplicates by domain

If an engine fails (network error, rate limit, empty results), the next engine in the chain is tried.

### Search Queries Generated

Multiple query variations improve coverage:
- `"{industry} companies in {location}"`
- `"{industry} startups {location}"`
- `"best {industry} companies {location}"`
- `"top {industry} firms in {location}"`
- `"{industry} services {location}"`

## Filtering Layers

### 1. Domain Denylist (~100 domains)

A hardcoded set of domains that are never returned as company results:

| Category | Examples |
|----------|---------|
| Social media | linkedin.com, facebook.com, twitter.com, instagram.com, youtube.com |
| Blog platforms | medium.com, wordpress.com, substack.com, blogger.com |
| Reference | wikipedia.org, britannica.com |
| E-commerce | amazon.com, ebay.com, alibaba.com, etsy.com |
| News | bbc.com, cnn.com, bloomberg.com, forbes.com, timesofindia.com |
| Search engines | google.com, bing.com, duckduckgo.com |
| Job boards | glassdoor.com, indeed.com, naukri.com, zoominfo.com |
| SaaS tools | zoho.com, hubspot.com, salesforce.com, slack.com |
| Directories | crunchbase.com, f6s.com, goodfirms.co (scraped but not returned) |

### 2. Domain Heuristics

Domains are rejected if:
- Length >60 characters (likely spam/parked)
- Contains ≥3 hyphens (SEO spam indicator)
- TLD is in a known spam list (`.xyz`, `.top`, `.buzz`, etc.)

### 3. Title Relevance Filter

Search result titles are checked for relevance:
- Must contain at least one token from the industry query OR one token from the location
- This is a prefix match on word boundaries, so "SaaS" matches "Top SaaS companies..."

### 4. Bad Title Filter (50+ patterns)

Rejects listicle, tutorial, and non-company results:

**Word patterns:** "how to", "tutorial", "top 10", "best of", "salary", "interview questions", "what is", "benefits of", "vs ", "review", "comparison", "guide", "course", "certification", "free", "download"

**Regex patterns:**
- `\b\d{4}\b` — year in title (listicle indicator)
- `\btop\s+\d+\b` — "top 10", "top 20" lists
- `\b\d+\+?\s+(best|top|leading)` — numbered rankings
- `\breport\b|\bsurvey\b|\bstatistics\b` — research content

### 5. Article URL Filter

URLs are checked for blog/news path patterns:

```regex
/(blog|news|post|article|how-to|careers|jobs|press|magazine|
  podcast|webinar|event|wiki|forum|faq|help|support|docs|
  legal|terms|privacy|sitemap|tag|category|archive)/
```

Any URL matching this pattern is skipped, preventing blog posts and support pages from being treated as company homepages.

## Output

The discovery stage returns a list of `DiscoveredCompany` objects:

```python
@dataclass
class DiscoveredCompany:
    name: str       # from search result title
    website: str    # homepage URL
    domain: str     # registered domain (via tldextract)
```

Duplicate domains are removed before returning. The list is capped at the job's `max_companies` setting.

## Edge Cases & Resilience

- **All search engines down:** returns empty list; pipeline completes with 0 companies
- **Directory pages return only denylist links:** falls through to search engines
- **Rate limiting:** each engine has independent error handling; failure moves to next engine
- **Unicode domains:** tldextract handles IDN domains; denylist checks use normalized forms
- **Empty search results:** logged and skipped; no exception raised

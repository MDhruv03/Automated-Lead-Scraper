"""Discovery service – finds real businesses via directory scraping + search engines.

Architecture:
  1. Search Brave for directory/listing pages about {industry} in {location}
  2. Scrape those listing pages to extract actual company website links
  3. Fall back to direct search engine results with strict filtering
  4. Apply relevance filter: every result must relate to the searched industry
"""

from __future__ import annotations

import logging
import random
import re
import time
from dataclasses import dataclass
from typing import List
from urllib.parse import quote_plus, urlparse, unquote

import requests
from bs4 import BeautifulSoup
import tldextract

from app.config import MAX_COMPANIES_PER_JOB, REQUEST_TIMEOUT, CRAWL_DELAY, INDUSTRY_KEYWORDS

logger = logging.getLogger(__name__)

_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
]


def _get_headers() -> dict:
    return {
        "User-Agent": random.choice(_USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }


# ── Domain blocklist ─────────────────────────────────────────────────────────
# Every domain here is NEVER returned as a discovered company.

_BAD_DOMAINS = {
    # Social / UGC
    "linkedin.com", "facebook.com", "twitter.com", "x.com",
    "instagram.com", "youtube.com", "tiktok.com", "pinterest.com",
    "reddit.com", "quora.com", "threads.net",
    "zhihu.com", "stackexchange.com", "stackoverflow.com",
    # Blogging / content
    "medium.com", "blogspot.com", "wordpress.com", "substack.com",
    "tumblr.com", "wix.com", "weebly.com", "blogger.com",
    # Reference / encyclopedias / dictionaries
    "wikipedia.org", "wikimedia.org", "britannica.com",
    "cambridge.org", "merriam-webster.com", "dictionary.com",
    # E-commerce / marketplaces
    "amazon.com", "amazon.in", "flipkart.com", "ebay.com",
    "alibaba.com", "aliexpress.com", "etsy.com",
    # News / media
    "bbc.com", "bbc.co.uk", "cnn.com", "reuters.com", "bloomberg.com",
    "ndtv.com", "timesofindia.com", "indiatimes.com",
    "theguardian.com", "forbes.com", "huffpost.com",
    "washingtonpost.com", "nytimes.com", "businessinsider.com",
    "cnbc.com", "economictimes.com", "livemint.com",
    "moneycontrol.com", "thehindu.com", "hindustantimes.com",
    # Search engines
    "google.com", "bing.com", "duckduckgo.com", "brave.com", "yahoo.com",
    # Job boards / directories
    "glassdoor.com", "glassdoor.co.in", "indeed.com", "in.indeed.com",
    "naukri.com", "ambitionbox.com", "internshala.com",
    "wellfound.com", "zoominfo.com", "monster.com",
    "justdial.com", "sulekha.com", "tradeindia.com",
    # Government / international orgs
    "who.int", "weforum.org", "worldbank.org", "un.org",
    "nih.gov", "gov.in", "cdc.gov",
    # Listing / aggregator sites (scraped for links, never saved as companies)
    "builtin.com", "builtinchennai.in", "builtinnyc.com",
    "tiimagazine.com", "easyleadz.com", "ssfglobal.in",
    "beststartup.in", "f6s.com", "goodfirms.co", "clutch.co",
    "dnb.com", "crunchbase.com", "owler.com", "tracxn.com",
    "loophealth.com", "18startup.com", "medicalstartups.org",
    "theceo.in", "salezshark.com",
    # SaaS / tools (these are products, not companies in the searched industry)
    "zoho.com", "zohocorp.com", "mailchimp.com", "hubspot.com",
    "salesforce.com", "freshworks.com", "zendesk.com",
    "intercom.com", "slack.com", "notion.so", "canva.com",
    "trello.com", "asana.com", "monday.com", "airtable.com",
    "typeform.com", "surveymonkey.com", "calendly.com",
    "dropbox.com", "box.com", "twilio.com", "stripe.com",
    "shopify.com", "squarespace.com", "godaddy.com",
    "namecheap.com", "cloudflare.com", "digitalocean.com",
    "aws.amazon.com", "azure.microsoft.com", "cloud.google.com",
    # Health content / info sites (NOT healthcare companies)
    "webmd.com", "healthline.com", "mayoclinic.org",
    "medicalnewstoday.com", "everydayhealth.com",
    "verywellhealth.com", "clevelandclinic.org",
    "drugs.com", "rxlist.com",
    # Recipe / lifestyle
    "allrecipes.com", "foodnetwork.com", "epicurious.com",
    "wikihow.com", "lifehacker.com", "buzzfeed.com",
    "taste.com.au", "delish.com",
    # Education
    "coursera.org", "udemy.com", "edx.org", "khanacademy.org",
    # Finance
    "investopedia.com", "nerdwallet.com", "bankrate.com",
}

# Known listing / directory domains — scraped for company links
_DIRECTORY_DOMAINS = {
    "builtin.com", "builtinchennai.in", "builtinnyc.com",
    "tiimagazine.com", "ssfglobal.in", "beststartup.in",
    "f6s.com", "goodfirms.co", "clutch.co", "easyleadz.com",
    "medicalstartups.org", "ambitionbox.com", "wellfound.com",
    "startupindia.gov.in", "tracxn.com", "theceo.in", "salezshark.com",
}

_BAD_TITLE_WORDS = [
    "how to", "guide", "tips", "steps", "recipe", "review",
    "best way", "top 10", "top 5", "top 20", "top 40", "top 50", "what is",
    "tutorial", "explained", "vs ", "versus", "comparison",
    "buy online", "shop now", "download", "subscribe",
    "job vacancies", "jobs in", "salary", "interview questions",
    "companies in", "companies to know", "companies leading",
    "firms in", "startups in",
    # Signup / promotional
    "sign up", "sign in", "log in", "login", "register",
    "create an account", "create account", "free trial",
    # Content / health info articles
    "health benefits", "side effects", "nutrition facts",
    "symptoms of", "causes of", "treatment for",
    "quick & easy", "quick and easy", "easy steps",
    "meaning", "definition", "dictionary",
    # Research / listicle / report
    "rankings", "report", "analysis", "market research", "market size",
    "trends", "statistics", "forecast", "survey", "outlook",
    "industry report", "industry analysis", "market overview",
    "growth rate", "cagr", "market share",
    "price list", "pricing comparison", "salary guide",
]

# Regex patterns for listicle/article titles
_BAD_TITLE_PATTERNS = [
    re.compile(r"^\d+\s+(best|top|leading|largest|biggest|fastest|innovative|emerging)", re.I),
    re.compile(r"^(list|ranking|directory|index)\s+of\b", re.I),
    re.compile(r":\s*(health benefits|nutrition|side effects|symptoms|meaning)", re.I),
    re.compile(r"\b(20[12]\d)\b", re.I),  # years 2010-2029 in titles → usually articles
    re.compile(r"\b(best|top|leading)\s+\d+\b", re.I),  # "best 15", "top 25" etc.
    re.compile(r"\breport\s*[:\-|]", re.I),  # "Report: ...", "Report - ..."
    re.compile(r"\bmarket\s+(research|report|analysis|overview|size|forecast)", re.I),
]


@dataclass
class DiscoveredCompany:
    name: str
    website: str
    domain: str


def _extract_domain(url: str) -> str:
    """Extract and normalize the registered domain to ASCII/punycode."""
    ext = tldextract.extract(url)
    domain = f"{ext.domain}.{ext.suffix}".lower()
    # Normalize to ASCII/punycode
    try:
        domain = domain.encode("idna").decode("ascii")
    except (UnicodeError, UnicodeDecodeError):
        pass
    return domain


def _clean_url(url: str) -> str:
    """Normalize to root registered domain, stripping subdomains and paths."""
    if not url.startswith("http"):
        url = "https://" + url
    ext = tldextract.extract(url)
    root = f"{ext.domain}.{ext.suffix}".lower()
    return f"https://{root}"


_SUSPICIOUS_TOKENS = {"free", "download", "crack", "keygen", "torrent", "proxy", "vpn"}


def _is_bad_domain(domain: str) -> bool:
    """Check if a domain is in the blacklist or looks suspicious."""
    if domain in _BAD_DOMAINS:
        return True
    ext = tldextract.extract(domain)
    base = f"{ext.domain}.{ext.suffix}".lower()
    if base in _BAD_DOMAINS:
        return True
    # Too long
    if len(domain) > 64:
        return True
    # Too many hyphens
    if domain.count("-") > 3:
        return True
    # No TLD
    if "." not in domain:
        return True
    # Suspicious tokens in domain
    if any(tok in ext.domain.lower() for tok in _SUSPICIOUS_TOKENS):
        return True
    return False


def _is_bad_title(title: str) -> bool:
    """Reject titles that indicate blog posts, articles, not real companies."""
    lower = title.lower()
    if any(kw in lower for kw in _BAD_TITLE_WORDS):
        return True
    if any(p.search(title) for p in _BAD_TITLE_PATTERNS):
        return True
    return False


# Article heuristic for URLs
_ARTICLE_URL_RE = re.compile(
    r"/(blog|article|news|post|story|guide|tutorial|how-to|tips|review|recipe"
    r"|top-\d+|best-|\d{4}/\d{2}/|report|analysis|ranking|survey|forecast"
    r"|comparison|vs-|versus|statistics|trends|market-)",
    re.I,
)


def _is_article_url(url: str) -> bool:
    """Reject URLs that look like blog/article/listicle pages."""
    return bool(_ARTICLE_URL_RE.search(url))


def _is_directory_page(url: str) -> bool:
    """Check if a URL belongs to a known directory/listing site."""
    domain = _extract_domain(url)
    return domain in _DIRECTORY_DOMAINS


def _is_relevant_to_query(title: str, industry: str, location: str) -> bool:
    """Check that a search result is actually relevant to the industry/location.

    This is the KEY quality filter. It prevents completely unrelated results
    (Zoho signup, Air Fryer cleaning, Coconut nutrition) from leaking through
    when search engines return garbage.

    Uses prefix matching so "Health" matches "Healthcare", "Tech" matches
    "Technology", etc.
    """
    title_lower = title.lower()
    title_words = set(re.findall(r"[a-z]{3,}", title_lower))

    industry_words = {w.lower() for w in re.findall(r"[a-zA-Z]{3,}", industry)}
    location_words = {w.lower() for w in re.findall(r"[a-zA-Z]{3,}", location)}

    # Check industry: any title word shares a 4+ char prefix with an industry word
    has_industry = False
    for tw in title_words:
        for iw in industry_words:
            # Either word is a prefix of the other (min 4 chars overlap)
            min_len = min(len(tw), len(iw))
            if min_len >= 4 and tw[:min_len] == iw[:min_len]:
                has_industry = True
                break
            # Exact substring match for shorter words
            if len(iw) >= 4 and iw in tw:
                has_industry = True
                break
            if len(tw) >= 4 and tw in iw:
                has_industry = True
                break
        if has_industry:
            break

    has_location = any(w in title_lower for w in location_words)

    return has_industry or has_location


# ── Search engines ───────────────────────────────────────────────────────────

def _search_brave(query: str, max_results: int) -> List[dict]:
    """Scrape Brave Search HTML results with retry on 429."""
    results: list[dict] = []
    encoded = quote_plus(query)
    url = f"https://search.brave.com/search?q={encoded}"

    resp = None
    for attempt in range(3):
        try:
            resp = requests.get(url, headers=_get_headers(), timeout=REQUEST_TIMEOUT)
            if resp.status_code == 429:
                wait = 3 * (attempt + 1)
                logger.info("Brave 429 – retrying in %ds (attempt %d/3)", wait, attempt + 1)
                time.sleep(wait)
                continue
            resp.raise_for_status()
            break
        except requests.RequestException as exc:
            logger.warning("Brave Search request failed: %s", exc)
            return results
    if resp is None or resp.status_code != 200:
        logger.warning("Brave Search exhausted retries for: %s", query)
        return results

    soup = BeautifulSoup(resp.text, "lxml")
    seen_hosts: set[str] = set()

    for snippet in soup.select("#results .snippet"):
        a_tag = snippet.select_one("a[href^='http']")
        if not a_tag:
            continue
        href = a_tag.get("href", "")
        parsed = urlparse(href)
        if not parsed.netloc or "brave" in parsed.netloc:
            continue
        if parsed.netloc in seen_hosts:
            continue
        seen_hosts.add(parsed.netloc)

        title_el = snippet.select_one(".title") or snippet.select_one("span") or a_tag
        title = title_el.get_text(strip=True)[:200] if title_el else parsed.netloc
        results.append({"title": title, "url": href})
        if len(results) >= max_results:
            break

    logger.info("Brave returned %d results for: %s", len(results), query)
    return results


def _search_ddg_api(query: str, max_results: int) -> List[dict]:
    """Use the ddgs (formerly duckduckgo-search) library."""
    DDGS = None
    try:
        from ddgs import DDGS
    except ImportError:
        try:
            from duckduckgo_search import DDGS
        except ImportError:
            logger.warning("Neither ddgs nor duckduckgo_search is installed")
            return []

    results: list[dict] = []
    try:
        with DDGS() as ddgs:
            for r in ddgs.text(query, max_results=max_results):
                url = r.get("href", "")
                title = r.get("title", "")
                if url and title:
                    results.append({"title": title, "url": url})
    except Exception as exc:
        logger.warning("DDG API search failed: %s", exc)
        return []

    logger.info("DDG API returned %d results for: %s", len(results), query)
    return results


def _search_duckduckgo_html(query: str, max_results: int) -> List[dict]:
    """Scrape DuckDuckGo HTML results as last-resort fallback."""
    results: list[dict] = []
    encoded = quote_plus(query)
    url = f"https://html.duckduckgo.com/html/?q={encoded}"

    try:
        resp = requests.get(url, headers=_get_headers(), timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
    except requests.RequestException as exc:
        logger.warning("DuckDuckGo HTML request failed: %s", exc)
        return results

    soup = BeautifulSoup(resp.text, "lxml")
    for result in soup.select(".result__a"):
        href = result.get("href", "")
        title = result.get_text(strip=True)
        if not href or not title:
            continue
        real_url_match = re.search(r"uddg=([^&]+)", href)
        if real_url_match:
            href = unquote(real_url_match.group(1))
        results.append({"title": title, "url": href})
        if len(results) >= max_results:
            break

    logger.info("DuckDuckGo HTML returned %d results for: %s", len(results), query)
    return results


def _search_google_scrape(query: str, max_results: int) -> List[dict]:
    """Scrape Google search results as a fallback."""
    results: list[dict] = []
    encoded = quote_plus(query)
    url = f"https://www.google.com/search?q={encoded}&num={max_results}"

    try:
        resp = requests.get(url, headers=_get_headers(), timeout=REQUEST_TIMEOUT)
        if resp.status_code != 200:
            logger.warning("Google scrape returned %d", resp.status_code)
            return results
    except requests.RequestException as exc:
        logger.warning("Google scrape failed: %s", exc)
        return results

    soup = BeautifulSoup(resp.text, "lxml")
    seen_hosts: set[str] = set()

    for a_tag in soup.select("a[href^='http']"):
        href = a_tag.get("href", "")
        parsed = urlparse(href)
        if not parsed.netloc:
            continue
        if any(g in parsed.netloc for g in ("google.", "googleapis.", "gstatic.", "youtube.")):
            continue
        if parsed.netloc in seen_hosts:
            continue
        seen_hosts.add(parsed.netloc)

        title = a_tag.get_text(strip=True)[:200]
        if not title or len(title) < 3:
            title = parsed.netloc
        results.append({"title": title, "url": href})
        if len(results) >= max_results:
            break

    logger.info("Google scrape returned %d results for: %s", len(results), query)
    return results


_ENGINES = [
    ("Brave", _search_brave),
    ("DDG API", _search_ddg_api),
    ("DDG HTML", _search_duckduckgo_html),
    ("Google", _search_google_scrape),
]


def _search_with_fallback(query: str, max_results: int) -> List[dict]:
    """Try each search engine in order until one returns results."""
    for name, engine_fn in _ENGINES:
        try:
            results = engine_fn(query, max_results)
            if results:
                logger.info("Engine '%s' succeeded with %d results", name, len(results))
                return results
        except Exception as exc:
            logger.warning("Engine '%s' error: %s", name, exc)
        time.sleep(CRAWL_DELAY)
    logger.warning("All search engines returned 0 results for: %s", query)
    return []


# ── Directory page scraping ──────────────────────────────────────────────────

def _scrape_companies_from_listing(listing_url: str) -> List[dict]:
    """Scrape a directory/listing page and extract individual company links."""
    companies: list[dict] = []
    try:
        resp = requests.get(listing_url, headers=_get_headers(), timeout=REQUEST_TIMEOUT)
        if resp.status_code != 200:
            return companies
    except requests.RequestException:
        return companies

    soup = BeautifulSoup(resp.text, "lxml")
    listing_domain = _extract_domain(listing_url)
    seen_domains: set[str] = set()

    for a_tag in soup.select("a[href^='http']"):
        href = a_tag.get("href", "").split("?")[0].split("#")[0]
        if not href:
            continue
        domain = _extract_domain(href)
        if not domain or "." not in domain:
            continue
        if domain == listing_domain or domain in seen_domains:
            continue
        if _is_bad_domain(domain):
            continue

        title = a_tag.get_text(strip=True)[:200]
        if not title or len(title) < 2:
            continue
        if _is_bad_title(title):
            continue

        seen_domains.add(domain)
        companies.append({"title": title, "url": href})

    logger.info("Scraped %d companies from listing: %s", len(companies), listing_url)
    return companies


# ── Main discovery function ──────────────────────────────────────────────────

def discover_companies(
    industry: str,
    location: str,
    max_results: int | None = None,
) -> List[DiscoveredCompany]:
    """Return a list of discovered companies for the given industry & location.

    Strategy:
      1. Search for companies — get a mix of direct results and directory pages
      2. For any directory/listing pages found, scrape them for individual company links
      3. Apply relevance + domain + title filters, then deduplicate
    """
    max_results = min(max_results or MAX_COMPANIES_PER_JOB, MAX_COMPANIES_PER_JOB)

    queries = [
        f"{industry} companies in {location}",
        f"list of {industry} companies {location}",
        f"best {industry} companies near {location}",
        f"top {industry} firms {location}",
    ]

    seen_domains: set[str] = set()
    companies: list[DiscoveredCompany] = []
    directory_urls: list[str] = []

    # Phase 1: Search engine results — collect direct companies + directory URLs
    for qi, q in enumerate(queries):
        if len(companies) >= max_results:
            break
        if qi > 0:
            time.sleep(3)  # extra delay between query variations to avoid 429
        raw_results = _search_with_fallback(q, max_results * 2)
        time.sleep(CRAWL_DELAY)

        for item in raw_results:
            if len(companies) >= max_results:
                break
            try:
                domain = _extract_domain(item["url"])
            except Exception:
                continue

            # Directory pages → queue for phase 2
            if _is_directory_page(item["url"]):
                if item["url"] not in directory_urls:
                    directory_urls.append(item["url"])
                continue

            if domain in seen_domains or _is_bad_domain(domain):
                continue
            if _is_bad_title(item.get("title", "")):
                continue
            # KEY FILTER: result must relate to the searched industry or location
            if not _is_relevant_to_query(item.get("title", ""), industry, location):
                logger.debug("SKIP (irrelevant) %s: %s", domain, item.get("title", "")[:80])
                continue

            seen_domains.add(domain)
            companies.append(
                DiscoveredCompany(
                    name=item["title"][:300],
                    website=_clean_url(item["url"]),
                    domain=domain,
                )
            )

    # Phase 2: Scrape directory pages for real company links
    # (Directory-scraped results skip relevance check — the directory page itself
    #  was already relevant, and individual company names won't contain industry keywords)
    for dir_url in directory_urls[:5]:
        if len(companies) >= max_results:
            break
        time.sleep(CRAWL_DELAY)
        scraped = _scrape_companies_from_listing(dir_url)

        for item in scraped:
            if len(companies) >= max_results:
                break
            try:
                domain = _extract_domain(item["url"])
            except Exception:
                continue
            if domain in seen_domains or _is_bad_domain(domain):
                continue

            seen_domains.add(domain)
            companies.append(
                DiscoveredCompany(
                    name=item["title"][:300],
                    website=_clean_url(item["url"]),
                    domain=domain,
                )
            )

    logger.info(
        "Discovered %d companies for '%s in %s' (scraped %d directory pages)",
        len(companies), industry, location, len(directory_urls),
    )
    return companies

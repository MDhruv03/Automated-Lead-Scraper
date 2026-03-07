"""Discovery service – finds real businesses via directory scraping + search engines.

Architecture:
  1. Search Brave for directory/listing pages about {industry} in {location}
  2. Scrape those listing pages to extract actual company website links
  3. Fall back to direct search engine results with strict filtering
  4. Validate every result: domain quality, title sanity, business signals
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

from app.config import MAX_COMPANIES_PER_JOB, REQUEST_TIMEOUT, CRAWL_DELAY

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


# ── Domain & title quality filters ──────────────────────────────────────────

_BAD_DOMAINS = {
    # Social / UGC platforms
    "linkedin.com", "facebook.com", "twitter.com", "x.com",
    "instagram.com", "youtube.com", "tiktok.com", "pinterest.com",
    "reddit.com", "quora.com", "threads.net",
    "zhihu.com", "stackexchange.com", "stackoverflow.com",
    # Blogging / content platforms
    "medium.com", "blogspot.com", "wordpress.com", "substack.com",
    "tumblr.com", "wix.com", "weebly.com",
    # Reference / encyclopedias
    "wikipedia.org", "wikimedia.org", "britannica.com",
    "cambridge.org", "merriam-webster.com",
    # E-commerce / marketplaces
    "amazon.com", "amazon.in", "flipkart.com", "ebay.com", "alibaba.com",
    # News / media
    "bbc.com", "cnn.com", "reuters.com", "bloomberg.com",
    "ndtv.com", "timesofindia.com", "indiatimes.com",
    "theguardian.com", "forbes.com", "huffpost.com",
    # Search engines
    "google.com", "bing.com", "duckduckgo.com", "brave.com", "yahoo.com",
    # Job boards / directories (used for directory scraping, not as company results)
    "glassdoor.com", "glassdoor.co.in", "indeed.com", "in.indeed.com",
    "naukri.com", "ambitionbox.com", "internshala.com",
    "wellfound.com", "zoominfo.com",
    "justdial.com", "sulekha.com", "tradeindia.com",
    # Government / international orgs
    "who.int", "weforum.org", "worldbank.org", "un.org",
    # Listing / aggregator sites (we scrape these to EXTRACT companies, not to save them)
    "builtin.com", "builtinchennai.in", "builtinnyc.com",
    "tiimagazine.com", "easyleadz.com", "ssfglobal.in",
    "beststartup.in", "f6s.com", "goodfirms.co", "clutch.co",
    "dnb.com", "crunchbase.com", "owler.com", "tracxn.com",
    "loophealth.com", "18startup.com", "medicalstartups.org",
    "theceo.in", "salezshark.com",
}

# Known listing / directory domains — pages from these are scraped for company links
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
]

# Regex patterns for listicle/article titles like "10 Leading..." or "20 Best..."
_BAD_TITLE_PATTERNS = [
    re.compile(r"^\d+\s+(best|top|leading|largest|biggest|fastest|innovative|emerging)", re.I),
    re.compile(r"^(list|ranking|directory|index)\s+of\b", re.I),
]


@dataclass
class DiscoveredCompany:
    name: str
    website: str
    domain: str


def _extract_domain(url: str) -> str:
    ext = tldextract.extract(url)
    return f"{ext.domain}.{ext.suffix}".lower()


def _clean_url(url: str) -> str:
    """Ensure scheme is present and strip tracking params."""
    if not url.startswith("http"):
        url = "https://" + url
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}"


def _is_bad_domain(domain: str) -> bool:
    """Check if a domain is in the blacklist or looks suspicious."""
    if domain in _BAD_DOMAINS:
        return True
    # Very long domain = suspicious
    if len(domain) > 50:
        return True
    # Excessive hyphens = SEO spam
    if domain.count("-") > 3:
        return True
    # No TLD = broken
    if "." not in domain:
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


def _is_directory_page(url: str) -> bool:
    """Check if a URL belongs to a known directory/listing site."""
    domain = _extract_domain(url)
    return domain in _DIRECTORY_DOMAINS


# ── Search engines ───────────────────────────────────────────────────────────

def _search_brave(query: str, max_results: int) -> List[dict]:
    """Scrape Brave Search HTML results."""
    results: list[dict] = []
    encoded = quote_plus(query)
    url = f"https://search.brave.com/search?q={encoded}"

    try:
        resp = requests.get(url, headers=_get_headers(), timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
    except requests.RequestException as exc:
        logger.warning("Brave Search request failed: %s", exc)
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
    """Use the duckduckgo-search library."""
    try:
        from duckduckgo_search import DDGS
    except ImportError:
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


def _search_bing_rss(query: str, max_results: int) -> List[dict]:
    """Fetch Bing search results via its RSS feed."""
    results: list[dict] = []
    encoded = quote_plus(query)
    url = f"https://www.bing.com/search?format=rss&q={encoded}&count={min(max_results, 50)}&setlang=en"

    try:
        resp = requests.get(url, headers=_get_headers(), timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
    except requests.RequestException as exc:
        logger.warning("Bing RSS request failed: %s", exc)
        return results

    soup = BeautifulSoup(resp.text, "xml")
    for item in soup.find_all("item"):
        title_tag = item.find("title")
        link_tag = item.find("link")
        if not title_tag or not link_tag:
            continue
        title = title_tag.get_text(strip=True)
        link = link_tag.get_text(strip=True)
        if title and link and link.startswith("http"):
            results.append({"title": title, "url": link})
            if len(results) >= max_results:
                break

    logger.info("Bing RSS returned %d results for: %s", len(results), query)
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


_ENGINES = [
    ("Brave", _search_brave),
    ("DDG API", _search_ddg_api),
    ("Bing RSS", _search_bing_rss),
    ("DDG HTML", _search_duckduckgo_html),
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
        # Skip same-site links and bad domains
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
      3. Combine all results, filter, deduplicate
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
    directory_urls: list[str] = []  # listing pages to scrape later

    # Phase 1: Search engine results — collect direct companies + directory URLs
    for q in queries:
        if len(companies) >= max_results:
            break
        raw_results = _search_with_fallback(q, max_results * 2)
        time.sleep(CRAWL_DELAY)

        for item in raw_results:
            if len(companies) >= max_results:
                break
            try:
                domain = _extract_domain(item["url"])
            except Exception:
                continue

            # If this is a directory page, save it for phase 2
            if _is_directory_page(item["url"]):
                if item["url"] not in directory_urls:
                    directory_urls.append(item["url"])
                continue

            if domain in seen_domains or _is_bad_domain(domain):
                continue
            if _is_bad_title(item.get("title", "")):
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
    for dir_url in directory_urls[:5]:  # cap to avoid too many requests
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

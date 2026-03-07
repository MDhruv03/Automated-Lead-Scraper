"""Discovery service – finds businesses via multiple search engines with fallback."""

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


# ── Engine 1: Brave Search HTML (best quality results) ───────────────────────

def _search_brave(query: str, max_results: int) -> List[dict]:
    """Scrape Brave Search HTML results (high quality, no API key needed)."""
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
        # Deduplicate by host within this result set
        if parsed.netloc in seen_hosts:
            continue
        seen_hosts.add(parsed.netloc)

        # Extract clean title from the snippet heading
        title_el = snippet.select_one(".title") or snippet.select_one("span") or a_tag
        title = title_el.get_text(strip=True)[:200] if title_el else parsed.netloc
        results.append({"title": title, "url": href})
        if len(results) >= max_results:
            break

    logger.info("Brave Search returned %d results for: %s", len(results), query)
    return results


# ── Engine 2: duckduckgo-search library (DDG internal JSON API) ──────────────

def _search_ddg_api(query: str, max_results: int) -> List[dict]:
    """Use the duckduckgo-search library (most reliable from cloud servers)."""
    try:
        from duckduckgo_search import DDGS
    except ImportError:
        logger.warning("duckduckgo-search package not installed")
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


# ── Engine 3: Bing RSS feed (no JS rendering needed) ─────────────────────────

def _search_bing_rss(query: str, max_results: int) -> List[dict]:
    """Fetch Bing search results via the RSS feed endpoint."""
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


# ── Engine 4: DuckDuckGo HTML scraping (works on non-blocked IPs) ────────────

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


# ── Fallback orchestrator ────────────────────────────────────────────────────

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


def discover_companies(
    industry: str,
    location: str,
    max_results: int | None = None,
) -> List[DiscoveredCompany]:
    """Return a list of discovered companies for the given industry & location."""
    max_results = min(max_results or MAX_COMPANIES_PER_JOB, MAX_COMPANIES_PER_JOB)

    queries = [
        f"{industry} companies in {location}",
        f"list of {industry} companies {location}",
        f"best {industry} companies near {location}",
        f"top {industry} firms {location}",
    ]

    seen_domains: set[str] = set()
    companies: list[DiscoveredCompany] = []

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

            # Skip social / directory domains
            if domain in seen_domains:
                continue
            skip_domains = {
                "linkedin.com", "facebook.com", "twitter.com", "x.com",
                "instagram.com", "youtube.com", "wikipedia.org",
                "yelp.com", "crunchbase.com", "glassdoor.com",
                "glassdoor.co.in", "indeed.com", "in.indeed.com",
                "zoominfo.com", "bloomberg.com", "quora.com",
                "duckduckgo.com", "google.com", "bing.com",
                "who.int", "weforum.org",
                "ambitionbox.com", "naukri.com", "justdial.com",
                "internshala.com", "wellfound.com",
            }
            if domain in skip_domains:
                continue

            seen_domains.add(domain)
            companies.append(
                DiscoveredCompany(
                    name=item["title"][:300],
                    website=_clean_url(item["url"]),
                    domain=domain,
                )
            )

    logger.info("Discovered %d companies for '%s in %s'", len(companies), industry, location)
    return companies

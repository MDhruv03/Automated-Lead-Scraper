"""Discovery service – finds businesses via DuckDuckGo HTML search."""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from typing import List
from urllib.parse import quote_plus, urlparse

import requests
from bs4 import BeautifulSoup
import tldextract

from app.config import MAX_COMPANIES_PER_JOB, REQUEST_TIMEOUT, CRAWL_DELAY

logger = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
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


def _search_duckduckgo(query: str, max_results: int) -> List[dict]:
    """Scrape DuckDuckGo HTML results (no API key needed)."""
    results: list[dict] = []
    encoded = quote_plus(query)
    url = f"https://html.duckduckgo.com/html/?q={encoded}"

    try:
        resp = requests.get(url, headers=_HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
    except requests.RequestException as exc:
        logger.warning("DuckDuckGo request failed: %s", exc)
        return results

    soup = BeautifulSoup(resp.text, "lxml")

    for result in soup.select(".result__a"):
        href = result.get("href", "")
        title = result.get_text(strip=True)
        if not href or not title:
            continue

        # DuckDuckGo wraps links via redirect – try to extract real URL
        real_url_match = re.search(r"uddg=([^&]+)", href)
        if real_url_match:
            from urllib.parse import unquote
            href = unquote(real_url_match.group(1))

        results.append({"title": title, "url": href})
        if len(results) >= max_results:
            break

    return results


def discover_companies(
    industry: str,
    location: str,
    max_results: int | None = None,
) -> List[DiscoveredCompany]:
    """Return a list of discovered companies for the given industry & location."""
    max_results = min(max_results or MAX_COMPANIES_PER_JOB, MAX_COMPANIES_PER_JOB)

    queries = [
        f"{industry} companies in {location}",
        f"{industry} {location} site:.com",
        f"top {industry} firms {location}",
    ]

    seen_domains: set[str] = set()
    companies: list[DiscoveredCompany] = []

    for q in queries:
        if len(companies) >= max_results:
            break
        raw_results = _search_duckduckgo(q, max_results * 2)
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
                "indeed.com", "zoominfo.com", "bloomberg.com",
                "duckduckgo.com", "google.com",
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

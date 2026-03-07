"""Crawler service – fetches key pages from a company website.

- Checks robots.txt before crawling
- Crawls only homepage + fixed business pages (/, /contact, /about, /team, /company)
- Realistic headers (User-Agent + Accept-Language)
- Configurable delay, timeout, retries with exponential backoff
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import List
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import requests

from app.config import MAX_PAGES_PER_SITE, REQUEST_TIMEOUT, CRAWL_DELAY, MAX_RETRIES

logger = logging.getLogger(__name__)

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

_HEADERS = {
    "User-Agent": _USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

# Fixed business pages to try (in priority order)
_BUSINESS_PATHS = ["/contact", "/about", "/team", "/company", "/about-us", "/contact-us"]


@dataclass
class CrawledPage:
    url: str
    html: str
    status_code: int


def _check_robots(base_url: str) -> RobotFileParser | None:
    """Fetch and parse robots.txt. Returns parser or None on failure."""
    parsed = urlparse(base_url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    rp = RobotFileParser()
    try:
        resp = requests.get(robots_url, headers=_HEADERS, timeout=5)
        if resp.status_code == 200:
            rp.parse(resp.text.splitlines())
            return rp
    except Exception:
        pass
    return None


def _can_fetch(robots: RobotFileParser | None, url: str) -> bool:
    """Check if we're allowed to crawl this URL per robots.txt."""
    if robots is None:
        return True
    return robots.can_fetch(_USER_AGENT, url)


def _fetch(url: str) -> CrawledPage | None:
    """Fetch a URL with retries and exponential backoff."""
    for attempt in range(1, MAX_RETRIES + 2):
        try:
            resp = requests.get(
                url, headers=_HEADERS, timeout=REQUEST_TIMEOUT, allow_redirects=True,
            )
            if resp.status_code < 400:
                return CrawledPage(url=resp.url, html=resp.text, status_code=resp.status_code)
            if resp.status_code in (429, 503) and attempt <= MAX_RETRIES:
                wait = CRAWL_DELAY * (2 ** (attempt - 1))
                logger.debug("HTTP %d for %s, retrying in %.1fs", resp.status_code, url, wait)
                time.sleep(wait)
                continue
            return None
        except requests.RequestException as exc:
            if attempt <= MAX_RETRIES:
                wait = CRAWL_DELAY * (2 ** (attempt - 1))
                logger.debug("Fetch error %s for %s, retrying in %.1fs", exc, url, wait)
                time.sleep(wait)
            else:
                logger.debug("Failed to fetch %s after %d attempts: %s", url, attempt, exc)
    return None


def crawl_website(website: str) -> List[CrawledPage]:
    """Crawl the homepage + fixed business sub-pages.

    Returns up to MAX_PAGES_PER_SITE pages. Respects robots.txt.
    """
    pages: list[CrawledPage] = []
    visited: set[str] = set()

    robots = _check_robots(website)

    if not _can_fetch(robots, website):
        logger.warning("robots.txt disallows crawling %s", website)
        return pages

    home = _fetch(website)
    if not home:
        return pages
    pages.append(home)
    visited.add(home.url)

    for path in _BUSINESS_PATHS:
        if len(pages) >= MAX_PAGES_PER_SITE:
            break
        candidate = urljoin(website, path)
        if candidate in visited:
            continue
        if not _can_fetch(robots, candidate):
            logger.debug("robots.txt disallows %s", candidate)
            continue
        visited.add(candidate)
        time.sleep(CRAWL_DELAY)
        page = _fetch(candidate)
        if page and page.status_code < 400:
            pages.append(page)

    logger.info("Crawled %d pages from %s", len(pages), website)
    return pages

"""Crawler service – fetches key pages from a company website."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import List
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from app.config import MAX_PAGES_PER_SITE, REQUEST_TIMEOUT, CRAWL_DELAY

logger = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
}

# Pages most likely to contain contact info
_PRIORITY_PATHS = ["/contact", "/about", "/team", "/about-us", "/contact-us"]


@dataclass
class CrawledPage:
    url: str
    html: str
    status_code: int


def _is_same_domain(base: str, url: str) -> bool:
    return urlparse(base).netloc == urlparse(url).netloc


def _find_contact_links(soup: BeautifulSoup, base_url: str) -> List[str]:
    """Discover internal links that likely point to contact/about pages."""
    keywords = {"contact", "about", "team", "people", "staff", "leadership"}
    links: list[str] = []
    for a in soup.find_all("a", href=True):
        href = a["href"].lower()
        text = a.get_text(strip=True).lower()
        if any(kw in href or kw in text for kw in keywords):
            full = urljoin(base_url, a["href"])
            if _is_same_domain(base_url, full) and full not in links:
                links.append(full)
    return links


def _fetch(url: str) -> CrawledPage | None:
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=REQUEST_TIMEOUT, allow_redirects=True)
        return CrawledPage(url=resp.url, html=resp.text, status_code=resp.status_code)
    except requests.RequestException as exc:
        logger.debug("Failed to fetch %s: %s", url, exc)
        return None


def crawl_website(website: str) -> List[CrawledPage]:
    """Crawl the homepage + priority sub-pages. Returns up to MAX_PAGES_PER_SITE pages."""
    pages: list[CrawledPage] = []
    visited: set[str] = set()

    # 1) Homepage
    home = _fetch(website)
    if not home or home.status_code >= 400:
        return pages
    pages.append(home)
    visited.add(home.url)

    # 2) Discover useful internal links
    soup = BeautifulSoup(home.html, "lxml")
    discovered = _find_contact_links(soup, website)

    # 3) Priority static paths
    for path in _PRIORITY_PATHS:
        candidate = urljoin(website, path)
        if candidate not in discovered:
            discovered.insert(0, candidate)

    # 4) Fetch sub-pages up to limit
    for link in discovered:
        if len(pages) >= MAX_PAGES_PER_SITE:
            break
        if link in visited:
            continue
        visited.add(link)
        time.sleep(CRAWL_DELAY)
        page = _fetch(link)
        if page and page.status_code < 400:
            pages.append(page)

    logger.info("Crawled %d pages from %s", len(pages), website)
    return pages

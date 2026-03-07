"""Business validation service – determines if a crawled website is a real business."""

from __future__ import annotations

import logging
import re

from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# Words/phrases that strongly indicate a real business website
_BUSINESS_SIGNALS = [
    "about us", "about the company", "our company", "who we are",
    "our services", "services", "our products", "products",
    "contact us", "get in touch", "reach us",
    "our team", "leadership", "management team", "founders",
    "careers", "work with us", "join us", "open positions",
    "clients", "our clients", "testimonials", "case studies",
    "partners", "our partners",
    "copyright ©", "all rights reserved",
    "privacy policy", "terms of service", "terms and conditions",
    "headquarters", "head office", "our offices",
]

# Words indicating the page is NOT a business (blog post, article, etc.)
_NON_BUSINESS_SIGNALS = [
    "subscribe to newsletter", "read more articles", "related posts",
    "posted by", "written by", "published on",
    "comments section", "leave a comment", "share this article",
    "next article", "previous article",
    "how to", "step by step", "tutorial",
    "advertisement", "sponsored content",
]


def validate_business(html: str) -> tuple[bool, float, list[str]]:
    """Check if the HTML content belongs to a real business website.

    Returns:
        (is_business, confidence, signals_found)
        - is_business: True if enough business signals found
        - confidence: 0.0 to 1.0
        - signals_found: list of matched business signals
    """
    if not html:
        return False, 0.0, []

    soup = BeautifulSoup(html, "lxml")
    text = soup.get_text(separator=" ", strip=True).lower()
    # Also check link text and nav items
    links_text = " ".join(a.get_text(strip=True).lower() for a in soup.find_all("a"))
    combined = text + " " + links_text

    signals_found: list[str] = []
    for signal in _BUSINESS_SIGNALS:
        if signal in combined:
            signals_found.append(signal)

    anti_signals: list[str] = []
    for signal in _NON_BUSINESS_SIGNALS:
        if signal in combined:
            anti_signals.append(signal)

    # Score: each business signal = +1, each anti-signal = -0.5
    score = len(signals_found) - 0.5 * len(anti_signals)
    max_possible = len(_BUSINESS_SIGNALS)
    confidence = max(0.0, min(1.0, score / max(max_possible * 0.3, 1)))

    # Need at least 3 business signals to consider it a real business
    is_business = len(signals_found) >= 3 and confidence > 0.2

    if not is_business:
        logger.debug(
            "Business validation failed: %d signals, %.2f confidence, anti=%d",
            len(signals_found), confidence, len(anti_signals),
        )

    return is_business, confidence, signals_found

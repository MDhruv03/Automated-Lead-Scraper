"""Business & location validation service."""

from __future__ import annotations

import logging
import re

from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# ── Location aliases for commonly-searched cities ─────────────────────────────
_CITY_ALIASES: dict[str, list[str]] = {
    "bangalore": ["bangalore", "bengaluru", "karnataka"],
    "mumbai": ["mumbai", "bombay", "maharashtra"],
    "delhi": ["delhi", "new delhi", "gurgaon", "gurugram", "noida", "ncr"],
    "chennai": ["chennai", "madras", "tamil nadu"],
    "hyderabad": ["hyderabad", "telangana", "secunderabad"],
    "pune": ["pune", "maharashtra"],
    "kolkata": ["kolkata", "calcutta", "west bengal"],
    "ahmedabad": ["ahmedabad", "gujarat"],
    "jaipur": ["jaipur", "rajasthan"],
    "kochi": ["kochi", "cochin", "kerala"],
    "new york": ["new york", "nyc", "manhattan", "brooklyn", "queens"],
    "san francisco": ["san francisco", "bay area"],
    "los angeles": ["los angeles", "la"],
    "chicago": ["chicago", "illinois"],
    "london": ["london", "uk", "united kingdom"],
    "singapore": ["singapore"],
    "dubai": ["dubai", "uae", "emirates"],
    "toronto": ["toronto", "ontario"],
    "sydney": ["sydney", "nsw"],
    "berlin": ["berlin", "germany"],
    "tokyo": ["tokyo", "japan"],
}

_COUNTRY_KEYWORDS: dict[str, list[str]] = {
    "india": ["india", ".in"],
    "usa": ["united states", "usa"],
    "uk": ["united kingdom", "uk"],
    "canada": ["canada"],
    "australia": ["australia"],
    "germany": ["germany"],
    "singapore": ["singapore"],
    "uae": ["united arab emirates", "uae"],
}


def get_location_terms(location: str) -> list[str]:
    """Generate all text-match terms for a given job location."""
    terms: set[str] = set()
    loc_lower = location.lower().strip()

    # Full location string
    terms.add(loc_lower)

    # Individual words (min 3 chars)
    for word in re.split(r"[,\s]+", loc_lower):
        if len(word) >= 3:
            terms.add(word)

    # City alias expansion
    for key, aliases in _CITY_ALIASES.items():
        if key in loc_lower or loc_lower in key:
            terms.update(aliases)

    # Country keyword expansion
    for key, aliases in _COUNTRY_KEYWORDS.items():
        if key in loc_lower:
            terms.update(aliases)

    return [t for t in terms if len(t) >= 2]


def check_location_relevance(text: str, location_terms: list[str]) -> bool:
    """Return True if any location term appears in the text."""
    if not location_terms:
        return True
    text_lower = text.lower()
    return any(term in text_lower for term in location_terms)


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


# ── Negative-industry filter ──────────────────────────────────────────────────
# These indicate the site is an agency / service-provider / product page rather
# than an actual company in the searched industry.

_AGENCY_KEYWORDS = [
    "seo agency", "seo services", "seo company",
    "digital marketing agency", "digital marketing services", "digital marketing company",
    "marketing agency", "marketing services", "marketing company",
    "advertising agency", "ad agency", "media agency",
    "recruiting agency", "recruitment agency", "staffing agency",
    "staffing company", "recruitment firm", "recruiting firm",
    "consulting firm", "consulting agency", "management consulting",
    "lead generation services", "lead generation company",
    "content marketing services", "social media marketing",
    "ppc management", "ppc agency", "link building",
    "web design agency", "web development agency",
    "branding agency", "creative agency", "pr agency",
    "public relations firm",
]

_INSURANCE_KEYWORDS = [
    "health insurance plans", "insurance premium", "buy insurance",
    "insurance quote", "compare plans", "insurance policy",
    "insurance coverage", "term insurance", "life insurance",
    "claim settlement", "premium calculator",
]


def check_negative_industry(text: str, query_industry: str) -> tuple[bool, str]:
    """Check if the crawled text contains strong signals that the site is an
    agency, recruiter, or insurance-product page rather than a company in the
    searched industry.

    Returns:
        (should_reject, reason)  – True means the site should be discarded.
    """
    text_lower = text.lower()
    query_lower = query_industry.lower()

    # Don't apply agency filter if the user explicitly searches for marketing/seo etc.
    skip_agency = any(k in query_lower for k in (
        "marketing", "seo", "advertising", "recruiting", "staffing", "consulting",
        "lead generation", "web design", "branding", "pr ", "public relations",
    ))

    if not skip_agency:
        for kw in _AGENCY_KEYWORDS:
            if kw in text_lower:
                return True, f"agency keyword: {kw}"

    # Insurance-product filter (skip if user searches for insurance)
    if "insurance" not in query_lower:
        for kw in _INSURANCE_KEYWORDS:
            if kw in text_lower:
                return True, f"insurance product: {kw}"

    return False, ""


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

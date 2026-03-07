"""General text-processing helpers shared across services."""

import re
from typing import List
from html import unescape


def clean_html_text(html: str) -> str:
    """Strip tags and collapse whitespace – quick and dependency-free."""
    text = re.sub(r"<script[\s\S]*?</script>", " ", html, flags=re.I)
    text = re.sub(r"<style[\s\S]*?</style>", " ", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def extract_social_links(html: str) -> dict:
    """Return dict of social-media profile URLs found in raw HTML."""
    patterns = {
        "linkedin": re.compile(r'https?://(?:www\.)?linkedin\.com/(?:company|in)/[A-Za-z0-9_\-/]+', re.I),
        "twitter": re.compile(r'https?://(?:www\.)?(?:twitter|x)\.com/[A-Za-z0-9_]+', re.I),
        "facebook": re.compile(r'https?://(?:www\.)?facebook\.com/[A-Za-z0-9._\-]+', re.I),
    }
    result: dict[str, str | None] = {}
    for key, pat in patterns.items():
        m = pat.search(html)
        result[key] = m.group(0) if m else None
    return result


def truncate(text: str, max_length: int = 500) -> str:
    """Return *text* capped at *max_length* characters with an ellipsis."""
    if len(text) <= max_length:
        return text
    return text[: max_length - 1] + "…"


def extract_keywords(text: str, top_n: int = 8) -> List[str]:
    """Cheap keyword extraction: most frequent capitalised words."""
    words = re.findall(r"\b[A-Z][a-z]{2,}\b", text)
    freq: dict[str, int] = {}
    for w in words:
        freq[w.lower()] = freq.get(w.lower(), 0) + 1
    ranked = sorted(freq, key=freq.get, reverse=True)  # type: ignore[arg-type]
    return ranked[:top_n]

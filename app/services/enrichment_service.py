"""Enrichment service – NLP-based industry detection, description and keyword extraction.

Uses spaCy's small English model when available; falls back to regex-based heuristics
so the app still works on constrained environments where the model isn't installed.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import List

logger = logging.getLogger(__name__)

# ── Lazy-load spaCy ──────────────────────────────────────────────────────────
_nlp = None


def _get_nlp():
    global _nlp
    if _nlp is not None:
        return _nlp
    try:
        import spacy
        _nlp = spacy.load("en_core_web_sm")
        logger.info("spaCy model loaded successfully")
    except Exception:
        logger.warning("spaCy model not available – using regex fallback")
        _nlp = False  # sentinel: tried and failed
    return _nlp


# Broad industry keyword map
_INDUSTRY_KEYWORDS: dict[str, list[str]] = {
    "Technology": ["software", "saas", "cloud", "tech", "digital", "app", "platform", "api", "devops"],
    "Fintech": ["fintech", "payment", "banking", "finance", "insurance", "lending", "neobank"],
    "Healthcare": ["health", "medical", "pharma", "biotech", "clinical", "hospital", "wellness"],
    "E-commerce": ["ecommerce", "e-commerce", "retail", "shop", "marketplace", "store"],
    "Education": ["education", "edtech", "learning", "university", "school", "training", "course"],
    "Marketing": ["marketing", "advertising", "seo", "content", "brand", "media", "creative"],
    "Real Estate": ["real estate", "property", "housing", "construction", "architect"],
    "Consulting": ["consulting", "advisory", "strategy", "management consulting"],
    "AI / ML": ["artificial intelligence", "machine learning", "ai", "ml", "deep learning", "nlp", "data science"],
    "Logistics": ["logistics", "supply chain", "shipping", "freight", "warehouse", "delivery"],
}


@dataclass
class EnrichmentResult:
    industry: str | None = None
    description: str | None = None
    keywords: List[str] = field(default_factory=list)


def _detect_industry(text: str) -> str | None:
    lower = text.lower()
    scores: dict[str, int] = {}
    for industry, kws in _INDUSTRY_KEYWORDS.items():
        score = sum(1 for kw in kws if kw in lower)
        if score:
            scores[industry] = score
    if scores:
        return max(scores, key=scores.get)  # type: ignore[arg-type]
    return None


def _extract_description_spacy(doc) -> str:
    """Build a one-liner description from the first meaningful sentences."""
    sents = [s.text.strip() for s in doc.sents if len(s.text.strip()) > 30]
    return " ".join(sents[:2])[:500] if sents else ""


def _extract_keywords_spacy(doc) -> List[str]:
    seen: set[str] = set()
    keywords: list[str] = []
    for ent in doc.ents:
        if ent.label_ in ("ORG", "PRODUCT", "GPE", "NORP", "WORK_OF_ART"):
            key = ent.text.strip().lower()
            if key not in seen and len(key) > 2:
                seen.add(key)
                keywords.append(ent.text.strip())
    # Supplement with noun chunks
    for chunk in doc.noun_chunks:
        key = chunk.text.strip().lower()
        if key not in seen and len(key) > 3:
            seen.add(key)
            keywords.append(chunk.text.strip())
        if len(keywords) >= 10:
            break
    return keywords[:10]


def _fallback_keywords(text: str) -> List[str]:
    words = re.findall(r"\b[A-Z][a-z]{2,}\b", text)
    freq: dict[str, int] = {}
    for w in words:
        freq[w] = freq.get(w, 0) + 1
    ranked = sorted(freq, key=freq.get, reverse=True)  # type: ignore[arg-type]
    return ranked[:8]


def enrich(text: str) -> EnrichmentResult:
    """Enrich raw page text with industry detection, description and keywords."""
    if not text or len(text.strip()) < 20:
        return EnrichmentResult()

    industry = _detect_industry(text)

    nlp = _get_nlp()
    if nlp and nlp is not False:
        doc = nlp(text[:5000])  # limit token count
        description = _extract_description_spacy(doc)
        keywords = _extract_keywords_spacy(doc)
    else:
        # regex fallback
        sentences = re.split(r"[.!?]+", text)
        meaningful = [s.strip() for s in sentences if len(s.strip()) > 30]
        description = ". ".join(meaningful[:2])[:500]
        keywords = _fallback_keywords(text)

    return EnrichmentResult(
        industry=industry,
        description=description or None,
        keywords=keywords,
    )

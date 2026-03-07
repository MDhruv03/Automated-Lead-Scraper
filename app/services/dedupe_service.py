"""Deduplication service – prevents duplicate companies and leads."""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import List

from sqlalchemy.orm import Session

from app.models.company import Company
from app.models.lead import Lead


def _normalise_name(name: str) -> str:
    """Lower-case, strip punctuation, collapse whitespace."""
    name = re.sub(r"[^\w\s]", "", name.lower())
    return re.sub(r"\s+", " ", name).strip()


def _names_similar(a: str, b: str, threshold: float = 0.85) -> bool:
    return SequenceMatcher(None, _normalise_name(a), _normalise_name(b)).ratio() >= threshold


def is_duplicate_company(db: Session, domain: str, name: str) -> bool:
    """Check whether a company with the same domain or a very similar name exists."""
    if db.query(Company).filter(Company.domain == domain).first():
        return True
    # Fuzzy name check against recent companies
    recent = db.query(Company).order_by(Company.id.desc()).limit(200).all()
    for c in recent:
        if _names_similar(c.name, name):
            return True
    return False


def is_duplicate_lead(db: Session, company_id: int, email: str | None) -> bool:
    """Check if this exact email already exists for the company."""
    if not email:
        return False
    return (
        db.query(Lead)
        .filter(Lead.company_id == company_id, Lead.email == email)
        .first()
        is not None
    )


def deduplicate_emails(emails: List[str]) -> List[str]:
    """Return emails with duplicates removed (case-insensitive)."""
    seen: set[str] = set()
    unique: list[str] = []
    for e in emails:
        key = e.lower()
        if key not in seen:
            seen.add(key)
            unique.append(e)
    return unique

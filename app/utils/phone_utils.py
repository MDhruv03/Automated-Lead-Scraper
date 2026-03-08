"""Utilities for extracting and normalising phone numbers."""

import re
from typing import List

# Liberal international phone regex
_PHONE_RE = re.compile(r"(\+?\d[\d\-\s\(\)]{7,}\d)")

_MIN_DIGITS = 7
_MAX_DIGITS = 15

# Patterns that look like phone numbers but aren't
_YEAR_RE = re.compile(r"^[\s\-]*(\d{4})[\s\-]+(\d{4})[\s\-]*$")
_ALL_YEARS_RE = re.compile(
    r"^[\s\(\)\-]*(?:19|20)\d{2}[\s\(\)\-]+(?:19|20)\d{2}[\s\(\)\-]*$"
)
_YEAR_RANGE_RE = re.compile(
    r"^[\s\-]*(?:19|20)\d{2}[\s\-]*$"
)


def _digit_count(s: str) -> int:
    return sum(c.isdigit() for c in s)


def _normalise(phone: str) -> str:
    """Strip excess whitespace and dashes, keep a clean representation."""
    return re.sub(r"[\s\-\.]+", " ", phone).strip()


def _looks_like_years(raw: str) -> bool:
    """Return True if the candidate is just year numbers (e.g. '2020 2021')."""
    stripped = raw.strip()
    if _ALL_YEARS_RE.match(stripped):
        return True
    # Check if it's purely N-digit groups that are all plausible years
    parts = re.findall(r"\d+", stripped)
    if parts and all(
        len(p) == 4 and 1900 <= int(p) <= 2099 for p in parts
    ):
        return True
    return False


def extract_phones(text: str) -> List[str]:
    """Return a deduplicated list of plausible phone numbers found in *text*."""
    results: list[str] = []
    seen: set[str] = set()

    for match in _PHONE_RE.findall(text):
        digits = _digit_count(match)
        if digits < _MIN_DIGITS or digits > _MAX_DIGITS:
            continue
        if _looks_like_years(match):
            continue
        normalised = _normalise(match)
        digit_key = re.sub(r"\D", "", normalised)
        if digit_key not in seen:
            seen.add(digit_key)
            results.append(normalised)

    return results

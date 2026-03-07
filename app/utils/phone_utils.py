"""Utilities for extracting and normalising phone numbers."""

import re
from typing import List

# Liberal international phone regex
_PHONE_RE = re.compile(r"(\+?\d[\d\-\s\(\)]{7,}\d)")

_MIN_DIGITS = 7
_MAX_DIGITS = 15


def _digit_count(s: str) -> int:
    return sum(c.isdigit() for c in s)


def _normalise(phone: str) -> str:
    """Strip excess whitespace and dashes, keep a clean representation."""
    return re.sub(r"[\s\-\.]+", " ", phone).strip()


def extract_phones(text: str) -> List[str]:
    """Return a deduplicated list of plausible phone numbers found in *text*."""
    results: list[str] = []
    seen: set[str] = set()

    for match in _PHONE_RE.findall(text):
        digits = _digit_count(match)
        if digits < _MIN_DIGITS or digits > _MAX_DIGITS:
            continue
        normalised = _normalise(match)
        digit_key = re.sub(r"\D", "", normalised)
        if digit_key not in seen:
            seen.add(digit_key)
            results.append(normalised)

    return results

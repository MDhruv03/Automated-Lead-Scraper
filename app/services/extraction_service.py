"""Extraction service – pulls emails, phones, addresses and social links from HTML."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List

from bs4 import BeautifulSoup

from app.utils.email_utils import extract_emails
from app.utils.phone_utils import extract_phones
from app.utils.text_utils import clean_html_text, extract_social_links


@dataclass
class ExtractedContacts:
    emails: List[str] = field(default_factory=list)
    phones: List[str] = field(default_factory=list)
    addresses: List[str] = field(default_factory=list)
    linkedin: str | None = None
    source_url: str = ""


# Rough pattern for street addresses (US / India style)
_ADDRESS_RE = re.compile(
    r"\d{1,5}\s[\w\s,.#\-]{5,80}(?:street|st|avenue|ave|road|rd|blvd|lane|ln|drive|dr|floor|suite|nagar|colony|sector)",
    re.IGNORECASE,
)


def extract_contacts_from_html(html: str, source_url: str = "") -> ExtractedContacts:
    """Extract all contact artefacts from a single HTML page."""
    text = clean_html_text(html)
    social = extract_social_links(html)

    addresses: list[str] = []
    for m in _ADDRESS_RE.findall(text):
        normalised = re.sub(r"\s+", " ", m).strip()
        if normalised not in addresses:
            addresses.append(normalised)

    return ExtractedContacts(
        emails=extract_emails(text),
        phones=extract_phones(text),
        addresses=addresses[:5],
        linkedin=social.get("linkedin"),
        source_url=source_url,
    )


def merge_contacts(contacts_list: List[ExtractedContacts]) -> ExtractedContacts:
    """Merge contacts extracted from multiple pages into one consolidated record."""
    emails: list[str] = []
    phones: list[str] = []
    addresses: list[str] = []
    linkedin: str | None = None
    source_url = ""

    seen_emails: set[str] = set()
    seen_phones: set[str] = set()

    for c in contacts_list:
        for e in c.emails:
            if e not in seen_emails:
                seen_emails.add(e)
                emails.append(e)
        for p in c.phones:
            digit_key = re.sub(r"\D", "", p)
            if digit_key not in seen_phones:
                seen_phones.add(digit_key)
                phones.append(p)
        for a in c.addresses:
            if a not in addresses:
                addresses.append(a)
        if c.linkedin and not linkedin:
            linkedin = c.linkedin
        if c.source_url and not source_url:
            source_url = c.source_url

    return ExtractedContacts(
        emails=emails,
        phones=phones,
        addresses=addresses[:5],
        linkedin=linkedin,
        source_url=source_url,
    )

"""Lead scoring service – assigns a 0-100 quality score with detailed breakdown."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, asdict

import dns.resolver

logger = logging.getLogger(__name__)


@dataclass
class ScoreBreakdown:
    email_valid: int = 0
    phone_found: int = 0
    linkedin_found: int = 0
    contact_page: int = 0
    description_found: int = 0
    active_website: int = 0
    tech_detected: int = 0
    personal_email: int = 0
    total: int = 0

    def to_json(self) -> str:
        """Serialise to JSON for DB storage."""
        return json.dumps(asdict(self))

    @property
    def factors(self) -> list[dict]:
        """Return list of {label, points, earned} for UI display."""
        defs = [
            ("Verified Email", 25, self.email_valid),
            ("Phone Number", 15, self.phone_found),
            ("LinkedIn Profile", 10, self.linkedin_found),
            ("Contact Page", 5, self.contact_page),
            ("Company Bio", 5, self.description_found),
            ("Active Website", 15, self.active_website),
            ("Tech Stack Detected", 10, self.tech_detected),
            ("Personal Email", 15, self.personal_email),
        ]
        return [{"label": l, "max": m, "earned": e} for l, m, e in defs]


def _check_mx(domain: str) -> bool:
    """Return True if the domain has at least one MX record."""
    try:
        answers = dns.resolver.resolve(domain, "MX", lifetime=5)
        return len(answers) > 0
    except Exception:
        return False


def validate_email(email: str) -> bool:
    """Validate an email: syntax + MX record lookup."""
    if not email or "@" not in email:
        return False
    domain = email.rsplit("@", 1)[1]
    return _check_mx(domain)


def score_lead(
    *,
    email: str | None = None,
    email_valid: bool = False,
    phone: str | None = None,
    linkedin: str | None = None,
    has_contact_page: bool = False,
    description: str | None = None,
    website_active: bool = False,
    tech_detected: bool = False,
    is_personal_email: bool = False,
) -> ScoreBreakdown:
    """Calculate a composite lead quality score (0-100) with detailed breakdown."""
    breakdown = ScoreBreakdown()

    if email and email_valid:
        breakdown.email_valid = 25
    if phone:
        breakdown.phone_found = 15
    if linkedin:
        breakdown.linkedin_found = 10
    if has_contact_page:
        breakdown.contact_page = 5
    if description:
        breakdown.description_found = 5
    if website_active:
        breakdown.active_website = 15
    if tech_detected:
        breakdown.tech_detected = 10
    if is_personal_email:
        breakdown.personal_email = 15

    breakdown.total = (
        breakdown.email_valid
        + breakdown.phone_found
        + breakdown.linkedin_found
        + breakdown.contact_page
        + breakdown.description_found
        + breakdown.active_website
        + breakdown.tech_detected
        + breakdown.personal_email
    )
    return breakdown

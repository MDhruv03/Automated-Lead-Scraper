"""Lead scoring service – assigns a 0-100 quality score with detailed breakdown.

Points allocation (max 100):
  - Valid MX email:      15
  - Phone present:       10
  - Contact page found:  15
  - Industry relevance:  15
  - Location verified:   15
  - Site reachable:      10
  - Multiple contacts:   10  (has both email AND phone)
  - Domain legitimacy:   10  (clean TLD, no suspicious patterns)
  - High-risk domain:   -15
"""

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
    contact_page: int = 0
    industry_keyword: int = 0
    location_match: int = 0
    active_website: int = 0
    multiple_contacts: int = 0
    domain_legitimacy: int = 0
    high_risk_penalty: int = 0
    total: int = 0

    def to_json(self) -> str:
        """Serialise to JSON for DB storage."""
        return json.dumps(asdict(self))

    @property
    def factors(self) -> list[dict]:
        """Return list of {label, points, earned} for UI display."""
        defs = [
            ("Verified MX Email", 15, self.email_valid),
            ("Phone Number", 10, self.phone_found),
            ("Contact Page Found", 15, self.contact_page),
            ("Industry Relevance", 15, self.industry_keyword),
            ("Location Verified", 15, self.location_match),
            ("Site Reachable", 10, self.active_website),
            ("Multiple Contacts", 10, self.multiple_contacts),
            ("Domain Legitimacy", 10, self.domain_legitimacy),
            ("High-Risk Domain", 0, self.high_risk_penalty),
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
    has_contact_page: bool = False,
    has_industry_keyword: bool = False,
    has_location_match: bool = False,
    website_active: bool = False,
    is_high_risk_domain: bool = False,
    is_legitimate_domain: bool = True,
) -> ScoreBreakdown:
    """Calculate a composite lead quality score (0-100) with detailed breakdown."""
    breakdown = ScoreBreakdown()

    if email and email_valid:
        breakdown.email_valid = 15
    if phone:
        breakdown.phone_found = 10
    if has_contact_page:
        breakdown.contact_page = 15
    if has_industry_keyword:
        breakdown.industry_keyword = 15
    if has_location_match:
        breakdown.location_match = 15
    if website_active:
        breakdown.active_website = 10
    # Bonus: both email and phone present
    if email and phone:
        breakdown.multiple_contacts = 10
    if is_legitimate_domain:
        breakdown.domain_legitimacy = 10
    if is_high_risk_domain:
        breakdown.high_risk_penalty = -15

    breakdown.total = max(0, (
        breakdown.email_valid
        + breakdown.phone_found
        + breakdown.contact_page
        + breakdown.industry_keyword
        + breakdown.location_match
        + breakdown.active_website
        + breakdown.multiple_contacts
        + breakdown.domain_legitimacy
        + breakdown.high_risk_penalty
    ))
    return breakdown

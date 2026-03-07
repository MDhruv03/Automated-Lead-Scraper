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
    contact_page: int = 0
    industry_keyword: int = 0
    active_website: int = 0
    high_risk_penalty: int = 0
    total: int = 0

    def to_json(self) -> str:
        """Serialise to JSON for DB storage."""
        return json.dumps(asdict(self))

    @property
    def factors(self) -> list[dict]:
        """Return list of {label, points, earned} for UI display."""
        defs = [
            ("Verified MX Email", 30, self.email_valid),
            ("Phone Number", 20, self.phone_found),
            ("Contact Page Found", 10, self.contact_page),
            ("Industry Keyword", 10, self.industry_keyword),
            ("Site Reachable", 20, self.active_website),
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
    website_active: bool = False,
    is_high_risk_domain: bool = False,
) -> ScoreBreakdown:
    """Calculate a composite lead quality score (0-100) with detailed breakdown.

    Points allocation:
      - Valid MX email: +30
      - Phone present: +20
      - Contact page found: +10
      - Industry keyword present: +10
      - Site reachable/fast: +20
      - High-risk domain: -10
    """
    breakdown = ScoreBreakdown()

    if email and email_valid:
        breakdown.email_valid = 30
    if phone:
        breakdown.phone_found = 20
    if has_contact_page:
        breakdown.contact_page = 10
    if has_industry_keyword:
        breakdown.industry_keyword = 10
    if website_active:
        breakdown.active_website = 20
    if is_high_risk_domain:
        breakdown.high_risk_penalty = -10

    breakdown.total = max(0, (
        breakdown.email_valid
        + breakdown.phone_found
        + breakdown.contact_page
        + breakdown.industry_keyword
        + breakdown.active_website
        + breakdown.high_risk_penalty
    ))
    return breakdown

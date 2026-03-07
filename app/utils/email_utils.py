"""Utilities for extracting, validating and classifying email addresses."""

import re
from typing import List

# RFC-5322-ish pattern, intentionally permissive for web scraping
_EMAIL_RE = re.compile(
    r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}",
)

# Obfuscated variants: name [at] domain [dot] com
_OBFUSCATED_RE = re.compile(
    r"[A-Za-z0-9._%+\-]+\s*\[?\s*(?:at|AT)\s*\]?\s*[A-Za-z0-9.\-]+\s*\[?\s*(?:dot|DOT)\s*\]?\s*[A-Za-z]{2,}",
)

# Common non-person / generic addresses to skip
_BLACKLIST_PREFIXES = {
    "noreply", "no-reply", "mailer-daemon", "postmaster", "webmaster",
    "abuse", "root", "admin", "hostmaster", "example", "test",
    "sampleemail", "email@example",
}

_BLACKLIST_DOMAINS = {
    "example.com", "example.org", "test.com", "sentry.io",
    "wixpress.com", "googleapis.com",
}

# ── Email role classification ────────────────────────────────────────────────
_ROLE_MAP: dict[str, list[str]] = {
    "Executive":  ["ceo", "cto", "cfo", "coo", "cmo", "founder", "cofounder", "co-founder", "president", "director", "vp", "chief"],
    "Sales":      ["sales", "business", "biz", "partnerships", "deals", "revenue"],
    "Marketing":  ["marketing", "growth", "seo", "content", "pr", "press", "media", "brand"],
    "Support":    ["support", "help", "helpdesk", "service", "care", "customer"],
    "HR":         ["hr", "hiring", "recruit", "talent", "people", "careers", "jobs"],
    "Technical":  ["dev", "developer", "engineering", "tech", "it", "sysadmin", "devops", "security"],
    "Finance":    ["finance", "billing", "accounts", "payable", "invoice", "accounting"],
    "Legal":      ["legal", "compliance", "privacy", "gdpr"],
    "General":    ["info", "hello", "contact", "office", "team", "general", "enquiry", "inquiry"],
}


def classify_email_role(email: str) -> str:
    """Classify an email into a department/role category."""
    local = email.split("@")[0].lower().replace(".", " ").replace("_", " ").replace("-", " ")
    for role, keywords in _ROLE_MAP.items():
        for kw in keywords:
            if kw in local:
                return role
    # If it looks like a person's name (first.last), it's likely a direct contact
    if re.match(r"^[a-z]+[._][a-z]+$", email.split("@")[0].lower()):
        return "Personal"
    return "Unknown"


def _deobfuscate(text: str) -> str:
    """Replace [at] / [dot] tokens with their real equivalents."""
    text = re.sub(r"\s*\[?\s*(?:at|AT)\s*\]?\s*", "@", text, count=1)
    text = re.sub(r"\s*\[?\s*(?:dot|DOT)\s*\]?\s*", ".", text)
    return text


def extract_emails(text: str) -> List[str]:
    """Return a deduplicated list of plausible email addresses found in *text*."""
    found: set[str] = set()

    for match in _EMAIL_RE.findall(text):
        found.add(match.lower())

    for match in _OBFUSCATED_RE.findall(text):
        deobfuscated = _deobfuscate(match).lower()
        if _EMAIL_RE.fullmatch(deobfuscated):
            found.add(deobfuscated)

    # Filter junk
    cleaned: list[str] = []
    for email in found:
        local = email.split("@")[0]
        domain = email.split("@")[1]
        if local in _BLACKLIST_PREFIXES:
            continue
        if domain in _BLACKLIST_DOMAINS:
            continue
        # skip image/asset filenames that look like emails
        if domain.endswith((".png", ".jpg", ".gif", ".svg", ".css", ".js")):
            continue
        cleaned.append(email)

    return sorted(set(cleaned))

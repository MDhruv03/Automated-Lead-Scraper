"""Technology stack detection – identifies frameworks, CMS, analytics, etc. from HTML."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List

# Each signature: (display name, category, detection patterns in HTML)
_SIGNATURES: list[tuple[str, str, list[str]]] = [
    # ── CMS / Platforms ───────────────────────────────────────────────────
    ("WordPress",    "CMS",        ["wp-content", "wp-includes", "wordpress"]),
    ("Shopify",      "E-commerce", ["cdn.shopify.com", "shopify.com"]),
    ("Wix",          "CMS",        ["wix.com", "wixsite.com", "parastorage.com"]),
    ("Squarespace",  "CMS",        ["squarespace.com", "sqsp.com"]),
    ("Webflow",      "CMS",        ["webflow.com", "assets-global.website-files.com"]),
    ("Drupal",       "CMS",        ["drupal.org", "/sites/default/files"]),
    ("Joomla",       "CMS",        ["/media/jui/", "joomla"]),
    ("Ghost",        "CMS",        ["ghost.io", "ghost.org"]),
    ("HubSpot CMS",  "CMS",        ["hs-scripts.com", "hubspot.com"]),
    # ── JS Frameworks ─────────────────────────────────────────────────────
    ("React",        "Framework",  ["react.production.min", "reactDOM", "_reactRootContainer", "__next"]),
    ("Next.js",      "Framework",  ["_next/static", "__NEXT_DATA__"]),
    ("Vue.js",       "Framework",  ["vue.min.js", "vue.global", "__vue__"]),
    ("Nuxt",         "Framework",  ["_nuxt/", "__nuxt"]),
    ("Angular",      "Framework",  ["ng-version", "angular.min.js", "ng-app"]),
    ("Svelte",       "Framework",  ["svelte", "__svelte"]),
    ("jQuery",       "Library",    ["jquery.min.js", "jquery-"]),
    ("Bootstrap",    "Library",    ["bootstrap.min.css", "bootstrap.min.js"]),
    ("Tailwind",     "Library",    ["tailwindcss", "tailwind.min"]),
    # ── Analytics / Marketing ─────────────────────────────────────────────
    ("Google Analytics", "Analytics", ["google-analytics.com", "gtag/js", "ga.js"]),
    ("Google Tag Manager", "Analytics", ["googletagmanager.com"]),
    ("Hotjar",       "Analytics",  ["hotjar.com", "static.hotjar.com"]),
    ("Mixpanel",     "Analytics",  ["mixpanel.com"]),
    ("Segment",      "Analytics",  ["cdn.segment.com"]),
    ("Facebook Pixel", "Analytics", ["connect.facebook.net", "fbevents.js"]),
    ("Heap",         "Analytics",  ["heap-analytics", "heapanalytics.com"]),
    ("Amplitude",    "Analytics",  ["amplitude.com/libs"]),
    # ── Infrastructure / CDN ──────────────────────────────────────────────
    ("Cloudflare",   "CDN",        ["cdnjs.cloudflare.com", "cf-ray", "__cf_bm"]),
    ("AWS",          "Hosting",    [".amazonaws.com", "aws-sdk"]),
    ("Vercel",       "Hosting",    ["vercel.app", "vercel-insights"]),
    ("Netlify",      "Hosting",    ["netlify.app", "netlify-cms"]),
    ("Heroku",       "Hosting",    ["herokuapp.com"]),
    # ── Chat / Support ────────────────────────────────────────────────────
    ("Intercom",     "Support",    ["intercom.io", "widget.intercom.io"]),
    ("Zendesk",      "Support",    ["zendesk.com", "zdassets.com"]),
    ("Drift",        "Support",    ["drift.com", "js.driftt.com"]),
    ("Crisp",        "Support",    ["crisp.chat"]),
    # ── Payments ──────────────────────────────────────────────────────────
    ("Stripe",       "Payments",   ["js.stripe.com", "stripe.com"]),
    ("PayPal",       "Payments",   ["paypal.com/sdk", "paypalobjects.com"]),
    ("Razorpay",     "Payments",   ["razorpay.com"]),
]


@dataclass(frozen=True)
class TechSignal:
    name: str
    category: str


def detect_technologies(html: str) -> List[TechSignal]:
    """Scan HTML for known technology fingerprints."""
    html_lower = html.lower()
    seen: set[str] = set()
    results: list[TechSignal] = []

    for name, category, patterns in _SIGNATURES:
        if name in seen:
            continue
        for pattern in patterns:
            if pattern.lower() in html_lower:
                seen.add(name)
                results.append(TechSignal(name=name, category=category))
                break

    return results


def detect_from_headers(headers: dict[str, str]) -> List[TechSignal]:
    """Detect technologies from HTTP response headers."""
    results: list[TechSignal] = []
    server = headers.get("server", "").lower()
    powered = headers.get("x-powered-by", "").lower()

    if "nginx" in server:
        results.append(TechSignal(name="Nginx", category="Server"))
    elif "apache" in server:
        results.append(TechSignal(name="Apache", category="Server"))
    elif "cloudflare" in server:
        results.append(TechSignal(name="Cloudflare", category="CDN"))

    if "php" in powered:
        results.append(TechSignal(name="PHP", category="Language"))
    if "express" in powered:
        results.append(TechSignal(name="Express.js", category="Framework"))
    if "asp.net" in powered:
        results.append(TechSignal(name="ASP.NET", category="Framework"))

    return results


def extract_meta_info(html: str) -> dict:
    """Pull OG tags, meta description and other SEO meta from raw HTML."""
    result: dict[str, str | None] = {
        "meta_description": None,
        "og_title": None,
        "og_description": None,
        "og_image": None,
    }

    patterns = {
        "meta_description": re.compile(
            r'<meta\s+[^>]*name=["\']description["\']\s+content=["\']([^"\']+)["\']',
            re.I,
        ),
        "og_title": re.compile(
            r'<meta\s+[^>]*property=["\']og:title["\']\s+content=["\']([^"\']+)["\']',
            re.I,
        ),
        "og_description": re.compile(
            r'<meta\s+[^>]*property=["\']og:description["\']\s+content=["\']([^"\']+)["\']',
            re.I,
        ),
        "og_image": re.compile(
            r'<meta\s+[^>]*property=["\']og:image["\']\s+content=["\']([^"\']+)["\']',
            re.I,
        ),
    }

    for key, pat in patterns.items():
        m = pat.search(html)
        if m:
            result[key] = m.group(1).strip()

    return result


def estimate_company_size(text: str) -> str | None:
    """Rough heuristic to estimate company size from page text."""
    lower = text.lower()

    size_patterns = [
        (r"\b(\d{1,3}),?(\d{3})\+?\s*employees", lambda m: int(m.group(1) + m.group(2))),
        (r"\b(\d+)\+?\s*employees", lambda m: int(m.group(1))),
        (r"\b(\d+)\+?\s*team\s*members", lambda m: int(m.group(1))),
        (r"team\s*of\s*(\d+)", lambda m: int(m.group(1))),
    ]

    for pattern, extractor in size_patterns:
        m = re.search(pattern, lower)
        if m:
            count = extractor(m)
            if count <= 10:
                return "1-10"
            elif count <= 50:
                return "11-50"
            elif count <= 200:
                return "51-200"
            elif count <= 1000:
                return "201-1K"
            elif count <= 10000:
                return "1K-10K"
            else:
                return "10K+"

    # Keyword heuristics
    if any(kw in lower for kw in ["enterprise", "fortune 500", "global offices"]):
        return "1K+"
    if any(kw in lower for kw in ["startup", "small team", "founded 202"]):
        return "1-50"

    return None

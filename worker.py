"""LeadPulse Local Worker – polls the deployed server for pending jobs,
runs the discovery/crawling/extraction pipeline locally, and sends results
back via API.

Usage:
    python worker.py                          # uses default server URL
    python worker.py --server https://your-app.onrender.com
    python worker.py --secret YOUR_WORKER_SECRET

Environment variables (override CLI flags):
    LEADPULSE_SERVER   – base URL of the deployed LeadPulse API
    WORKER_SECRET      – shared auth token
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import sys
import threading
import time
from datetime import datetime, timezone

import requests as http_client

# Load .env file so LEADPULSE_SERVER / WORKER_SECRET are picked up automatically
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv not installed – rely on real env vars or CLI flags

# ── Ensure project root is on sys.path so service imports work ────────────────
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.config import (
    MIN_LEAD_SCORE,
    INDUSTRY_KEYWORDS,
    WORKER_SECRET as _DEFAULT_SECRET,
)
from app.services.discovery_service import discover_companies, _is_article_url, _is_bad_domain
from app.services.crawler_service import crawl_website
from app.services.extraction_service import extract_contacts_from_html, merge_contacts
from app.services.enrichment_service import enrich
from app.services.scoring_service import score_lead, validate_email
from app.services.dedupe_service import deduplicate_emails
from app.services.techdetect_service import detect_technologies, detect_from_headers, extract_meta_info, estimate_company_size
from app.services.validation_service import validate_business, get_location_terms, check_location_relevance, check_negative_industry
from app.utils.email_utils import classify_email_role
from app.utils.text_utils import clean_html_text

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
)
logger = logging.getLogger("worker")

# ── Graceful shutdown ─────────────────────────────────────────────────────────
_shutdown = threading.Event()


def _handle_signal(sig, _frame):
    logger.info("Received %s – shutting down gracefully …", signal.Signals(sig).name)
    _shutdown.set()


signal.signal(signal.SIGINT, _handle_signal)
signal.signal(signal.SIGTERM, _handle_signal)


# ── Helpers: talk to the server ───────────────────────────────────────────────

class ServerClient:
    """Thin wrapper around the deployed LeadPulse worker API.

    Accepts one or more server base URLs. Every request is tried against each
    URL in order; the first successful one wins.  This lets you specify both
    the ``*.onrender.com`` URL and a custom domain so the worker keeps working
    even if one endpoint is temporarily unreachable.
    """

    def __init__(self, base_urls: list[str], secret: str, timeout: int = 30):
        self.bases = [u.rstrip("/") for u in base_urls]
        self.headers = {"Authorization": f"Bearer {secret}"}
        self.timeout = timeout

    def _request(self, method: str, path: str, **kwargs):
        """Try the request against each base URL; return the first success."""
        kwargs.setdefault("headers", self.headers)
        kwargs.setdefault("timeout", self.timeout)
        last_exc: Exception | None = None
        for base in self.bases:
            url = f"{base}{path}"
            try:
                resp = getattr(http_client, method)(url, **kwargs)
                if resp.status_code < 500:
                    return resp
            except Exception as exc:
                last_exc = exc
                logger.debug("Request to %s failed: %s", url, exc)
        # All bases failed
        if last_exc:
            raise last_exc
        return None

    # -- heartbeat --
    def heartbeat(self) -> bool:
        try:
            r = self._request("post", "/api/worker/heartbeat")
            return r is not None and r.status_code == 200
        except Exception:
            return False

    # -- pending jobs --
    def get_pending_jobs(self) -> list[dict]:
        try:
            r = self._request("get", "/api/worker/jobs")
            if r and r.status_code == 200:
                return r.json()
        except Exception as exc:
            logger.warning("Failed to fetch pending jobs: %s", exc)
        return []

    # -- claim --
    def claim(self, job_id: int) -> bool:
        try:
            r = self._request("post", f"/api/worker/claim/{job_id}")
            return r is not None and r.status_code == 200
        except Exception:
            return False

    # -- progress --
    def progress(self, job_id: int, stage: str, total: int, processed: int):
        try:
            self._request(
                "post",
                f"/api/worker/job/{job_id}/progress",
                json={"current_stage": stage, "total_companies": total, "processed_companies": processed},
            )
        except Exception:
            pass  # best-effort

    # -- results --
    def submit_results(self, job_id: int, companies: list[dict], duration: float) -> bool:
        try:
            r = self._request(
                "post",
                f"/api/worker/job/{job_id}/results",
                json={"companies": companies, "duration_seconds": round(duration, 1)},
                timeout=60,
            )
            return r is not None and r.status_code == 200
        except Exception as exc:
            logger.error("Failed to submit results for job %d: %s", job_id, exc)
            return False

    # -- fail --
    def fail(self, job_id: int):
        try:
            self._request("post", f"/api/worker/job/{job_id}/fail")
        except Exception:
            pass


# ── Pipeline (runs locally, collects results in memory) ──────────────────────

def _get_industry_keywords(query: str) -> list[str]:
    q = query.lower()
    for industry, kws in INDUSTRY_KEYWORDS.items():
        if industry in q or any(kw in q for kw in kws[:3]):
            return kws
    return []


def _has_industry_relevance(text: str, keywords: list[str]) -> bool:
    if not keywords:
        return True
    text_lower = text.lower()
    return any(kw in text_lower for kw in keywords)


def run_local_pipeline(
    client: ServerClient,
    job_id: int,
    query: str,
    location: str,
) -> None:
    """Execute the full discovery pipeline locally and push results to server."""
    start = time.monotonic()

    try:
        # ── Step 1: Discover ──────────────────────────────────────────────
        client.progress(job_id, "discovering", 0, 0)
        discovered = discover_companies(query, location)
        total = len(discovered)
        logger.info("Discovered %d companies for '%s' in '%s'", total, query, location)
        client.progress(job_id, "crawling", total, 0)

        industry_kws = _get_industry_keywords(query)
        location_terms = get_location_terms(location)
        results: list[dict] = []
        saved = 0
        seen_domains: set[str] = set()

        for idx, disc in enumerate(discovered, 1):
            if _shutdown.is_set():
                logger.info("Shutdown requested – stopping pipeline early")
                break

            try:
                # ── Domain-level dedup (in-job) ───────────────────────────
                if disc.domain in seen_domains:
                    client.progress(job_id, "crawling", total, idx)
                    continue
                seen_domains.add(disc.domain)

                if _is_bad_domain(disc.domain):
                    client.progress(job_id, "crawling", total, idx)
                    continue

                # ── Crawl ─────────────────────────────────────────────────
                client.progress(job_id, "crawling", total, idx)
                pages = crawl_website(disc.website)
                website_active = len(pages) > 0
                has_contact_page = any(
                    kw in p.url.lower() for p in pages for kw in ("contact", "about", "team")
                )
                pages = [p for p in pages if not _is_article_url(p.url)]

                if not pages:
                    continue

                all_html = " ".join(p.html for p in pages)
                full_text = " ".join(clean_html_text(p.html) for p in pages)

                # ── Quality Gate 1: Business validation ───────────────────
                is_biz, confidence, signals = validate_business(all_html)
                if not is_biz:
                    continue

                # ── Quality Gate 2: Location relevance ────────────────────
                location_match = check_location_relevance(full_text, location_terms)
                if not location_match:
                    continue

                # ── Quality Gate 3: Industry relevance ────────────────────
                industry_kw_present = _has_industry_relevance(full_text, industry_kws)
                if not industry_kw_present and industry_kws:
                    continue

                # ── Quality Gate 3b: Negative industry filter ─────────────
                neg_reject, neg_reason = check_negative_industry(full_text, query)
                if neg_reject:
                    logger.info("SKIP (negative industry: %s) %s", neg_reason, disc.domain)
                    continue

                # ── Extract contacts ──────────────────────────────────────
                client.progress(job_id, "extracting", total, idx)
                page_contacts = [extract_contacts_from_html(p.html, source_url=p.url) for p in pages]
                merged = merge_contacts(page_contacts)
                merged.emails = deduplicate_emails(merged.emails)

                has_email = bool(merged.emails)
                has_phone = bool(merged.phones)
                if not has_email and not has_phone:
                    continue

                # ── Tech detection ────────────────────────────────────────
                techs: list[str] = []
                meta_desc = ""
                logo = ""
                emp_est = ""
                if pages:
                    tech_signals = detect_technologies(pages[0].html)
                    header_signals = detect_from_headers({})
                    all_signals = {s.name: s for s in tech_signals + header_signals}
                    techs = [s.name for s in all_signals.values()]
                    meta = extract_meta_info(pages[0].html)
                    meta_desc = meta.get("description", "")
                    logo = meta.get("og_image", "")
                emp_est = estimate_company_size(full_text[:5000])

                is_high_risk = disc.domain.count("-") >= 3
                is_legit_domain = not is_high_risk and len(disc.domain) < 50

                # ── Enrich ────────────────────────────────────────────────
                client.progress(job_id, "enriching", total, idx)
                enrichment = enrich(full_text[:8000])
                keywords = (
                    enrichment.keywords
                    if hasattr(enrichment, "keywords") and enrichment.keywords
                    else []
                )

                # ── Score – ONE lead per company ──────────────────────────
                client.progress(job_id, "scoring", total, idx)

                best_email = None
                best_email_valid = False
                best_role = None
                best_score = -1
                best_breakdown = None
                extra_emails: list[str] = []

                if merged.emails:
                    for email in merged.emails[:10]:
                        is_valid = validate_email(email)
                        role = classify_email_role(email)
                        bd = score_lead(
                            email=email,
                            email_valid=is_valid,
                            phone=merged.phones[0] if merged.phones else None,
                            has_contact_page=has_contact_page,
                            has_industry_keyword=industry_kw_present,
                            has_location_match=location_match,
                            website_active=website_active,
                            is_high_risk_domain=is_high_risk,
                            is_legitimate_domain=is_legit_domain,
                        )
                        if bd.total > best_score:
                            if best_email:
                                extra_emails.append(best_email)
                            best_email = email
                            best_email_valid = is_valid
                            best_role = role
                            best_score = bd.total
                            best_breakdown = bd
                        else:
                            extra_emails.append(email)

                if best_email is None and merged.phones:
                    best_breakdown = score_lead(
                        phone=merged.phones[0],
                        has_contact_page=has_contact_page,
                        has_industry_keyword=industry_kw_present,
                        has_location_match=location_match,
                        website_active=website_active,
                        is_high_risk_domain=is_high_risk,
                        is_legitimate_domain=is_legit_domain,
                    )
                    best_score = best_breakdown.total

                if best_score < MIN_LEAD_SCORE:
                    continue

                # ── Collect single lead for this company ──────────────────
                lead_dict = {
                    "email": best_email,
                    "phone": merged.phones[0] if merged.phones else None,
                    "address": merged.addresses[0] if merged.addresses else None,
                    "linkedin": merged.linkedin,
                    "lead_score": best_score,
                    "email_valid": best_email_valid,
                    "source_url": merged.source_url,
                    "role": best_role,
                    "score_breakdown": best_breakdown.to_json(),
                    "extra_emails": json.dumps(extra_emails) if extra_emails else None,
                }

                results.append({
                    "name": disc.name,
                    "website": disc.website,
                    "domain": disc.domain,
                    "industry": enrichment.industry or query,
                    "city": location,
                    "country": "",
                    "description": enrichment.description,
                    "tech_stack": techs or None,
                    "meta_description": meta_desc or None,
                    "logo_url": logo or None,
                    "employee_estimate": emp_est or None,
                    "keywords": keywords or None,
                    "leads": [lead_dict],
                })
                saved += 1
                logger.info("SAVED %s (score %d)", disc.domain, best_score)

            except Exception:
                logger.exception("Error processing %s", disc.name)

        # ── Submit results ────────────────────────────────────────────────
        duration = time.monotonic() - start
        if results:
            ok = client.submit_results(job_id, results, duration)
            if ok:
                logger.info("Job %d done – submitted %d companies (%.1fs)", job_id, saved, duration)
            else:
                logger.error("Job %d – failed to submit results to server", job_id)
                client.fail(job_id)
        else:
            # No results but job is complete
            client.submit_results(job_id, [], duration)
            logger.info("Job %d done – 0 companies matched (%.1fs)", job_id, duration)

    except Exception:
        logger.exception("Pipeline failed for job %d", job_id)
        client.fail(job_id)


# ── Heartbeat background thread ──────────────────────────────────────────────

def _heartbeat_loop(client: ServerClient, interval: int = 25):
    """Send heartbeats in a background thread until shutdown."""
    while not _shutdown.is_set():
        ok = client.heartbeat()
        if not ok:
            logger.warning("Heartbeat failed – server unreachable?")
        _shutdown.wait(interval)


# ── Main loop ─────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="LeadPulse local crawler worker")
    parser.add_argument(
        "--server",
        default=os.getenv("LEADPULSE_SERVER", "http://localhost:8000"),
        help="Comma-separated base URL(s) of the LeadPulse server "
             "(default: http://localhost:8000; set LEADPULSE_SERVER env var for production)",
    )
    parser.add_argument(
        "--secret",
        default=os.getenv("WORKER_SECRET", _DEFAULT_SECRET),
        help="Shared worker authentication secret",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=int(os.getenv("WORKER_POLL_INTERVAL", "30")),
        help="Seconds between polling for new jobs (default: 30)",
    )
    args = parser.parse_args()

    server_urls = [u.strip() for u in args.server.split(",") if u.strip()]
    if not server_urls:
        logger.error("No server URL(s) provided")
        sys.exit(1)

    client = ServerClient(server_urls, args.secret)

    # Verify connectivity
    logger.info("Connecting to %s …", ", ".join(server_urls))
    if not client.heartbeat():
        logger.error("Cannot reach any server – check URLs and secret")
        sys.exit(1)
    logger.info("Connected. Polling every %ds. Press Ctrl+C to stop.", args.interval)

    # Start heartbeat thread
    hb_thread = threading.Thread(target=_heartbeat_loop, args=(client,), daemon=True)
    hb_thread.start()

    # Main polling loop
    while not _shutdown.is_set():
        try:
            jobs = client.get_pending_jobs()
            if jobs:
                job = jobs[0]  # take oldest pending
                logger.info("Claiming job %d: '%s' in '%s'", job["id"], job["query"], job["location"])
                if client.claim(job["id"]):
                    run_local_pipeline(client, job["id"], job["query"], job["location"])
                else:
                    logger.warning("Could not claim job %d – may already be taken", job["id"])
            else:
                logger.debug("No pending jobs.")
        except Exception:
            logger.exception("Error in polling loop")

        # Wait for next poll (interruptible)
        _shutdown.wait(args.interval)

    logger.info("Worker stopped.")


if __name__ == "__main__":
    main()

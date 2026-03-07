"""Pipeline orchestrator – the background task that drives end-to-end lead discovery."""

from __future__ import annotations

import json
import logging
import time as _time
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.config import MIN_LEAD_SCORE, INDUSTRY_KEYWORDS
from app.models.company import Company
from app.models.lead import Lead
from app.models.job import Job
from app.services.discovery_service import discover_companies, _is_article_url, _is_bad_domain
from app.services.crawler_service import crawl_website
from app.services.extraction_service import extract_contacts_from_html, merge_contacts
from app.services.enrichment_service import enrich
from app.services.scoring_service import score_lead, validate_email
from app.services.dedupe_service import is_duplicate_company, is_duplicate_lead, deduplicate_emails
from app.services.techdetect_service import detect_technologies, detect_from_headers, extract_meta_info, estimate_company_size
from app.services.validation_service import validate_business
from app.utils.email_utils import classify_email_role
from app.utils.text_utils import clean_html_text

logger = logging.getLogger(__name__)


def _get_industry_keywords(query: str) -> list[str]:
    """Return industry keywords matching the query, or an empty list."""
    q = query.lower()
    for industry, kws in INDUSTRY_KEYWORDS.items():
        if industry in q or any(kw in q for kw in kws[:3]):
            return kws
    return []


def _has_industry_relevance(text: str, keywords: list[str]) -> bool:
    """Check if any industry keyword appears in the combined crawled text."""
    if not keywords:
        return True  # No industry keywords defined → don't block
    text_lower = text.lower()
    return any(kw in text_lower for kw in keywords)


def _set_stage(db: Session, job: Job, stage: str) -> None:
    """Update the current pipeline stage on the job record."""
    job.current_stage = stage
    db.commit()


def run_pipeline(job_id: int) -> None:
    """Execute the full lead-discovery pipeline for a given job.

    Quality gates:
      - Business validation: homepage must have ≥3 business signals
      - Industry relevance: crawled text must contain ≥1 industry keyword
      - Contact requirement: at least one email OR phone needed
      - Score threshold: leads scoring < MIN_LEAD_SCORE are discarded
      - Strict dedup: by (normalized domain, email)
    """
    db: Session = SessionLocal()
    try:
        job = db.get(Job, job_id)
        if not job:
            logger.error("Job %s not found", job_id)
            return

        job.status = "running"
        _set_stage(db, job, "discovering")
        _start_time = _time.monotonic()

        # ── Step 1: Discover companies ────────────────────────────────────
        discovered = discover_companies(job.query, job.location)
        job.total_companies = len(discovered)
        _set_stage(db, job, "crawling")

        industry_kws = _get_industry_keywords(job.query)
        logger.info("Industry keywords for '%s': %s", job.query, industry_kws[:5] if industry_kws else "none")

        saved_count = 0
        skipped_validation = 0
        skipped_contacts = 0
        skipped_score = 0
        skipped_relevance = 0
        seen_domain_email: set[tuple[str, str]] = set()

        for idx, disc in enumerate(discovered, 1):
            try:
                # ── Dedup check ───────────────────────────────────────────
                if is_duplicate_company(db, disc.domain, disc.name):
                    job.processed_companies = idx
                    db.commit()
                    continue

                # Check domain quality
                if _is_bad_domain(disc.domain):
                    logger.info("SKIP (bad domain) %s", disc.domain)
                    job.processed_companies = idx
                    db.commit()
                    continue

                # ── Step 2: Crawl ─────────────────────────────────────────
                _set_stage(db, job, "crawling")
                pages = crawl_website(disc.website)
                website_active = len(pages) > 0
                has_contact_page = any(
                    kw in p.url.lower() for p in pages for kw in ("contact", "about", "team")
                )

                # Reject pages that look like articles/blog posts
                pages = [p for p in pages if not _is_article_url(p.url)]

                # ── Quality Gate 1: Business validation ───────────────────
                if pages:
                    all_html = " ".join(p.html for p in pages)
                    is_biz, confidence, signals = validate_business(all_html)
                    if not is_biz:
                        logger.info(
                            "SKIP (not a business) %s – confidence=%.2f, signals=%s",
                            disc.domain, confidence, signals,
                        )
                        skipped_validation += 1
                        job.processed_companies = idx
                        db.commit()
                        continue
                else:
                    logger.info("SKIP (no pages crawled) %s", disc.domain)
                    skipped_validation += 1
                    job.processed_companies = idx
                    db.commit()
                    continue

                # ── Quality Gate 1b: Industry relevance ───────────────────
                full_text = " ".join(clean_html_text(p.html) for p in pages)
                if not _has_industry_relevance(full_text, industry_kws):
                    logger.info("SKIP (no industry relevance) %s", disc.domain)
                    skipped_relevance += 1
                    job.processed_companies = idx
                    db.commit()
                    continue

                # ── Step 3: Extract contacts ──────────────────────────────
                _set_stage(db, job, "extracting")
                page_contacts = [
                    extract_contacts_from_html(p.html, source_url=p.url) for p in pages
                ]
                merged = merge_contacts(page_contacts)
                merged.emails = deduplicate_emails(merged.emails)

                # ── Quality Gate 2: Contact requirement ───────────────────
                has_email = bool(merged.emails)
                has_phone = bool(merged.phones)
                if not has_email and not has_phone:
                    logger.info("SKIP (no contacts) %s", disc.domain)
                    skipped_contacts += 1
                    job.processed_companies = idx
                    db.commit()
                    continue

                # ── Step 3b: Tech detection & meta ────────────────────────
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

                # Check if domain is high-risk (e.g. suspicious patterns)
                is_high_risk = disc.domain.count("-") >= 3

                # Check industry keyword presence for scoring
                industry_kw_present = _has_industry_relevance(full_text, industry_kws) if industry_kws else False

                # ── Step 4: Enrich ────────────────────────────────────────
                _set_stage(db, job, "enriching")
                enrichment = enrich(full_text[:8000])
                keywords = enrichment.keywords if hasattr(enrichment, 'keywords') and enrichment.keywords else []

                # ── Step 5: Score leads & apply threshold ─────────────────
                _set_stage(db, job, "scoring")

                leads_to_save: list[Lead] = []

                if merged.emails:
                    for email in merged.emails[:5]:
                        # Strict dedup: (domain, email)
                        dedup_key = (disc.domain, email.lower())
                        if dedup_key in seen_domain_email:
                            continue
                        seen_domain_email.add(dedup_key)

                        is_valid = validate_email(email)
                        role = classify_email_role(email)
                        breakdown = score_lead(
                            email=email,
                            email_valid=is_valid,
                            phone=merged.phones[0] if merged.phones else None,
                            has_contact_page=has_contact_page,
                            has_industry_keyword=industry_kw_present,
                            website_active=website_active,
                            is_high_risk_domain=is_high_risk,
                        )
                        if breakdown.total < MIN_LEAD_SCORE:
                            logger.debug(
                                "SKIP lead %s (score %d < %d)", email, breakdown.total, MIN_LEAD_SCORE,
                            )
                            continue
                        leads_to_save.append(
                            Lead(
                                email=email,
                                phone=merged.phones[0] if merged.phones else None,
                                address=merged.addresses[0] if merged.addresses else None,
                                linkedin=merged.linkedin,
                                lead_score=breakdown.total,
                                email_valid=is_valid,
                                source_url=merged.source_url,
                                role=role,
                                score_breakdown=breakdown.to_json(),
                            )
                        )
                else:
                    # Phone-only lead
                    breakdown = score_lead(
                        phone=merged.phones[0] if merged.phones else None,
                        has_contact_page=has_contact_page,
                        has_industry_keyword=industry_kw_present,
                        website_active=website_active,
                        is_high_risk_domain=is_high_risk,
                    )
                    if breakdown.total >= MIN_LEAD_SCORE:
                        leads_to_save.append(
                            Lead(
                                phone=merged.phones[0] if merged.phones else None,
                                address=merged.addresses[0] if merged.addresses else None,
                                linkedin=merged.linkedin,
                                lead_score=breakdown.total,
                                source_url=merged.source_url,
                                score_breakdown=breakdown.to_json(),
                            )
                        )

                # ── Quality Gate 3: Score threshold ───────────────────────
                if not leads_to_save:
                    logger.info("SKIP (all leads below score %d) %s", MIN_LEAD_SCORE, disc.domain)
                    skipped_score += 1
                    job.processed_companies = idx
                    db.commit()
                    continue

                # ── Save company + leads ──────────────────────────────────
                company = Company(
                    name=disc.name,
                    website=disc.website,
                    domain=disc.domain,
                    industry=enrichment.industry or job.query,
                    city=job.location,
                    country="",
                    description=enrichment.description,
                    job_id=job.id,
                    tech_stack=json.dumps(techs) if techs else None,
                    meta_description=meta_desc or None,
                    logo_url=logo or None,
                    employee_estimate=emp_est or None,
                    keywords=json.dumps(keywords) if keywords else None,
                )
                db.add(company)
                db.flush()

                for lead in leads_to_save:
                    if lead.email and is_duplicate_lead(db, company.id, lead.email):
                        continue
                    lead.company_id = company.id
                    db.add(lead)

                saved_count += 1
                job.processed_companies = idx
                db.commit()
                logger.info("SAVED lead(s) for %s (score %d+)", disc.domain,
                            leads_to_save[0].lead_score if leads_to_save else 0)

            except Exception:
                logger.exception("Error processing company %s", disc.name)
                db.rollback()
                job.processed_companies = idx
                db.commit()

        job.status = "completed"
        job.current_stage = "completed"
        job.completed_at = datetime.now(timezone.utc)
        job.duration_seconds = round(_time.monotonic() - _start_time, 1)
        db.commit()
        logger.info(
            "Job %s completed – %d saved, skipped: validation=%d, relevance=%d, contacts=%d, score=%d",
            job_id, saved_count, skipped_validation, skipped_relevance, skipped_contacts, skipped_score,
        )

    except Exception:
        logger.exception("Pipeline failed for job %s", job_id)
        try:
            job = db.get(Job, job_id)
            if job:
                job.status = "failed"
                db.commit()
        except Exception:
            pass
    finally:
        db.close()

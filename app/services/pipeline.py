"""Pipeline orchestrator – the background task that drives end-to-end lead discovery."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.company import Company
from app.models.lead import Lead
from app.models.job import Job
from app.services.discovery_service import discover_companies
from app.services.crawler_service import crawl_website
from app.services.extraction_service import extract_contacts_from_html, merge_contacts
from app.services.enrichment_service import enrich
from app.services.scoring_service import score_lead, validate_email
from app.services.dedupe_service import is_duplicate_company, is_duplicate_lead, deduplicate_emails
from app.services.techdetect_service import detect_technologies, detect_from_headers, extract_meta_info, estimate_company_size
from app.utils.email_utils import classify_email_role
from app.utils.text_utils import clean_html_text

logger = logging.getLogger(__name__)


def _set_stage(db: Session, job: Job, stage: str) -> None:
    """Update the current pipeline stage on the job record."""
    job.current_stage = stage
    db.commit()


def run_pipeline(job_id: int) -> None:
    """Execute the full lead-discovery pipeline for a given job.

    Designed to be called inside ``BackgroundTasks.add_task()``.
    Opens its own DB session so it is fully self-contained.
    """
    db: Session = SessionLocal()
    try:
        job = db.query(Job).get(job_id)
        if not job:
            logger.error("Job %s not found", job_id)
            return

        job.status = "running"
        _set_stage(db, job, "discovering")

        # ── Step 1: Discover companies ────────────────────────────────────
        discovered = discover_companies(job.query, job.location)
        job.total_companies = len(discovered)
        _set_stage(db, job, "crawling")

        for idx, disc in enumerate(discovered, 1):
            try:
                # ── Dedup check ───────────────────────────────────────────
                if is_duplicate_company(db, disc.domain, disc.name):
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

                # ── Step 3: Extract contacts ──────────────────────────────
                _set_stage(db, job, "extracting")
                page_contacts = [
                    extract_contacts_from_html(p.html, source_url=p.url) for p in pages
                ]
                merged = merge_contacts(page_contacts)
                merged.emails = deduplicate_emails(merged.emails)

                # ── Step 3b: Tech detection & meta ────────────────────────
                all_html = " ".join(p.html for p in pages)
                techs: list[str] = []
                meta_desc = ""
                logo = ""
                emp_est = ""

                if pages:
                    techs = detect_technologies(pages[0].html)
                    # Also check headers if available
                    header_techs = detect_from_headers({})  # headers not stored, pass empty
                    techs = list(set(techs + header_techs))

                    meta = extract_meta_info(pages[0].html)
                    meta_desc = meta.get("description", "")
                    logo = meta.get("og_image", "")

                full_text = " ".join(clean_html_text(p.html) for p in pages)
                emp_est = estimate_company_size(full_text[:5000])

                # ── Step 4: Enrich ────────────────────────────────────────
                _set_stage(db, job, "enriching")
                enrichment = enrich(full_text[:8000])

                # ── Step 4b: Extract keywords from enrichment ─────────────
                keywords = enrichment.keywords if hasattr(enrichment, 'keywords') and enrichment.keywords else []

                # ── Save company ──────────────────────────────────────────
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

                # ── Step 5 & 6: Score + Save leads ────────────────────────
                _set_stage(db, job, "scoring")

                if merged.emails:
                    for email in merged.emails[:5]:  # cap per company
                        if is_duplicate_lead(db, company.id, email):
                            continue

                        is_valid = validate_email(email)
                        role = classify_email_role(email)
                        is_personal = role in ("Executive", "Personal")
                        breakdown = score_lead(
                            email=email,
                            email_valid=is_valid,
                            phone=merged.phones[0] if merged.phones else None,
                            linkedin=merged.linkedin,
                            has_contact_page=has_contact_page,
                            description=enrichment.description,
                            website_active=website_active,
                            tech_detected=len(techs) > 0,
                            is_personal_email=is_personal,
                        )
                        lead = Lead(
                            company_id=company.id,
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
                        db.add(lead)
                else:
                    # No email found – still create a lead record with phone/social
                    breakdown = score_lead(
                        phone=merged.phones[0] if merged.phones else None,
                        linkedin=merged.linkedin,
                        has_contact_page=has_contact_page,
                        description=enrichment.description,
                        website_active=website_active,
                        tech_detected=len(techs) > 0,
                    )
                    lead = Lead(
                        company_id=company.id,
                        phone=merged.phones[0] if merged.phones else None,
                        address=merged.addresses[0] if merged.addresses else None,
                        linkedin=merged.linkedin,
                        lead_score=breakdown.total,
                        source_url=merged.source_url,
                        score_breakdown=breakdown.to_json(),
                    )
                    db.add(lead)

                job.processed_companies = idx
                db.commit()

            except Exception:
                logger.exception("Error processing company %s", disc.name)
                db.rollback()
                job.processed_companies = idx
                db.commit()

        job.status = "completed"
        job.current_stage = "completed"
        job.completed_at = datetime.now(timezone.utc)
        db.commit()
        logger.info("Job %s completed – %d companies processed", job_id, job.processed_companies)

    except Exception:
        logger.exception("Pipeline failed for job %s", job_id)
        try:
            job = db.query(Job).get(job_id)
            if job:
                job.status = "failed"
                db.commit()
        except Exception:
            pass
    finally:
        db.close()

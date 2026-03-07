"""Pipeline orchestrator – the background task that drives end-to-end lead discovery."""

from __future__ import annotations

import logging

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
from app.utils.text_utils import clean_html_text

logger = logging.getLogger(__name__)


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
        db.commit()

        # ── Step 1: Discover companies ────────────────────────────────────
        discovered = discover_companies(job.query, job.location)
        job.total_companies = len(discovered)
        db.commit()

        for idx, disc in enumerate(discovered, 1):
            try:
                # ── Dedup check ───────────────────────────────────────────
                if is_duplicate_company(db, disc.domain, disc.name):
                    job.processed_companies = idx
                    db.commit()
                    continue

                # ── Step 2: Crawl ─────────────────────────────────────────
                pages = crawl_website(disc.website)
                website_active = len(pages) > 0
                has_contact_page = any(
                    kw in p.url.lower() for p in pages for kw in ("contact", "about", "team")
                )

                # ── Step 3: Extract contacts ──────────────────────────────
                page_contacts = [
                    extract_contacts_from_html(p.html, source_url=p.url) for p in pages
                ]
                merged = merge_contacts(page_contacts)
                merged.emails = deduplicate_emails(merged.emails)

                # ── Step 4: Enrich ────────────────────────────────────────
                full_text = " ".join(clean_html_text(p.html) for p in pages)
                enrichment = enrich(full_text[:8000])

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
                )
                db.add(company)
                db.flush()

                # ── Step 5 & 6: Score + Save leads ────────────────────────
                if merged.emails:
                    for email in merged.emails[:5]:  # cap per company
                        if is_duplicate_lead(db, company.id, email):
                            continue

                        is_valid = validate_email(email)
                        breakdown = score_lead(
                            email=email,
                            email_valid=is_valid,
                            phone=merged.phones[0] if merged.phones else None,
                            linkedin=merged.linkedin,
                            has_contact_page=has_contact_page,
                            description=enrichment.description,
                            website_active=website_active,
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
                    )
                    lead = Lead(
                        company_id=company.id,
                        phone=merged.phones[0] if merged.phones else None,
                        address=merged.addresses[0] if merged.addresses else None,
                        linkedin=merged.linkedin,
                        lead_score=breakdown.total,
                        source_url=merged.source_url,
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

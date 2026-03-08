"""Worker API – endpoints consumed by the local crawler worker."""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import WORKER_SECRET, WORKER_HEARTBEAT_TIMEOUT
from app.database import get_db
from app.models.company import Company
from app.models.job import Job
from app.models.lead import Lead

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/worker", tags=["worker"])

# ── In-memory heartbeat tracking ─────────────────────────────────────────────
_last_heartbeat: float | None = None


def _verify_secret(authorization: str = Header(...)) -> None:
    """Validate the shared worker secret from the Authorization header."""
    expected = f"Bearer {WORKER_SECRET}"
    if authorization != expected:
        raise HTTPException(status_code=401, detail="Invalid worker secret")


def is_worker_online() -> bool:
    """Return True if the worker has sent a heartbeat recently."""
    if _last_heartbeat is None:
        return False
    return (time.time() - _last_heartbeat) < WORKER_HEARTBEAT_TIMEOUT


# ── Heartbeat ─────────────────────────────────────────────────────────────────
@router.post("/heartbeat")
async def heartbeat(_: None = Depends(_verify_secret)):
    global _last_heartbeat
    _last_heartbeat = time.time()
    return {"ok": True}


# ── Disconnect (worker calls this on graceful shutdown) ───────────────────────
@router.post("/disconnect")
async def disconnect(_: None = Depends(_verify_secret)):
    global _last_heartbeat
    _last_heartbeat = None
    logger.info("Worker disconnected explicitly.")
    return {"ok": True}


# ── Worker status (public, used by dashboard JS) ─────────────────────────────
@router.get("/status")
async def worker_status():
    return {"online": is_worker_online()}


# ── Pending jobs for the worker to pick up ────────────────────────────────────
@router.get("/jobs")
async def pending_jobs(
    db: Session = Depends(get_db),
    _: None = Depends(_verify_secret),
):
    jobs = (
        db.query(Job)
        .filter(Job.status == "pending")
        .order_by(Job.created_at.asc())
        .all()
    )
    return [
        {
            "id": j.id,
            "query": j.query,
            "location": j.location,
            "max_companies": j.max_companies or 30,
            "max_pages": j.max_pages or 5,
            "min_score": j.min_score or 40,
        }
        for j in jobs
    ]


# ── Claim a job (worker sets it to "running") ────────────────────────────────
@router.post("/claim/{job_id}")
async def claim_job(
    job_id: int,
    db: Session = Depends(get_db),
    _: None = Depends(_verify_secret),
):
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status != "pending":
        raise HTTPException(status_code=409, detail="Job already claimed")
    job.status = "running"
    job.current_stage = "discovering"
    db.commit()
    return {"ok": True}


# ── Progress update ───────────────────────────────────────────────────────────
class ProgressPayload(BaseModel):
    current_stage: str
    total_companies: int = 0
    processed_companies: int = 0


@router.post("/job/{job_id}/progress")
async def update_progress(
    job_id: int,
    payload: ProgressPayload,
    db: Session = Depends(get_db),
    _: None = Depends(_verify_secret),
):
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    job.current_stage = payload.current_stage
    job.total_companies = payload.total_companies
    job.processed_companies = payload.processed_companies
    db.commit()
    return {"ok": True}


# ── Results submission ────────────────────────────────────────────────────────
class LeadPayload(BaseModel):
    email: str | None = None
    phone: str | None = None
    address: str | None = None
    linkedin: str | None = None
    lead_score: float = 0.0
    email_valid: bool = False
    source_url: str | None = None
    role: str | None = None
    score_breakdown: str | None = None
    extra_emails: str | None = None


class CompanyPayload(BaseModel):
    name: str
    website: str | None = None
    domain: str | None = None
    industry: str | None = None
    city: str | None = None
    country: str | None = None
    description: str | None = None
    tech_stack: list[str] | None = None
    meta_description: str | None = None
    logo_url: str | None = None
    employee_estimate: str | None = None
    keywords: list[str] | None = None
    leads: list[LeadPayload] = []


class ResultsPayload(BaseModel):
    companies: list[CompanyPayload] = []
    duration_seconds: float | None = None


@router.post("/job/{job_id}/results")
async def submit_results(
    job_id: int,
    payload: ResultsPayload,
    db: Session = Depends(get_db),
    _: None = Depends(_verify_secret),
):
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    saved = 0
    for cp in payload.companies:
        company = Company(
            name=cp.name,
            website=cp.website,
            domain=cp.domain,
            industry=cp.industry,
            city=cp.city,
            country=cp.country or "",
            description=cp.description,
            job_id=job_id,
            tech_stack=json.dumps(cp.tech_stack) if cp.tech_stack else None,
            meta_description=cp.meta_description,
            logo_url=cp.logo_url,
            employee_estimate=cp.employee_estimate,
            keywords=json.dumps(cp.keywords) if cp.keywords else None,
        )
        db.add(company)
        db.flush()

        for lp in cp.leads:
            lead = Lead(
                company_id=company.id,
                email=lp.email,
                phone=lp.phone,
                address=lp.address,
                linkedin=lp.linkedin,
                lead_score=lp.lead_score,
                email_valid=lp.email_valid,
                source_url=lp.source_url,
                role=lp.role,
                score_breakdown=lp.score_breakdown,
                extra_emails=lp.extra_emails,
            )
            db.add(lead)
        saved += 1

    job.status = "completed"
    job.current_stage = "completed"
    job.completed_at = datetime.now(timezone.utc)
    job.duration_seconds = payload.duration_seconds
    db.commit()

    logger.info("Worker submitted %d companies for job %d", saved, job_id)
    return {"ok": True, "companies_saved": saved}


# ── Mark job as failed ────────────────────────────────────────────────────────
@router.post("/job/{job_id}/fail")
async def fail_job(
    job_id: int,
    db: Session = Depends(get_db),
    _: None = Depends(_verify_secret),
):
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    job.status = "failed"
    db.commit()
    return {"ok": True}


# ── Job status check (worker polls this to detect cancellation) ───────────────
@router.get("/job/{job_id}/status")
async def job_status_check(
    job_id: int,
    db: Session = Depends(get_db),
    _: None = Depends(_verify_secret),
):
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return {"status": job.status}

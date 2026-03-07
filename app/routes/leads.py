"""Leads route – paginated lead listing with filters."""

from __future__ import annotations

import math

from fastapi import APIRouter, Request, Depends, Query
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func

from app.database import get_db
from app.models.lead import Lead
from app.models.company import Company
from app.models.job import Job

router = APIRouter()

PAGE_SIZE = 20


@router.get("/leads")
async def leads_page(
    request: Request,
    db: Session = Depends(get_db),
    industry: str | None = Query(None),
    city: str | None = Query(None),
    min_score: float | None = Query(None),
    job_id: int | None = Query(None),
    page: int = Query(1, ge=1),
):
    query = db.query(Lead).join(Company).options(joinedload(Lead.company))

    if industry:
        query = query.filter(Company.industry.ilike(f"%{industry}%"))
    if city:
        query = query.filter(Company.city.ilike(f"%{city}%"))
    if min_score is not None:
        query = query.filter(Lead.lead_score >= min_score)
    if job_id is not None:
        query = query.filter(Company.job_id == job_id)

    total = query.count()
    total_pages = max(1, math.ceil(total / PAGE_SIZE))
    page = min(page, total_pages)

    leads = (
        query.order_by(Lead.lead_score.desc())
        .offset((page - 1) * PAGE_SIZE)
        .limit(PAGE_SIZE)
        .all()
    )

    # Distinct filter options
    industries = [
        r[0]
        for r in db.query(Company.industry).filter(Company.industry.isnot(None)).distinct().all()
    ]
    cities = [
        r[0]
        for r in db.query(Company.city).filter(Company.city.isnot(None), Company.city != "").distinct().all()
    ]
    jobs = db.query(Job).order_by(Job.created_at.desc()).all()

    return request.app.state.templates.TemplateResponse(
        "leads.html",
        {
            "request": request,
            "leads": leads,
            "page": page,
            "total_pages": total_pages,
            "total": total,
            "industries": sorted(industries),
            "cities": sorted(cities),
            "jobs": jobs,
            "filter_industry": industry or "",
            "filter_city": city or "",
            "filter_min_score": min_score if min_score is not None else "",
            "filter_job_id": job_id if job_id is not None else "",
        },
    )


@router.get("/api/leads")
async def api_leads(
    db: Session = Depends(get_db),
    industry: str | None = Query(None),
    city: str | None = Query(None),
    min_score: float | None = Query(None),
    page: int = Query(1, ge=1),
):
    query = db.query(Lead).join(Company).options(joinedload(Lead.company))

    if industry:
        query = query.filter(Company.industry.ilike(f"%{industry}%"))
    if city:
        query = query.filter(Company.city.ilike(f"%{city}%"))
    if min_score is not None:
        query = query.filter(Lead.lead_score >= min_score)

    total = query.count()
    leads = (
        query.order_by(Lead.lead_score.desc())
        .offset((page - 1) * PAGE_SIZE)
        .limit(PAGE_SIZE)
        .all()
    )

    return {
        "total": total,
        "page": page,
        "leads": [
            {
                "id": l.id,
                "company": l.company.name if l.company else None,
                "email": l.email,
                "phone": l.phone,
                "industry": l.company.industry if l.company else None,
                "city": l.company.city if l.company else None,
                "lead_score": l.lead_score,
                "email_valid": l.email_valid,
                "website": l.company.website if l.company else None,
                "source_url": l.source_url,
            }
            for l in leads
        ],
    }


# ── Delete single lead ───────────────────────────────────────────────────────
@router.post("/leads/{lead_id}/delete")
async def delete_lead(lead_id: int, db: Session = Depends(get_db)):
    lead = db.query(Lead).get(lead_id)
    if lead:
        db.delete(lead)
        db.commit()
    return RedirectResponse(url="/leads", status_code=303)


# ── Delete all leads ─────────────────────────────────────────────────────────
@router.post("/leads/delete-all")
async def delete_all_leads(db: Session = Depends(get_db)):
    db.query(Lead).delete()
    db.commit()
    return RedirectResponse(url="/leads", status_code=303)

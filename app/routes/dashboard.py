"""Dashboard route – landing page with summary stats."""

from fastapi import APIRouter, Request, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.database import get_db
from app.models.company import Company
from app.models.lead import Lead
from app.models.job import Job
from app.routes.worker import is_worker_online

router = APIRouter()


@router.get("/")
async def dashboard(request: Request, db: Session = Depends(get_db)):
    total_leads = db.query(func.count(Lead.id)).scalar() or 0
    valid_emails = db.query(func.count(Lead.id)).filter(Lead.email_valid == True).scalar() or 0
    total_companies = db.query(func.count(Company.id)).scalar() or 0
    avg_score = db.query(func.avg(Lead.lead_score)).scalar() or 0

    # Top industries
    top_industries = (
        db.query(Company.industry, func.count(Company.id).label("cnt"))
        .filter(Company.industry.isnot(None))
        .group_by(Company.industry)
        .order_by(func.count(Company.id).desc())
        .limit(6)
        .all()
    )

    # Recent jobs
    recent_jobs = db.query(Job).order_by(Job.created_at.desc()).limit(5).all()

    # High-score leads
    top_leads = (
        db.query(Lead)
        .join(Company)
        .order_by(Lead.lead_score.desc())
        .limit(5)
        .all()
    )

    return request.app.state.templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "total_leads": total_leads,
            "valid_emails": valid_emails,
            "total_companies": total_companies,
            "avg_score": round(avg_score, 1),
            "top_industries": top_industries,
            "recent_jobs": recent_jobs,
            "top_leads": top_leads,
            "worker_online": is_worker_online(),
        },
    )

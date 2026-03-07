"""Search route – start a new lead-discovery job."""

from fastapi import APIRouter, Request, Depends, BackgroundTasks
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.job import Job
from app.models.company import Company
from app.models.lead import Lead
from app.services.pipeline import run_pipeline
from app.config import MAX_COMPANIES_PER_JOB

router = APIRouter()


class SearchRequest(BaseModel):
    industry: str = Field(..., min_length=2, max_length=200)
    location: str = Field(..., min_length=2, max_length=200)


# ── Page ──────────────────────────────────────────────────────────────────────
@router.get("/search")
async def search_page(request: Request):
    return request.app.state.templates.TemplateResponse(
        "search.html", {"request": request, "max_results": MAX_COMPANIES_PER_JOB}
    )


# ── API: start job ───────────────────────────────────────────────────────────
@router.post("/search")
async def start_search(
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    form = await request.form()
    industry = str(form.get("industry", "")).strip()
    location = str(form.get("location", "")).strip()

    if not industry or not location:
        return request.app.state.templates.TemplateResponse(
            "search.html",
            {"request": request, "error": "Both fields are required.", "max_results": MAX_COMPANIES_PER_JOB},
        )

    job = Job(query=industry, location=location)
    db.add(job)
    db.commit()
    db.refresh(job)

    background_tasks.add_task(run_pipeline, job.id)

    return RedirectResponse(url=f"/jobs/{job.id}", status_code=303)


# ── API: JSON endpoint for programmatic access ──────────────────────────────
@router.post("/api/search")
async def api_start_search(
    payload: SearchRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    job = Job(query=payload.industry, location=payload.location)
    db.add(job)
    db.commit()
    db.refresh(job)

    background_tasks.add_task(run_pipeline, job.id)

    return {"job_id": job.id, "status": job.status}


# ── Job status ───────────────────────────────────────────────────────────────
@router.get("/jobs/{job_id}")
async def job_status(job_id: int, request: Request, db: Session = Depends(get_db)):
    job = db.get(Job, job_id)
    if not job:
        return request.app.state.templates.TemplateResponse(
            "404.html", {"request": request}, status_code=404
        )
    return request.app.state.templates.TemplateResponse(
        "job_status.html", {"request": request, "job": job}
    )


@router.get("/api/jobs/{job_id}")
async def api_job_status(job_id: int, db: Session = Depends(get_db)):
    job = db.get(Job, job_id)
    if not job:
        return {"error": "Job not found"}
    return {
        "id": job.id,
        "query": job.query,
        "location": job.location,
        "status": job.status,
        "total_companies": job.total_companies,
        "processed_companies": job.processed_companies,
        "current_stage": job.current_stage,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "duration_seconds": job.duration_seconds,
    }


# ── Delete single job + its companies & leads ────────────────────────────────
@router.post("/jobs/{job_id}/delete")
async def delete_job(job_id: int, db: Session = Depends(get_db)):
    job = db.get(Job, job_id)
    if job:
        companies = db.query(Company).filter(Company.job_id == job_id).all()
        for company in companies:
            db.delete(company)  # cascade deletes leads
        db.delete(job)
        db.commit()
    return RedirectResponse(url="/", status_code=303)


# ── Delete all jobs + all companies & leads ──────────────────────────────────
@router.post("/jobs/delete-all")
async def delete_all_jobs(db: Session = Depends(get_db)):
    db.query(Lead).delete()
    db.query(Company).delete()
    db.query(Job).delete()
    db.commit()
    # Reset auto-increment so next IDs start from 1
    dialect = db.bind.dialect.name
    try:
        if dialect == "sqlite":
            # sqlite_sequence only exists if AUTOINCREMENT is used; ignore if missing
            for tbl in ("leads", "companies", "jobs"):
                db.execute(text(f"DELETE FROM sqlite_sequence WHERE name='{tbl}'"))
        elif dialect == "postgresql":
            for tbl in ("leads", "companies", "jobs"):
                db.execute(text(f"ALTER SEQUENCE {tbl}_id_seq RESTART WITH 1"))
        db.commit()
    except Exception:
        db.rollback()
    return RedirectResponse(url="/", status_code=303)

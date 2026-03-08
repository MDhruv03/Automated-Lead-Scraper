"""Analytics route – charts and deep insights."""

from __future__ import annotations

import json
from collections import Counter

from fastapi import APIRouter, Request, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.database import get_db
from app.models.company import Company
from app.models.lead import Lead
from app.models.job import Job

router = APIRouter()


@router.get("/analytics")
async def analytics_page(request: Request, db: Session = Depends(get_db)):
    # ── Core counts ───────────────────────────────────────────────────
    total_leads = db.query(func.count(Lead.id)).scalar() or 0
    total_companies = db.query(func.count(Company.id)).scalar() or 0
    total_jobs = db.query(func.count(Job.id)).scalar() or 0
    completed_jobs = (
        db.query(func.count(Job.id)).filter(Job.status == "completed").scalar() or 0
    )

    # ── Score stats ───────────────────────────────────────────────────
    avg_score = db.query(func.avg(Lead.lead_score)).scalar() or 0
    max_score = db.query(func.max(Lead.lead_score)).scalar() or 0

    # Email validity rate
    total_emails = (
        db.query(func.count(Lead.id)).filter(Lead.email.isnot(None)).scalar() or 0
    )
    valid_emails = (
        db.query(func.count(Lead.id)).filter(Lead.email_valid == True).scalar() or 0
    )
    email_rate = round(valid_emails / total_emails * 100, 1) if total_emails else 0

    # Phone coverage
    with_phone = (
        db.query(func.count(Lead.id)).filter(Lead.phone.isnot(None)).scalar() or 0
    )
    phone_rate = round(with_phone / total_leads * 100, 1) if total_leads else 0

    # ── Score quality tiers ───────────────────────────────────────────
    high_q = db.query(func.count(Lead.id)).filter(Lead.lead_score >= 70).scalar() or 0
    mid_q = (
        db.query(func.count(Lead.id))
        .filter(Lead.lead_score >= 40, Lead.lead_score < 70)
        .scalar()
        or 0
    )
    low_q = db.query(func.count(Lead.id)).filter(Lead.lead_score < 40).scalar() or 0

    # ── Score distribution (buckets of 10) ────────────────────────────
    scores = db.query(Lead.lead_score).filter(Lead.lead_score.isnot(None)).all()
    buckets = {f"{i}-{i+9}": 0 for i in range(0, 100, 10)}
    for (score,) in scores:
        s = int(score)
        key = f"{(s // 10) * 10}-{(s // 10) * 10 + 9}"
        if key in buckets:
            buckets[key] += 1

    # ── Industry breakdown ────────────────────────────────────────────
    industry_rows = (
        db.query(Company.industry, func.count(Company.id))
        .filter(Company.industry.isnot(None))
        .group_by(Company.industry)
        .order_by(func.count(Company.id).desc())
        .limit(8)
        .all()
    )

    # ── Location / city breakdown ─────────────────────────────────────
    city_rows = (
        db.query(Company.city, func.count(Company.id))
        .filter(Company.city.isnot(None), Company.city != "")
        .group_by(Company.city)
        .order_by(func.count(Company.id).desc())
        .limit(8)
        .all()
    )

    # ── Avg job duration ──────────────────────────────────────────────
    avg_duration = (
        db.query(func.avg(Job.duration_seconds))
        .filter(Job.duration_seconds.isnot(None))
        .scalar()
    )
    avg_duration_display = ""
    if avg_duration:
        secs = int(avg_duration)
        if secs >= 60:
            avg_duration_display = f"{secs // 60}m {secs % 60}s"
        else:
            avg_duration_display = f"{secs}s"

    return request.app.state.templates.TemplateResponse(
        "analytics.html",
        {
            "request": request,
            # stat cards
            "total_leads": total_leads,
            "total_companies": total_companies,
            "avg_score": round(avg_score, 1),
            "max_score": int(max_score),
            "email_rate": email_rate,
            "phone_rate": phone_rate,
            "completed_jobs": completed_jobs,
            "avg_duration": avg_duration_display or "—",
            # quality tiers
            "high_q": high_q,
            "mid_q": mid_q,
            "low_q": low_q,
            # charts (JSON for Chart.js)
            "score_labels": json.dumps(list(buckets.keys())),
            "score_data": json.dumps(list(buckets.values())),
            "industry_labels": json.dumps([r[0] for r in industry_rows]),
            "industry_data": json.dumps([r[1] for r in industry_rows]),
            # template-friendly lists for CSS-only rendering
            "city_items": city_rows,
            "max_city_count": city_rows[0][1] if city_rows else 1,
        },
    )

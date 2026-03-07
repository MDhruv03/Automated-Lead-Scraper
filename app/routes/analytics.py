"""Analytics route – charts and deep insights."""

from __future__ import annotations

import json
from collections import Counter

from fastapi import APIRouter, Request, Depends
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func

from app.database import get_db
from app.models.company import Company
from app.models.lead import Lead
from app.models.job import Job

router = APIRouter()


@router.get("/analytics")
async def analytics_page(request: Request, db: Session = Depends(get_db)):
    # ── Score distribution (buckets of 10) ────────────────────────────
    leads = db.query(Lead.lead_score).all()
    buckets = {f"{i}-{i+9}": 0 for i in range(0, 100, 10)}
    for (score,) in leads:
        key = f"{(score // 10) * 10}-{(score // 10) * 10 + 9}"
        if key in buckets:
            buckets[key] += 1

    # ── Industry breakdown ────────────────────────────────────────────
    industry_rows = (
        db.query(Company.industry, func.count(Company.id))
        .filter(Company.industry.isnot(None))
        .group_by(Company.industry)
        .order_by(func.count(Company.id).desc())
        .limit(10)
        .all()
    )

    # ── Email validity ────────────────────────────────────────────────
    total_emails = db.query(func.count(Lead.id)).filter(Lead.email.isnot(None)).scalar() or 0
    valid_emails = db.query(func.count(Lead.id)).filter(Lead.email_valid == True).scalar() or 0
    invalid_emails = total_emails - valid_emails

    # ── Role distribution ─────────────────────────────────────────────
    role_rows = (
        db.query(Lead.role, func.count(Lead.id))
        .filter(Lead.role.isnot(None))
        .group_by(Lead.role)
        .order_by(func.count(Lead.id).desc())
        .all()
    )

    # ── Tech stack distribution ───────────────────────────────────────
    companies = db.query(Company.tech_stack).filter(Company.tech_stack.isnot(None)).all()
    tech_counter: Counter[str] = Counter()
    for (ts,) in companies:
        try:
            techs = json.loads(ts) if ts else []
            for t in techs:
                tech_counter[t] += 1
        except (json.JSONDecodeError, TypeError):
            pass
    top_techs = tech_counter.most_common(12)

    # ── Job timeline ──────────────────────────────────────────────────
    jobs = (
        db.query(Job)
        .filter(Job.status == "completed")
        .order_by(Job.created_at.desc())
        .limit(15)
        .all()
    )
    timeline = [
        {
            "label": j.created_at.strftime("%b %d %H:%M") if j.created_at else "?",
            "companies": j.total_companies or 0,
        }
        for j in reversed(jobs)
    ]

    # ── Summary stats ─────────────────────────────────────────────────
    avg_score = db.query(func.avg(Lead.lead_score)).scalar() or 0
    max_score = db.query(func.max(Lead.lead_score)).scalar() or 0
    total_companies = db.query(func.count(Company.id)).scalar() or 0

    return request.app.state.templates.TemplateResponse(
        "analytics.html",
        {
            "request": request,
            "score_labels": json.dumps(list(buckets.keys())),
            "score_data": json.dumps(list(buckets.values())),
            "industry_labels": json.dumps([r[0] for r in industry_rows]),
            "industry_data": json.dumps([r[1] for r in industry_rows]),
            "email_valid": valid_emails,
            "email_invalid": invalid_emails,
            "role_labels": json.dumps([r[0] for r in role_rows]),
            "role_data": json.dumps([r[1] for r in role_rows]),
            "tech_labels": json.dumps([t[0] for t in top_techs]),
            "tech_data": json.dumps([t[1] for t in top_techs]),
            "timeline_labels": json.dumps([t["label"] for t in timeline]),
            "timeline_data": json.dumps([t["companies"] for t in timeline]),
            "avg_score": round(avg_score, 1),
            "max_score": int(max_score),
            "total_companies": total_companies,
            "total_leads": len(leads),
        },
    )

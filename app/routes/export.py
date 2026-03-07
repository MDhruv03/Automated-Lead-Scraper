"""Export route – download leads as Excel."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session, joinedload
import io

from app.database import get_db
from app.models.lead import Lead
from app.models.company import Company

router = APIRouter()


@router.get("/export")
async def export_leads(db: Session = Depends(get_db)):
    import pandas as pd

    leads = (
        db.query(Lead)
        .join(Company)
        .options(joinedload(Lead.company))
        .order_by(Lead.lead_score.desc())
        .all()
    )

    rows = []
    for l in leads:
        extra = ""
        if l.extra_emails:
            try:
                extras = json.loads(l.extra_emails)
                if isinstance(extras, list):
                    extra = ", ".join(extras)
            except (json.JSONDecodeError, TypeError):
                pass

        rows.append({
            "Company Name": l.company.name if l.company else "",
            "Website": l.company.website if l.company else "",
            "Domain": l.company.domain if l.company else "",
            "Email": l.email or "",
            "Extra Emails": extra,
            "Email Valid": "Yes" if l.email_valid else "No",
            "Contact Role": l.role or "",
            "Phone": l.phone or "",
            "LinkedIn": l.linkedin or "",
            "Address": l.address or "",
            "Industry": l.company.industry if l.company else "",
            "City": l.company.city if l.company else "",
            "Tech Stack": ", ".join(l.company.tech_list) if l.company and l.company.tech_list else "",
            "Employee Estimate": l.company.employee_estimate if l.company else "",
            "Lead Score": l.lead_score,
            "Source URL": l.source_url or "",
        })

    _cols = [
        "Company Name", "Website", "Domain", "Email", "Extra Emails", "Email Valid",
        "Contact Role", "Phone", "LinkedIn", "Address", "Industry", "City",
        "Tech Stack", "Employee Estimate", "Lead Score", "Source URL",
    ]
    df = pd.DataFrame(rows) if rows else pd.DataFrame(columns=_cols)

    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Leads")
    buf.seek(0)

    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=leads_export.xlsx"},
    )

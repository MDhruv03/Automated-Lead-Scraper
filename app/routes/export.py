"""Export route – download leads as Excel."""

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

    rows = [
        {
            "Company Name": l.company.name if l.company else "",
            "Website": l.company.website if l.company else "",
            "Domain": l.company.domain if l.company else "",
            "Email": l.email or "",
            "Email Valid": "Yes" if l.email_valid else "No",
            "Phone": l.phone or "",
            "LinkedIn": l.linkedin or "",
            "Address": l.address or "",
            "Industry": l.company.industry if l.company else "",
            "City": l.company.city if l.company else "",
            "Lead Score": l.lead_score,
            "Source URL": l.source_url or "",
        }
        for l in leads
    ]

    df = pd.DataFrame(rows) if rows else pd.DataFrame(
        columns=[
            "Company Name", "Website", "Domain", "Email", "Email Valid",
            "Phone", "LinkedIn", "Address", "Industry", "City",
            "Lead Score", "Source URL",
        ]
    )

    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Leads")
    buf.seek(0)

    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=leads_export.xlsx"},
    )

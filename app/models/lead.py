"""Lead model – individual contact records extracted from company websites."""

import json
from datetime import datetime, timezone

from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship

from app.database import Base


class Lead(Base):
    __tablename__ = "leads"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    email = Column(String(320))
    phone = Column(String(50))
    address = Column(String(500))
    linkedin = Column(String(500))
    lead_score = Column(Float, default=0.0)
    email_valid = Column(Boolean, default=False)
    source_url = Column(String(2000))

    # ── Enhanced fields ───────────────────────────────────────────────────
    role = Column(String(50))            # Executive, Sales, Support, etc.
    score_breakdown = Column(Text)       # JSON dict of scoring factors

    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    company = relationship("Company", back_populates="leads")

    @property
    def score_factors(self) -> dict:
        """Deserialise score_breakdown JSON."""
        if not self.score_breakdown:
            return {}
        try:
            return json.loads(self.score_breakdown)
        except (json.JSONDecodeError, TypeError):
            return {}

    def __repr__(self) -> str:
        return f"<Lead {self.email or self.phone}>"

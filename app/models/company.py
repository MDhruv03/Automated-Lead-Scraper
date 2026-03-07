"""Company model – stores discovered businesses."""

import json
from datetime import datetime, timezone

from sqlalchemy import Column, Integer, String, Text, DateTime
from sqlalchemy.orm import relationship

from app.database import Base


class Company(Base):
    __tablename__ = "companies"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(300), nullable=False)
    website = Column(String(500))
    domain = Column(String(253), index=True)
    industry = Column(String(200))
    city = Column(String(200))
    country = Column(String(100))
    description = Column(Text)
    job_id = Column(Integer, index=True)

    # ── Enhanced fields ───────────────────────────────────────────────────
    tech_stack = Column(Text)            # JSON list of detected technologies
    meta_description = Column(Text)      # OG / meta description from site
    logo_url = Column(String(500))       # Favicon / logo URL
    employee_estimate = Column(String(50))  # e.g. "11-50", "51-200"
    keywords = Column(Text)              # JSON list of NLP keywords

    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    leads = relationship("Lead", back_populates="company", cascade="all, delete-orphan")

    @property
    def tech_list(self) -> list[str]:
        """Deserialise tech_stack JSON into a Python list."""
        if not self.tech_stack:
            return []
        try:
            return json.loads(self.tech_stack)
        except (json.JSONDecodeError, TypeError):
            return []

    @property
    def keyword_list(self) -> list[str]:
        if not self.keywords:
            return []
        try:
            return json.loads(self.keywords)
        except (json.JSONDecodeError, TypeError):
            return []

    def __repr__(self) -> str:
        return f"<Company {self.name}>"

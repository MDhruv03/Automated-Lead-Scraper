"""Job model – tracks background pipeline runs."""

from datetime import datetime, timezone

from sqlalchemy import Column, Integer, String, DateTime, Float

from app.database import Base

# Pipeline stages in execution order
PIPELINE_STAGES = [
    "queued",
    "discovering",
    "crawling",
    "extracting",
    "enriching",
    "scoring",
    "completed",
]


class Job(Base):
    __tablename__ = "jobs"

    id = Column(Integer, primary_key=True, index=True)
    query = Column(String(300), nullable=False)
    location = Column(String(300), nullable=False)
    status = Column(String(20), default="pending", index=True)
    total_companies = Column(Integer, default=0)
    processed_companies = Column(Integer, default=0)
    current_stage = Column(String(30), default="queued")  # pipeline stage name
    duration_seconds = Column(Float, nullable=True)  # total wall-clock seconds
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    # Per-job pipeline settings (user-configurable at search time)
    max_companies = Column(Integer, default=30)
    max_pages = Column(Integer, default=5)
    min_score = Column(Integer, default=40)

    @property
    def stage_index(self) -> int:
        try:
            return PIPELINE_STAGES.index(self.current_stage or "queued")
        except ValueError:
            return 0

    @property
    def duration_display(self) -> str:
        """Human-readable duration string."""
        secs = self.duration_seconds
        if secs is None:
            return "—"
        secs = int(secs)
        if secs < 60:
            return f"{secs}s"
        mins, s = divmod(secs, 60)
        if mins < 60:
            return f"{mins}m {s}s"
        hrs, m = divmod(mins, 60)
        return f"{hrs}h {m}m {s}s"

    def __repr__(self) -> str:
        return f"<Job {self.id} – {self.status}>"

"""Video ORM model – one row per video within a job."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, Float, ForeignKey, Integer, String, Text

from app.models import Base


class Video(Base):
    __tablename__ = "videos"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    job_id = Column(String, ForeignKey("jobs.id"), nullable=False)
    video_id = Column(String, nullable=False)  # YouTube video ID
    title = Column(String, nullable=True)
    url = Column(String, nullable=True)
    channel = Column(String, nullable=True)
    channel_url = Column(String, nullable=True)
    upload_date = Column(String, nullable=True)
    duration = Column(Integer, nullable=True)
    description = Column(Text, nullable=True)
    thumbnail = Column(String, nullable=True)
    status = Column(String, nullable=False, default="pending")
    subtitle_status = Column(String, nullable=True)  # manual | auto | mixed | none
    subtitle_languages = Column(String, nullable=True)  # JSON array string
    transcript_source = Column(String, nullable=True)  # manual | auto | mixed | none
    transcript_path = Column(String, nullable=True)
    vtt_path = Column(String, nullable=True)
    error_message = Column(Text, nullable=True)
    relevance_score = Column(Float, nullable=True)
    created_at = Column(String, nullable=False, default=lambda: datetime.now(timezone.utc).isoformat())
    updated_at = Column(String, nullable=False, default=lambda: datetime.now(timezone.utc).isoformat())

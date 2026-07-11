"""Job ORM model – tracks a single collection run."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, Integer, String, Text

from app.models import Base


class Job(Base):
    __tablename__ = "jobs"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    source_url = Column(String, nullable=False)
    source_type = Column(String, nullable=False)  # channel | playlist | video | unknown
    status = Column(String, nullable=False, default="pending")
    languages = Column(String, nullable=True)  # JSON array string
    subtitle_mode = Column(String, nullable=True)  # manual | auto | manual_and_auto
    max_videos = Column(Integer, nullable=True)
    no_subtitle_strategy = Column(String, nullable=True)  # skip | top_relevant | manual_select
    total_videos = Column(Integer, default=0)
    processed_videos = Column(Integer, default=0)
    success_count = Column(Integer, default=0)
    failed_count = Column(Integer, default=0)
    no_subtitle_count = Column(Integer, default=0)
    zip_path = Column(String, nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(String, nullable=False, default=lambda: datetime.now(timezone.utc).isoformat())
    updated_at = Column(String, nullable=False, default=lambda: datetime.now(timezone.utc).isoformat())

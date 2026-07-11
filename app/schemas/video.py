"""Pydantic schemas for video and transcript responses."""

from typing import List, Optional

from pydantic import BaseModel


class VideoItem(BaseModel):
    """A single video row in the job's video list."""

    video_id: str
    title: Optional[str] = None
    url: Optional[str] = None
    channel: Optional[str] = None
    upload_date: Optional[str] = None
    duration: Optional[int] = None
    status: str = "pending"
    subtitle_status: Optional[str] = None
    subtitle_languages: Optional[List[str]] = None
    transcript_source: Optional[str] = None
    relevance_score: Optional[float] = None
    error_message: Optional[str] = None


class VideoListResponse(BaseModel):
    """Paginated video list."""

    items: List[VideoItem]
    total: int


class TranscriptResponse(BaseModel):
    """A single transcript's full text."""

    video_id: str
    title: Optional[str] = None
    language: str = "en"
    source: str = "auto"
    text: str = ""

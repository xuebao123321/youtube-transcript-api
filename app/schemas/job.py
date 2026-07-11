"""Pydantic schemas for job requests and responses."""

from typing import List, Optional

from pydantic import BaseModel, Field


class JobCreateRequest(BaseModel):
    """Payload for POST /api/youtube/jobs."""

    url: str
    languages: List[str] = ["en"]
    subtitle_mode: str = "manual_and_auto"
    max_videos: int = 5
    no_subtitle_strategy: str = "skip"
    relevance_keywords: List[str] = []


class JobCreateResponse(BaseModel):
    """Returned immediately after job creation."""

    job_id: str
    status: str


class JobResponse(BaseModel):
    """Returned by GET /api/youtube/jobs/{job_id}."""

    job_id: str
    status: str
    source_url: str
    source_type: str
    total_videos: int = 0
    processed_videos: int = 0
    success_count: int = 0
    failed_count: int = 0
    no_subtitle_count: int = 0
    progress: float = 0.0
    message: str = ""
    zip_ready: bool = False
    error_message: Optional[str] = None

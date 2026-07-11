"""Video list and transcript read APIs."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.video import Video
from app.schemas.video import TranscriptResponse, VideoItem, VideoListResponse

router = APIRouter(prefix="/api/youtube", tags=["videos"])


@router.get("/jobs/{job_id}/videos", response_model=VideoListResponse)
async def list_videos(
    job_id: str,
    db: AsyncSession = Depends(get_db),
    status: str | None = Query(None),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
):
    """Return paginated video list for a job, with optional status filter."""
    base = select(Video).where(Video.job_id == job_id)
    count_q = select(func.count(Video.id)).where(Video.job_id == job_id)

    if status:
        base = base.where(Video.status == status)
        count_q = count_q.where(Video.status == status)

    total_result = await db.execute(count_q)
    total = total_result.scalar() or 0

    rows = await db.execute(
        base.order_by(Video.created_at).offset(offset).limit(limit)
    )
    videos = rows.scalars().all()

    items = [_video_to_item(v) for v in videos]
    return VideoListResponse(items=items, total=total)


@router.get("/videos/{video_db_id}/transcript", response_model=TranscriptResponse)
async def get_transcript(video_db_id: str, db: AsyncSession = Depends(get_db)):
    """Read the transcript TXT file for a single video."""
    result = await db.execute(select(Video).where(Video.id == video_db_id))
    video = result.scalar_one_or_none()
    if not video:
        raise HTTPException(status_code=404, detail={"error": "NOT_FOUND", "message": "视频不存在。"})

    txt_path = video.transcript_path
    if not txt_path or not Path(txt_path).exists():
        raise HTTPException(status_code=404, detail={"error": "NOT_FOUND", "message": "逐字稿文件不存在。"})

    text = Path(txt_path).read_text(encoding="utf-8")

    # Determine language from subtitle_languages JSON
    lang = "en"
    source = video.transcript_source or "auto"
    try:
        langs = json.loads(video.subtitle_languages or "[]")
        if isinstance(langs, list) and langs:
            lang = langs[0]
    except (json.JSONDecodeError, TypeError):
        pass

    return TranscriptResponse(
        video_id=video.video_id,
        title=video.title,
        language=lang,
        source=source,
        text=text,
    )


# ------------------------------------------------------------------
def _video_to_item(v: Video) -> VideoItem:
    langs = None
    try:
        parsed = json.loads(v.subtitle_languages or "[]")
        if isinstance(parsed, list):
            langs = parsed
    except (json.JSONDecodeError, TypeError):
        pass

    return VideoItem(
        video_id=v.video_id,
        title=v.title,
        url=v.url,
        channel=v.channel,
        upload_date=v.upload_date,
        duration=v.duration,
        status=v.status,
        subtitle_status=v.subtitle_status,
        subtitle_languages=langs,
        transcript_source=v.transcript_source,
        relevance_score=v.relevance_score,
        error_message=v.error_message,
    )

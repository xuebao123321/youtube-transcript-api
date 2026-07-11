"""Job CRUD API – create, poll, cancel collection jobs."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session, get_db
from app.models.job import Job
from app.schemas.job import JobCreateRequest, JobCreateResponse, JobResponse
from app.utils.validators import validate_youtube_url
from app.workers.job_runner import STATUS_MESSAGES, JobRunner

router = APIRouter(prefix="/api/youtube/jobs", tags=["jobs"])


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@router.post("/", response_model=JobCreateResponse)
async def create_job(
    payload: JobCreateRequest,
    background_tasks: BackgroundTasks,
):
    """Create a new collection job and start it in the background."""
    source_type, normalized_url = validate_youtube_url(payload.url)
    if source_type == "unknown":
        raise HTTPException(
            status_code=400,
            detail={
                "error": "INVALID_URL",
                "message": "链接无法识别，请确认是 YouTube 频道、播放列表或视频链接。",
            },
        )

    job_id = str(uuid.uuid4())
    job = Job(
        id=job_id,
        source_url=normalized_url,
        source_type=source_type,
        status="pending",
        languages=json.dumps(payload.languages),
        subtitle_mode=payload.subtitle_mode,
        max_videos=payload.max_videos,
        no_subtitle_strategy=payload.no_subtitle_strategy,
        created_at=_now(),
        updated_at=_now(),
    )

    async with async_session() as db:
        db.add(job)
        await db.commit()

    # Fire-and-forget background task
    runner = JobRunner(async_session)
    background_tasks.add_task(runner.run_job, job_id)

    return JobCreateResponse(job_id=job_id, status="pending")


@router.get("/{job_id}", response_model=JobResponse)
async def get_job(job_id: str, db: AsyncSession = Depends(get_db)):
    """Poll job status / progress."""
    result = await db.execute(select(Job).where(Job.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail={"error": "NOT_FOUND", "message": "任务不存在。"})

    total = job.total_videos or 0
    processed = job.processed_videos or 0
    progress = (processed / total) if total > 0 else 0.0
    zip_ready = job.status == "completed" and bool(job.zip_path)

    return JobResponse(
        job_id=job.id,
        status=job.status,
        source_url=job.source_url,
        source_type=job.source_type,
        total_videos=total,
        processed_videos=processed,
        success_count=job.success_count or 0,
        failed_count=job.failed_count or 0,
        no_subtitle_count=job.no_subtitle_count or 0,
        progress=round(progress, 4),
        message=STATUS_MESSAGES.get(job.status, job.status),
        zip_ready=zip_ready,
        error_message=job.error_message,
    )


@router.delete("/{job_id}")
async def cancel_job(job_id: str, db: AsyncSession = Depends(get_db)):
    """Cancel a running job."""
    result = await db.execute(select(Job).where(Job.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail={"error": "NOT_FOUND", "message": "任务不存在。"})

    if job.status not in ("completed", "failed", "cancelled"):
        job.status = "cancelled"
        job.updated_at = _now()
        await db.commit()

    return {"status": "cancelled"}

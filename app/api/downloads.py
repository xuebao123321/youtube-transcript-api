"""ZIP download endpoint with path-traversal protection."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models.job import Job

router = APIRouter(prefix="/api/youtube", tags=["downloads"])


@router.get("/jobs/{job_id}/download")
async def download_zip(job_id: str, db: AsyncSession = Depends(get_db)):
    """Serve the completed ZIP package for a job."""
    result = await db.execute(select(Job).where(Job.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail={"error": "NOT_FOUND", "message": "任务不存在。"})

    if job.status != "completed":
        raise HTTPException(
            status_code=400,
            detail={"error": "NOT_READY", "message": "任务尚未完成，请等待处理完毕后再下载。"},
        )

    zip_path = job.zip_path
    if not zip_path:
        raise HTTPException(status_code=404, detail={"error": "NOT_FOUND", "message": "资料包不存在。"})

    # Path-traversal guard: resolve and ensure inside STORAGE_DIR
    resolved = Path(zip_path).resolve()
    storage_root = Path(settings.STORAGE_DIR).resolve()
    if not str(resolved).startswith(str(storage_root)):
        raise HTTPException(status_code=403, detail={"error": "FORBIDDEN", "message": "禁止访问该路径。"})

    if not resolved.exists():
        raise HTTPException(status_code=404, detail={"error": "NOT_FOUND", "message": "资料包文件已被清理，请重新创建任务。"})

    filename = os.path.basename(zip_path)
    return FileResponse(
        path=str(resolved),
        media_type="application/zip",
        filename=filename,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )

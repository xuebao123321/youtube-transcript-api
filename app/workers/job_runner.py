"""Background task runner – orchestrates the full collect → subtitle → export pipeline."""

from __future__ import annotations

import asyncio
import json
import logging
import traceback
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select

from app.config import settings
from app.models.job import Job
from app.models.video import Video
from app.services.multi_source_extractor import MultiSourceExtractor
from app.services.youtube_extractor import ExtractionError
from app.services.subtitle_service import SubtitleService
from app.services.transcript_converter import TranscriptConverter
from app.services.export_service import ExportService
from app.utils.filenames import generate_transcript_filename

logger = logging.getLogger(__name__)

STATUS_MESSAGES = {
    "pending": "等待处理",
    "fetching_videos": "正在获取视频列表",
    "downloading_subtitles": "正在下载字幕",
    "converting": "正在转换逐字稿",
    "packing": "正在打包资料",
    "completed": "已完成",
    "failed": "任务失败",
    "cancelled": "已取消",
}


class JobRunner:
    """Orchestrates a single job from creation to ZIP delivery."""

    def __init__(self, session_factory):
        self._session_factory = session_factory
        self._extractor = MultiSourceExtractor()
        self._subtitle_service = SubtitleService(settings.STORAGE_DIR)
        self._converter = TranscriptConverter()
        self._exporter = ExportService()

    # ------------------------------------------------------------------
    async def run_job(self, job_id: str) -> None:
        """Main execution flow. Wrapped in try/except so individual errors
        never crash the server; the job is marked *failed* instead."""
        try:
            await self._execute(job_id)
        except Exception:
            logger.exception("Job %s failed with unexpected error", job_id)
            await self._update_job(job_id, status="failed", error_message=traceback.format_exc())

    # ------------------------------------------------------------------
    async def _execute(self, job_id: str) -> None:
        job = await self._get_job(job_id)
        if not job:
            return

        # 1. Fetch video list --------------------------------------------------
        await self._update_job(job_id, status="fetching_videos")
        try:
            videos_raw = await self._extractor.extract_video_list(
                job.source_url,
                job.source_type,
                job.max_videos or 5,
            )
        except ExtractionError as exc:
            await self._update_job(job_id, status="failed", error_message=str(exc))
            return

        if not videos_raw:
            await self._update_job(
                job_id, status="failed",
                error_message="无法提取视频列表。可能触发了 YouTube 的反爬机制，请在 Render 等服务器环境上重试，或稍后再试。"
            )
            return

        # Write video rows
        video_records = []
        for v in videos_raw:
            video_records.append(
                Video(
                    job_id=job_id,
                    video_id=v["video_id"],
                    title=v["title"],
                    url=v["url"],
                    channel=v["channel"],
                    channel_url=v["channel_url"],
                    upload_date=v["upload_date"],
                    duration=v["duration"],
                    description=v.get("description", ""),
                    thumbnail=v.get("thumbnail", ""),
                    status="pending",
                )
            )
        await self._bulk_insert(video_records)
        total = len(video_records)
        await self._update_job(job_id, total_videos=total)

        # Parse job config
        languages = self._parse_json_array(job.languages, ["en"])
        subtitle_mode = job.subtitle_mode or "manual_and_auto"

        # 2. Download subtitles ------------------------------------------------
        await self._update_job(job_id, status="downloading_subtitles")
        processed = 0
        success = 0
        no_sub = 0
        failed = 0

        # Re-fetch video rows to get their DB ids
        video_objs = await self._get_videos(job_id)

        for v_obj in video_objs:
            await self._update_video(v_obj.id, status="processing")
            try:
                sub_result = await self._subtitle_service.fetch_subtitles(
                    v_obj.video_id,
                    languages,
                    subtitle_mode,
                )
            except Exception as exc:
                logger.warning("Subtitle fetch error for %s: %s", v_obj.video_id, exc)
                sub_result = {"status": "none", "languages": [], "transcripts": []}

            if sub_result["status"] == "none":
                await self._update_video(
                    v_obj.id,
                    status="no_subtitle",
                    subtitle_status="none",
                    subtitle_languages="[]",
                    transcript_source="none",
                )
                no_sub += 1
            else:
                # Convert and save transcripts
                job_dir = Path(settings.STORAGE_DIR) / "jobs" / job_id
                transcripts_dir = job_dir / "transcripts"
                transcripts_dir.mkdir(parents=True, exist_ok=True)

                langs_list: list[str] = []
                transcript_path = ""
                vtt_path = ""
                source = sub_result["status"]

                for t in sub_result["transcripts"]:
                    lang = t["language"]
                    langs_list.append(lang)

                    filename = generate_transcript_filename(
                        upload_date=v_obj.upload_date or "00000000",
                        video_id=v_obj.video_id,
                        title=v_obj.title or "untitled",
                        lang=lang,
                        ext="txt",
                    )
                    txt_path = transcripts_dir / filename

                    meta = {
                        "title": v_obj.title or "",
                        "channel": v_obj.channel or "",
                        "url": v_obj.url or "",
                        "date": v_obj.upload_date or "",
                        "duration": str(v_obj.duration or 0),
                        "language": lang,
                        "source": source,
                    }

                    if t.get("vtt_path"):
                        # VTT downloaded by yt-dlp
                        self._converter.convert_vtt_to_txt(t["vtt_path"], txt_path, meta)
                        vtt_path = t["vtt_path"]
                    else:
                        # Raw text from youtube-transcript-api
                        self._converter.convert_text_to_txt(t["text"], txt_path, meta)

                    transcript_path = str(txt_path)

                await self._update_video(
                    v_obj.id,
                    status="completed",
                    subtitle_status=source,
                    subtitle_languages=json.dumps(langs_list),
                    transcript_source=source,
                    transcript_path=transcript_path,
                    vtt_path=vtt_path,
                )
                success += 1

            processed += 1

            # Persist counters each video so the front-end sees real-time progress
            await self._update_job(
                job_id,
                processed_videos=processed,
                success_count=success,
                no_subtitle_count=no_sub,
                failed_count=failed,
            )

            # Rate-limit between videos
            await asyncio.sleep(1.5)

        # 3. Pack ---------------------------------------------------------------
        await self._update_job(job_id, status="packing")

        # Collect final video data for export
        final_videos = await self._get_videos(job_id)
        video_dicts = [self._video_to_dict(v) for v in final_videos]

        job_info = {
            "job_id": job_id,
            "source_url": job.source_url,
            "source_type": job.source_type,
            "created_at": job.created_at,
        }

        job_dir = Path(settings.STORAGE_DIR) / "jobs" / job_id
        zip_path = await asyncio.to_thread(
            self._exporter.build_export_package,
            job_id,
            str(job_dir),
            video_dicts,
            job_info,
        )

        # 4. Complete -----------------------------------------------------------
        await self._update_job(job_id, status="completed", zip_path=zip_path)
        logger.info("Job %s completed – ZIP: %s", job_id, zip_path)

    # ------------------------------------------------------------------
    # DB helpers
    # ------------------------------------------------------------------
    async def _get_job(self, job_id: str) -> Job | None:
        async with self._session_factory() as db:
            result = await db.execute(select(Job).where(Job.id == job_id))
            return result.scalar_one_or_none()

    async def _get_videos(self, job_id: str) -> list[Video]:
        async with self._session_factory() as db:
            result = await db.execute(
                select(Video).where(Video.job_id == job_id).order_by(Video.created_at)
            )
            return list(result.scalars().all())

    async def _update_job(self, job_id: str, **kwargs) -> None:
        kwargs["updated_at"] = datetime.now(timezone.utc).isoformat()
        async with self._session_factory() as db:
            result = await db.execute(select(Job).where(Job.id == job_id))
            job = result.scalar_one_or_none()
            if job:
                for k, v in kwargs.items():
                    setattr(job, k, v)
                await db.commit()

    async def _update_video(self, video_db_id: str, **kwargs) -> None:
        kwargs["updated_at"] = datetime.now(timezone.utc).isoformat()
        async with self._session_factory() as db:
            result = await db.execute(select(Video).where(Video.id == video_db_id))
            video = result.scalar_one_or_none()
            if video:
                for k, v in kwargs.items():
                    setattr(video, k, v)
                await db.commit()

    async def _bulk_insert(self, records: list[Video]) -> None:
        async with self._session_factory() as db:
            db.add_all(records)
            await db.commit()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _parse_json_array(raw: str | None, default: list[str]) -> list[str]:
        if not raw:
            return default
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, list) else default
        except (json.JSONDecodeError, TypeError):
            return default

    @staticmethod
    def _video_to_dict(v: Video) -> dict:
        langs = JobRunner._parse_json_array(v.subtitle_languages, [])
        return {
            "video_id": v.video_id,
            "title": v.title or "",
            "url": v.url or "",
            "channel": v.channel or "",
            "upload_date": v.upload_date or "",
            "duration": v.duration or 0,
            "subtitle_status": v.subtitle_status or "",
            "subtitle_languages": langs,
            "transcript_source": v.transcript_source or "",
            "transcript_path": v.transcript_path or "",
            "vtt_path": v.vtt_path or "",
            "error_message": v.error_message or "",
        }

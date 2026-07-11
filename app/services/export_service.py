"""Export metadata files and package everything into a ZIP archive."""

from __future__ import annotations

import csv
import json
import logging
import os
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

_METADATA_COLUMNS = [
    "job_id",
    "video_id",
    "title",
    "url",
    "channel",
    "upload_date",
    "duration",
    "subtitle_status",
    "subtitle_languages",
    "transcript_source",
    "transcript_file",
    "vtt_file",
    "error_message",
]


class ExportService:
    """Generates metadata files and the final deliverable ZIP."""

    def generate_metadata_csv(self, videos: list[dict], output_path: str | Path) -> None:
        """Write a UTF-8 CSV with BOM (Excel-compatible)."""
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        df = pd.DataFrame(videos, columns=_METADATA_COLUMNS)
        df.to_csv(output_path, index=False, encoding="utf-8-sig")
        logger.info("CSV written: %s (%d rows)", output_path, len(videos))

    def generate_metadata_json(
        self, videos: list[dict], job_info: dict, output_path: str | Path
    ) -> None:
        """Write a pretty-printed JSON metadata file."""
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        payload = {
            "job_id": job_info.get("job_id", ""),
            "source_url": job_info.get("source_url", ""),
            "source_type": job_info.get("source_type", ""),
            "created_at": job_info.get("created_at", ""),
            "total_videos": len(videos),
            "videos": videos,
        }
        output_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        logger.info("JSON written: %s", output_path)

    def generate_index_md(
        self, videos: list[dict], job_info: dict, output_path: str | Path
    ) -> None:
        """Write a Markdown index summarising the collection."""
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        success = sum(1 for v in videos if v.get("subtitle_status") not in ("none", "failed"))
        no_sub = sum(1 for v in videos if v.get("subtitle_status") == "none")
        failed = sum(1 for v in videos if v.get("subtitle_status") == "failed")

        lines = [
            "# YouTube 素材采集结果",
            "",
            f"Source URL: {job_info.get('source_url', '')}",
            f"Job ID: {job_info.get('job_id', '')}",
            f"Created At: {job_info.get('created_at', '')}",
            f"Total Videos: {len(videos)}  |  Success: {success}  |  No Subtitle: {no_sub}  |  Failed: {failed}",
            "",
            "## Videos",
            "",
            "| Date | Title | Language | Source | URL |",
            "| --- | --- | --- | --- | --- |",
        ]

        for v in videos:
            date = v.get("upload_date", "") or ""
            title = (v.get("title") or "").replace("|", "\\|")
            langs = ", ".join(v.get("subtitle_languages") or [])
            source = v.get("transcript_source") or ""
            url = v.get("url") or ""
            lines.append(f"| {date} | {title} | {langs} | {source} | {url} |")

        output_path.write_text("\n".join(lines), encoding="utf-8")
        logger.info("Index.md written: %s", output_path)

    def create_zip_package(self, job_dir: str | Path, output_zip_path: str | Path) -> None:
        """Zip *job_dir* so that the archive root is ``youtube_materials/``."""
        job_dir = Path(job_dir).resolve()
        output_zip_path = Path(output_zip_path).resolve()
        output_zip_path.parent.mkdir(parents=True, exist_ok=True)

        with zipfile.ZipFile(output_zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for file_path in job_dir.rglob("*"):
                if file_path.is_dir():
                    continue
                if file_path.name == ".gitkeep":
                    continue
                # Archive path relative to job_dir, prefixed with youtube_materials/
                arcname = Path("youtube_materials") / file_path.relative_to(job_dir)
                zf.write(file_path, str(arcname))

        logger.info("ZIP created: %s", output_zip_path)

    def build_export_package(
        self,
        job_id: str,
        job_dir: str | Path,
        videos: list[dict],
        job_info: dict,
    ) -> str:
        """Run the full export pipeline for a completed job.

        1. metadata.csv
        2. metadata.json
        3. index.md
        4. no_subtitle_videos.csv (if any)
        5. youtube_materials_{job_id}.zip

        Returns the absolute path to the ZIP file.
        """
        job_dir = Path(job_dir)
        job_dir.mkdir(parents=True, exist_ok=True)
        (job_dir / "transcripts").mkdir(parents=True, exist_ok=True)
        (job_dir / "no_subtitles").mkdir(parents=True, exist_ok=True)

        # Per-video metadata rows for CSV
        rows = []
        for v in videos:
            transcript_file = ""
            if v.get("transcript_path"):
                transcript_file = os.path.basename(v["transcript_path"])
            vtt_file = ""
            if v.get("vtt_path"):
                vtt_file = os.path.basename(v["vtt_path"])
            rows.append({
                "job_id": job_id,
                "video_id": v.get("video_id", ""),
                "title": v.get("title", ""),
                "url": v.get("url", ""),
                "channel": v.get("channel", ""),
                "upload_date": v.get("upload_date", ""),
                "duration": v.get("duration", 0),
                "subtitle_status": v.get("subtitle_status", ""),
                "subtitle_languages": ", ".join(v.get("subtitle_languages") or []),
                "transcript_source": v.get("transcript_source", ""),
                "transcript_file": transcript_file,
                "vtt_file": vtt_file,
                "error_message": v.get("error_message", ""),
            })

        # 1. metadata.csv
        self.generate_metadata_csv(rows, job_dir / "metadata.csv")

        # 2. metadata.json
        self.generate_metadata_json(rows, job_info, job_dir / "metadata.json")

        # 3. index.md
        self.generate_index_md(rows, job_info, job_dir / "index.md")

        # 4. no_subtitle_videos.csv
        no_sub = [r for r in rows if r["subtitle_status"] == "none"]
        if no_sub:
            pd.DataFrame(no_sub).to_csv(
                job_dir / "no_subtitles" / "no_subtitle_videos.csv",
                index=False,
                encoding="utf-8-sig",
            )

        # 5. ZIP
        zip_path = job_dir / f"youtube_materials_{job_id}.zip"
        self.create_zip_package(job_dir, zip_path)

        return str(zip_path.resolve())

"""Subtitle fetching via youtube-transcript-api with yt-dlp fallback."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import NoTranscriptFound, TranscriptsDisabled

from yt_dlp import YoutubeDL

logger = logging.getLogger(__name__)


class SubtitleService:
    """Fetch subtitles / transcripts for a YouTube video.

    Strategy (priority):
        1. youtube-transcript-api  (fast, no filesystem overhead)
        2. yt-dlp subtitle download (fallback, writes VTT to disk)
    """

    def __init__(self, storage_dir: str):
        self._storage_dir = Path(storage_dir)

    # ------------------------------------------------------------------
    def fetch_subtitles(
        self,
        video_id: str,
        languages: list[str],
        subtitle_mode: str,
    ) -> dict:
        """Fetch subtitles for *video_id* and return a unified result dict.

        Returns:
            {
                "status": "manual" | "auto" | "mixed" | "none",
                "languages": ["en"],
                "transcripts": [
                    {"language": "en", "source": "manual", "text": "...", "vtt_path": None},
                ]
            }
        """
        result = self._try_transcript_api(video_id, languages, subtitle_mode)
        if result["status"] != "none":
            return result

        # Fallback: yt-dlp
        logger.info("Transcript API returned nothing for %s, trying yt-dlp", video_id)
        ytdlp_result = self._try_ytdlp(video_id, languages, subtitle_mode)
        return ytdlp_result if ytdlp_result["status"] != "none" else result

    # ------------------------------------------------------------------
    # youtube-transcript-api path
    # ------------------------------------------------------------------
    def _try_transcript_api(
        self, video_id: str, languages: list[str], subtitle_mode: str
    ) -> dict:
        try:
            transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
        except (NoTranscriptFound, TranscriptsDisabled, Exception) as exc:
            logger.debug("Transcript API unavailable for %s: %s", video_id, exc)
            return {"status": "none", "languages": [], "transcripts": []}

        transcripts: list[dict] = []
        found_languages: set[str] = set()
        has_manual = False
        has_auto = False

        want_all_langs = "all" in languages

        for t in transcript_list:
            lang = t.language_code

            # Language filter
            if not want_all_langs and lang not in languages:
                continue

            is_manual = not getattr(t, "is_generated", False)

            # Subtitle-mode filter
            if subtitle_mode == "manual" and not is_manual:
                continue
            if subtitle_mode == "auto" and is_manual:
                continue

            try:
                fetched = t.fetch()
            except Exception as exc:
                logger.warning("Failed to fetch transcript %s/%s: %s", video_id, lang, exc)
                continue

            text = self._snapshot_to_text(fetched)
            transcripts.append({
                "language": lang,
                "source": "manual" if is_manual else "auto",
                "text": text,
                "vtt_path": None,
            })
            found_languages.add(lang)
            if is_manual:
                has_manual = True
            else:
                has_auto = True

        if not transcripts:
            return {"status": "none", "languages": [], "transcripts": []}

        status = "mixed"
        if has_manual and not has_auto:
            status = "manual"
        elif has_auto and not has_manual:
            status = "auto"

        return {
            "status": status,
            "languages": sorted(found_languages),
            "transcripts": transcripts,
        }

    @staticmethod
    def _snapshot_to_text(snapshot: list) -> str:
        """Convert a list of {'text':..., 'start':..., 'duration':...} into plain text."""
        lines = [item.get("text", "") for item in snapshot]
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # yt-dlp fallback
    # ------------------------------------------------------------------
    def _try_ytdlp(
        self, video_id: str, languages: list[str], subtitle_mode: str
    ) -> dict:
        video_url = f"https://www.youtube.com/watch?v={video_id}"
        lang_list = languages if "all" not in languages else ["en"]

        # Build yt-dlp options
        write_manual = subtitle_mode in ("manual", "manual_and_auto")
        write_auto = subtitle_mode in ("auto", "manual_and_auto")

        ydl_opts = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "writesubtitles": write_manual,
            "writeautosub": write_auto,
            "subtitleslangs": lang_list,
            "subtitlesformat": "vtt",
            "outtmpl": str(self._storage_dir / "%(id)s.%(ext)s"),
            "ignoreerrors": True,
        }

        try:
            with YoutubeDL(ydl_opts) as ydl:
                ydl.extract_info(video_url, download=True)
        except Exception as exc:
            logger.warning("yt-dlp subtitle download failed for %s: %s", video_id, exc)
            return {"status": "none", "languages": [], "transcripts": []}

        # Scan for downloaded .vtt files
        transcripts = []
        found_languages = set()
        has_manual = False
        has_auto = False

        for fpath in self._storage_dir.glob(f"{video_id}*.vtt"):
            # yt-dlp names: <video_id>.<lang>.vtt  or  <video_id>.<lang>.<ext>.vtt
            stem_parts = fpath.stem.split(".")
            lang = stem_parts[1] if len(stem_parts) >= 2 else "en"

            try:
                text = self._vtt_to_text(fpath)
            except Exception as exc:
                logger.warning("Failed to read VTT %s: %s", fpath, exc)
                continue

            # yt-dlp manual sub has suffix like .en.vtt, auto sub like .en.auto.vtt
            # but we cannot distinguish reliably from file names alone; mark as auto for safety
            source = "auto"

            transcripts.append({
                "language": lang,
                "source": source,
                "text": text,
                "vtt_path": str(fpath),
            })
            found_languages.add(lang)
            has_auto = True  # fallback always marks as auto

        if not transcripts:
            return {"status": "none", "languages": [], "transcripts": []}

        status = "auto" if has_auto and not has_manual else "manual"
        return {
            "status": status,
            "languages": sorted(found_languages),
            "transcripts": transcripts,
        }

    @staticmethod
    def _vtt_to_text(vtt_path: Path) -> str:
        """Quickly extract plain text from a VTT file without the full webvtt parser."""
        lines = []
        in_header = True
        with open(vtt_path, "r", encoding="utf-8") as fh:
            for raw in fh:
                line = raw.strip()
                if not line or line.startswith("WEBVTT") or line.startswith("NOTE"):
                    continue
                if "-->" in line:
                    in_header = False
                    continue
                if in_header:
                    continue
                # Skip HTML-style tags
                if line.startswith("<") and line.endswith(">"):
                    continue
                # Remove inline tags like <c>...</c>
                import re
                cleaned = re.sub(r"<[^>]+>", "", line).strip()
                if cleaned:
                    lines.append(cleaned)
        return "\n".join(lines)

"""Invidious API wrapper – free, no-auth YouTube metadata & captions.

Uses multiple public Invidious instances with automatic failover.
All methods return empty results on failure (never raise) so callers
can fall back to the next strategy.
"""

from __future__ import annotations

import logging
import re
import time
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlparse

import aiohttp

logger = logging.getLogger(__name__)

# Public Invidious instances (tried in order; first that responds is used)
_INSTANCES = [
    "https://invidious.tiekoetter.com",
    "https://inv.nadeko.net",
    "https://yewtu.be",
    "https://vid.puffyan.us",
    "https://invidious.privacyredirect.com",
]

_REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=12)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class InvidiousService:
    """Fetch YouTube video info, channel/playlist listings, and captions
    through the Invidious public API."""

    def __init__(self):
        self._instances: list[str] = list(_INSTANCES)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def fetch_video_info(self, video_id: str) -> Optional[dict]:
        """Return video metadata dict (same shape as YouTubeExtractor) or None."""
        # Try Piped first (usually better uptime)
        result = await self._piped_video_info(video_id)
        if result:
            return result
        # Fall back to Invidious
        data = await self._call_invidious(f"/api/v1/videos/{video_id}")
        if not data:
            return None
        return self._parse_invidious_video(data, video_id)

    async def fetch_channel_videos(
        self, channel_id: str, max_videos: int
    ) -> Optional[list[dict]]:
        """Return a list of video dicts for an Invidious channel (UC... ID)."""
        data = await self._call_invidious(f"/api/v1/channels/{channel_id}/videos")
        if not data:
            return None
        entries = data.get("videos") or []
        videos = []
        for entry in entries:
            if len(videos) >= max_videos:
                break
            videos.append(self._parse_channel_entry(entry))
        return videos if videos else None

    async def fetch_playlist_videos(
        self, playlist_id: str, max_videos: int
    ) -> Optional[list[dict]]:
        """Return a list of video dicts for a playlist."""
        data = await self._call_invidious(f"/api/v1/playlists/{playlist_id}")
        if not data:
            return None
        entries = data.get("videos") or []
        videos = []
        for entry in entries:
            if len(videos) >= max_videos:
                break
            videos.append(self._parse_channel_entry(entry))
        return videos if videos else None

    async def resolve_channel_handle(self, handle: str) -> Optional[str]:
        """Resolve @handle to a UC... channel ID via search."""
        query = handle.lstrip("@")
        data = await self._call_invidious(f"/api/v1/search?q={query}&type=channel")
        if not data:
            return None
        results = data if isinstance(data, list) else data.get("results", data)
        results = results if isinstance(results, list) else []
        for item in results:
            # Match on authorId (UC...) with author matching handle
            author_id = item.get("authorId") or ""
            author = (item.get("author") or "").lower()
            if author_id.startswith("UC") and query.lower() in author:
                return author_id
        return None

    async def fetch_captions(
        self, video_id: str, languages: list[str]
    ) -> Optional[list[dict]]:
        """Return subtitles for *video_id*.

        Returns list of {"language", "source", "text", "vtt_path": None} dicts,
        or None if no captions available.
        """
        # Try Piped first
        result = await self._piped_captions(video_id, languages)
        if result:
            return result

        # Fall back to Invidious
        cap_data = await self._call_invidious(f"/api/v1/captions/{video_id}")
        if not cap_data:
            return None

        captions = cap_data.get("captions") or []
        want_all = "all" in languages
        results = []

        for cap in captions:
            lang_code = cap.get("languageCode") or cap.get("language_code") or ""
            if not want_all and lang_code not in languages:
                continue

            caption_url = cap.get("url") or ""
            if not caption_url:
                continue

            text = await self._fetch_caption_text(caption_url)
            if text:
                results.append({
                    "language": lang_code,
                    "source": "auto",  # Invidious does not distinguish manual vs auto
                    "text": text,
                    "vtt_path": None,
                })

        return results if results else None

    # ------------------------------------------------------------------
    # Piped API (https://docs.piped.video)
    # ------------------------------------------------------------------
    _PIPED_INSTANCES = [
        "https://pipedapi.kavin.rocks",
        "https://pipedapi.tokhmi.xyz",
        "https://pipedapi.moomoo.me",
    ]

    async def _piped_video_info(self, video_id: str) -> Optional[dict]:
        for instance in self._PIPED_INSTANCES:
            data = await self._piped_get(instance, f"/streams/{video_id}")
            if not data:
                continue
            return {
                "video_id": video_id,
                "title": data.get("title") or "",
                "url": f"https://www.youtube.com/watch?v={video_id}",
                "channel": data.get("uploader") or "",
                "channel_url": data.get("uploaderUrl") or "",
                "upload_date": self._fmt_piped_date(data.get("uploadDate")),
                "duration": int(data.get("duration") or 0),
                "description": data.get("description") or "",
                "thumbnail": data.get("thumbnailUrl") or "",
            }
        return None

    async def _piped_captions(
        self, video_id: str, languages: list[str]
    ) -> Optional[list[dict]]:
        want_all = "all" in languages
        for instance in self._PIPED_INSTANCES:
            data = await self._piped_get(instance, f"/streams/{video_id}")
            if not data:
                continue
            subtitles = data.get("subtitles") or []
            results = []
            for sub in subtitles:
                code = sub.get("code") or ""
                if not want_all and code not in languages:
                    continue
                caption_url = sub.get("url") or ""
                if not caption_url:
                    continue
                text = await self._piped_get(instance, caption_url, raw_text=True)
                if text:
                    results.append({
                        "language": code,
                        "source": "auto" if sub.get("autoGenerated") else "manual",
                        "text": text,
                        "vtt_path": None,
                    })
            if results:
                return results
        return None

    async def _piped_get(self, instance: str, path: str, raw_text: bool = False):
        url = f"{instance}{path}"
        try:
            async with aiohttp.ClientSession(timeout=_REQUEST_TIMEOUT) as session:
                async with session.get(url) as resp:
                    if resp.status != 200:
                        return None
                    if raw_text:
                        return await resp.text()
                    return await resp.json()
        except Exception:
            return None

    @staticmethod
    def _fmt_piped_date(upload_date: Optional[str]) -> str:
        if not upload_date:
            return _utc_now()[:10]
        # Piped returns ISO format like "2005-04-23T20:37:03+00:00"
        return upload_date[:10] if len(upload_date) >= 10 else _utc_now()[:10]

    # ------------------------------------------------------------------
    # Invidious helpers
    # ------------------------------------------------------------------
    def _parse_invidious_video(self, data: dict, video_id: str) -> dict:
        return {
            "video_id": data.get("videoId", video_id),
            "title": data.get("title") or "",
            "url": f"https://www.youtube.com/watch?v={video_id}",
            "channel": data.get("author") or "",
            "channel_url": data.get("authorUrl") or "",
            "upload_date": self._fmt_date(data.get("published"), data.get("publishedText")),
            "duration": int(data.get("lengthSeconds") or 0),
            "description": data.get("description") or "",
            "thumbnail": self._best_thumbnail(data.get("videoThumbnails")),
        }

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------

    async def _call_invidious(self, path: str) -> Optional[dict | list]:
        """Try *path* against each Invidious instance until one succeeds."""
        for instance in self._instances:
            url = f"{instance}{path}"
            try:
                async with aiohttp.ClientSession(timeout=_REQUEST_TIMEOUT) as session:
                    async with session.get(url) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            logger.debug("Invidious hit: %s", instance)
                            return data
                        logger.debug("Invidious %s returned %s for %s", instance, resp.status, path)
            except Exception as exc:
                logger.debug("Invidious %s error: %s", instance, exc)
                continue
        logger.warning("All Invidious instances failed for %s", path)
        return None

    async def _fetch_caption_text(self, caption_url: str) -> Optional[str]:
        """Download and parse an SRT / VTT caption file into plain text."""
        for instance in self._instances:
            # Caption URLs from Invidious are often relative to the instance
            if caption_url.startswith("/"):
                url = f"{instance}{caption_url}"
            else:
                url = caption_url

            try:
                async with aiohttp.ClientSession(timeout=_REQUEST_TIMEOUT) as session:
                    async with session.get(url) as resp:
                        if resp.status != 200:
                            continue
                        raw = await resp.text()
            except Exception:
                continue

            return self._parse_srt_to_text(raw)

        return None

    @staticmethod
    def _fmt_date(published: Optional[int], published_text: Optional[str]) -> str:
        """Convert Invidious timestamp or text to YYYY-MM-DD."""
        if published:
            try:
                return datetime.fromtimestamp(published, tz=timezone.utc).strftime("%Y-%m-%d")
            except Exception:
                pass
        if published_text:
            match = re.search(r"(\d{4})-(\d{2})-(\d{2})", str(published_text))
            if match:
                return match.group(0)
            ago = str(published_text).lower()
            if "day" in ago or "month" in ago or "year" in ago or "week" in ago:
                return _utc_now()[:10]
        return _utc_now()[:10]

    @staticmethod
    def _best_thumbnail(thumbnails: Optional[list]) -> str:
        if not thumbnails:
            return ""
        # Prefer medium quality
        for t in thumbnails:
            if t.get("quality") == "medium":
                return t.get("url", "")
        return thumbnails[-1].get("url", "") if thumbnails else ""

    def _parse_channel_entry(self, entry: dict) -> dict:
        video_id = entry.get("videoId") or ""
        return {
            "video_id": video_id,
            "title": entry.get("title") or "",
            "url": f"https://www.youtube.com/watch?v={video_id}",
            "channel": entry.get("author") or "",
            "channel_url": entry.get("authorUrl") or "",
            "upload_date": self._fmt_date(
                entry.get("published"), entry.get("publishedText")
            ),
            "duration": int(entry.get("lengthSeconds") or 0),
            "description": entry.get("description") or "",
            "thumbnail": self._best_thumbnail(entry.get("videoThumbnails")),
        }

    @staticmethod
    def _parse_srt_to_text(raw: str) -> str:
        """Minimal SRT/VTT → plain-text conversion."""
        lines = []
        for line in raw.splitlines():
            line = line.strip()
            # Skip index numbers, timestamps, WEBVTT headers
            if not line:
                continue
            if line.isdigit():
                continue
            if "-->" in line:
                continue
            if line.startswith("WEBVTT") or line.startswith("NOTE"):
                continue
            # Strip HTML tags
            text = re.sub(r"<[^>]+>", "", line).strip()
            if text:
                lines.append(text)
        return "\n".join(lines)

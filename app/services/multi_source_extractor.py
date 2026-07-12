"""Multi-source YouTube extractor: Invidious first, yt-dlp fallback."""

from __future__ import annotations

import asyncio
import logging
import re

from app.services.invidious_service import InvidiousService
from app.services.youtube_extractor import YouTubeExtractor, ExtractionError

logger = logging.getLogger(__name__)


class MultiSourceExtractor:
    """Try Invidious API first (free, no auth), fall back to yt-dlp if it fails."""

    def __init__(self):
        self._invidious = InvidiousService()
        self._ytdlp = YouTubeExtractor()

    async def extract_video_list(
        self, source_url: str, source_type: str, max_videos: int
    ) -> list[dict]:
        """Extract video list, preferring Invidious. Raises ExtractionError if both fail."""
        # 1) Try Invidious
        try:
            result = await self._try_invidious(source_url, source_type, max_videos)
            if result:
                logger.info("Invidious succeeded for %s (%d videos)", source_type, len(result))
                return result
        except Exception as exc:
            logger.warning("Invidious failed for %s: %s", source_type, exc)

        # 2) Fall back to yt-dlp
        logger.info("Falling back to yt-dlp for %s", source_type)
        try:
            return await asyncio.to_thread(
                self._ytdlp.extract_video_list, source_url, source_type, max_videos
            )
        except ExtractionError:
            raise
        except Exception as exc:
            raise ExtractionError(f"视频列表获取失败（Invidious + yt-dlp 均失败）: {exc}") from exc

    # ------------------------------------------------------------------
    async def _try_invidious(
        self, source_url: str, source_type: str, max_videos: int
    ) -> list[dict] | None:
        if source_type == "video":
            video_id = self._extract_video_id(source_url)
            if not video_id:
                return None
            info = await self._invidious.fetch_video_info(video_id)
            return [info] if info else None

        if source_type == "playlist":
            playlist_id = self._extract_playlist_id(source_url)
            if not playlist_id:
                return None
            return await self._invidious.fetch_playlist_videos(playlist_id, max_videos)

        if source_type == "channel":
            # Try direct UC ID first, then @handle resolution
            uc_id = self._extract_uc_id(source_url)
            if uc_id:
                return await self._invidious.fetch_channel_videos(uc_id, max_videos)

            handle = self._extract_handle(source_url)
            if handle:
                uc_id = await self._invidious.resolve_channel_handle(handle)
                if uc_id:
                    return await self._invidious.fetch_channel_videos(uc_id, max_videos)

        return None

    # ------------------------------------------------------------------
    @staticmethod
    def _extract_video_id(url: str) -> str | None:
        m = re.search(r"(?:watch\?v=|youtu\.be/|/shorts/|/live/)([a-zA-Z0-9_-]{11})", url)
        return m.group(1) if m else None

    @staticmethod
    def _extract_playlist_id(url: str) -> str | None:
        m = re.search(r"[?&]list=([a-zA-Z0-9_-]+)", url)
        return m.group(1) if m else None

    @staticmethod
    def _extract_uc_id(url: str) -> str | None:
        m = re.search(r"/channel/(UC[a-zA-Z0-9_-]+)", url)
        return m.group(1) if m else None

    @staticmethod
    def _extract_handle(url: str) -> str | None:
        m = re.search(r"/@([\w.-]+)", url)
        return m.group(1) if m else None

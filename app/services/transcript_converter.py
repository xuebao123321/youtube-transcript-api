"""Convert VTT subtitles to clean TXT files with metadata headers."""

from __future__ import annotations

import logging
import re
from pathlib import Path

import webvtt

logger = logging.getLogger(__name__)

# Patterns for HTML entities and tags
_TAG_RE = re.compile(r"<[^>]+>")
_ENTITY_RE = re.compile(r"&[a-z]+;")


class TranscriptConverter:
    """Converts subtitle files to plain-text transcript files."""

    def convert_vtt_to_txt(self, vtt_path: str | Path, txt_path: str | Path, metadata: dict) -> None:
        """Parse a VTT file, clean it, and write a TXT file with metadata header.

        Args:
            vtt_path: Path to the source .vtt file.
            txt_path: Destination .txt path.
            metadata: Dict with keys title, channel, url, date, duration, language, source.
        """
        vtt_path = Path(vtt_path)
        txt_path = Path(txt_path)
        txt_path.parent.mkdir(parents=True, exist_ok=True)

        lines: list[str] = []
        try:
            for caption in webvtt.read(vtt_path):
                text = self.clean_transcript_text(caption.text)
                if text:
                    lines.append(text)
        except Exception as exc:
            logger.warning("webvtt parse failed for %s: %s", vtt_path, exc)
            # Fallback: simple line-based extraction
            lines = self._simple_vtt_extract(vtt_path)

        cleaned = self._deduplicate_lines(lines)
        self._write_txt(txt_path, metadata, "\n".join(cleaned))

    def convert_text_to_txt(self, text: str, txt_path: str | Path, metadata: dict) -> None:
        """Write already-fetched transcript text into a TXT file with metadata header.

        Args:
            text: The transcript plain-text content.
            txt_path: Destination .txt path.
            metadata: Same structure as convert_vtt_to_txt.
        """
        txt_path = Path(txt_path)
        txt_path.parent.mkdir(parents=True, exist_ok=True)

        cleaned = self.clean_transcript_text(text)
        self._write_txt(txt_path, metadata, cleaned)

    def save_vtt_file(self, raw_content: str, vtt_path: str | Path) -> None:
        """Persist raw VTT content to disk."""
        vtt_path = Path(vtt_path)
        vtt_path.parent.mkdir(parents=True, exist_ok=True)
        vtt_path.write_text(raw_content, encoding="utf-8")
        logger.debug("Saved VTT: %s", vtt_path)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def clean_transcript_text(text: str) -> str:
        """Remove HTML tags and entities, collapse whitespace."""
        text = _TAG_RE.sub("", text)
        # Common YouTube VTT entities
        text = text.replace("&amp;", "&")
        text = text.replace("&lt;", "<")
        text = text.replace("&gt;", ">")
        text = text.replace("&quot;", '"')
        text = text.replace("&#39;", "'")
        # Collapse blank lines (max 1 consecutive blank line)
        lines = [ln.strip() for ln in text.splitlines()]
        cleaned = []
        prev_blank = False
        for ln in lines:
            if not ln:
                if not prev_blank:
                    cleaned.append("")
                prev_blank = True
            else:
                cleaned.append(ln)
                prev_blank = False
        return "\n".join(cleaned).strip()

    @staticmethod
    def _deduplicate_lines(lines: list[str]) -> list[str]:
        """Remove consecutive duplicate lines."""
        result = []
        prev = None
        for line in lines:
            if line != prev:
                result.append(line)
            prev = line
        return result

    @staticmethod
    def _simple_vtt_extract(vtt_path: Path) -> list[str]:
        """Line-based VTT extraction (fallback if webvtt fails)."""
        lines = []
        in_text = False
        with open(vtt_path, encoding="utf-8") as fh:
            for raw in fh:
                line = raw.strip()
                if not line or line.startswith("WEBVTT") or line.startswith("NOTE"):
                    continue
                if "-->" in line:
                    in_text = True
                    continue
                if in_text and not (line.startswith("<") and line.endswith(">")):
                    cleaned = _TAG_RE.sub("", line).strip()
                    if cleaned:
                        lines.append(cleaned)
        return lines

    @staticmethod
    def _write_txt(txt_path: Path, metadata: dict, body: str) -> None:
        """Write a transcript TXT file with the standard header block."""
        header = (
            f"Title: {metadata.get('title', '')}\n"
            f"Channel: {metadata.get('channel', '')}\n"
            f"URL: {metadata.get('url', '')}\n"
            f"Published Date: {metadata.get('date', '')}\n"
            f"Duration: {metadata.get('duration', '')}\n"
            f"Language: {metadata.get('language', '')}\n"
            f"Transcript Source: {metadata.get('source', '')}\n"
            f"\nTranscript:\n"
        )
        txt_path.write_text(header + body, encoding="utf-8")
        logger.debug("Wrote transcript: %s", txt_path)

"""YouTube URL validation and normalization."""

import re


# Allowed YouTube hostnames
_ALLOWED_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"}


def validate_youtube_url(url: str) -> tuple[str, str]:
    """Validate a YouTube URL and return (source_type, normalized_url).

    source_type is one of: channel, playlist, video, unknown.
    """
    url = url.strip()

    # youtu.be short links
    short_match = re.match(r"^https?://youtu\.be/([a-zA-Z0-9_-]{11})", url)
    if short_match:
        video_id = short_match.group(1)
        return ("video", f"https://www.youtube.com/watch?v={video_id}")

    # Extract hostname
    host_match = re.match(r"^https?://([^/]+)", url)
    if not host_match:
        return ("unknown", url)

    host = host_match.group(1).lower()
    if host not in _ALLOWED_HOSTS:
        return ("unknown", url)

    # Channel: @handle or /channel/UC... or /c/...
    if re.search(r"/(@[\w.-]+)", url) or re.search(r"/(channel|c)/([\w-]+)", url):
        # Ensure /videos suffix for channel URLs
        if not url.rstrip("/").endswith("/videos"):
            url = url.rstrip("/") + "/videos"
        return ("channel", url)

    # Playlist
    if "playlist?list=" in url or "&list=" in url:
        return ("playlist", url)

    # Single video
    if "watch?v=" in url or "/shorts/" in url or "/live/" in url:
        return ("video", url)

    return ("unknown", url)

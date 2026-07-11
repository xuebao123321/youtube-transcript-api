"""Safe filename generation for transcripts and exports."""

from slugify import slugify


def sanitize_filename(title: str, max_length: int = 80) -> str:
    """Convert a video title into a safe filesystem name.

    Lowercases, replaces spaces with hyphens, removes special characters,
    and truncates to *max_length* characters.
    """
    if not title:
        return "untitled"
    slug = slugify(title, lowercase=True, max_length=max_length)
    return slug or "untitled"


def generate_transcript_filename(
    upload_date: str,
    video_id: str,
    title: str,
    lang: str,
    ext: str,
) -> str:
    """Build a transcript filename following the project naming convention.

    Format: {upload_date}_{video_id}_{safe_title}_{lang}.{ext}
    """
    safe_title = sanitize_filename(title)
    date_str = upload_date.replace("-", "") if upload_date else "00000000"
    return f"{date_str}_{video_id}_{safe_title}_{lang}.{ext}"

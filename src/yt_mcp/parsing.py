"""Pure helpers: reference parsing, date filters, durations, timestamps, links."""

import re
from datetime import UTC, datetime, timedelta

from yt_mcp.errors import InvalidDateError

_CHANNEL_ID_RE = re.compile(r"^UC[\w-]{22}$")
_VIDEO_ID_RE = re.compile(r"^[\w-]{11}$")
_HANDLE_RE = re.compile(r"^@[\w.-]+$")

_CHANNEL_URL_RES = (
    ("id", re.compile(r"youtube\.com/channel/(UC[\w-]{22})", re.IGNORECASE)),
    ("handle", re.compile(r"youtube\.com/(@[\w.-]+)", re.IGNORECASE)),
    ("username", re.compile(r"youtube\.com/(?:c|user)/([\w.-]+)", re.IGNORECASE)),
)

_VIDEO_URL_RES = (
    re.compile(r"[?&]v=([\w-]{11})"),
    re.compile(r"youtu\.be/([\w-]{11})"),
    re.compile(r"youtube\.com/(?:shorts|embed|live|v)/([\w-]{11})", re.IGNORECASE),
)

_DURATION_RE = re.compile(
    r"^P(?:(?P<days>\d+)D)?T?(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?"
    r"(?:(?P<seconds>\d+)S)?$",
)

_RELATIVE_RE = re.compile(r"^(\d+)\s*(h|d|w|m|y)$", re.IGNORECASE)
_RELATIVE_UNITS = {"h": 1 / 24, "d": 1.0, "w": 7.0, "m": 30.0, "y": 365.0}

_URL_RE = re.compile(r"https?://[^\s<>\"')\]]+")
_TRAILING_PUNCTUATION = ".,;:!?"


def _parse_channel_url(value: str) -> tuple[str, str] | None:
    """Classify a channel reference that looks like a YouTube URL.

    Args:
        value: The stripped reference.

    Returns:
        A ``(kind, value)`` pair, or ``None`` when the reference is not a
        recognisable channel URL.
    """
    if "youtube.com/" not in value.lower():
        return None
    for kind, pattern in _CHANNEL_URL_RES:
        match = pattern.search(value)
        if match:
            return kind, match.group(1).lstrip("@")
    return None


def parse_channel_reference(reference: str) -> tuple[str, str]:
    """Classify a channel reference.

    Args:
        reference: A channel id, ``@handle``, channel URL, legacy ``/c/`` or
            ``/user/`` path, or a free-text channel name.

    Returns:
        A ``(kind, value)`` pair where kind is one of ``id``, ``handle``,
        ``username`` or ``search``.
    """
    value = reference.strip()
    if _CHANNEL_ID_RE.match(value):
        return "id", value
    if _HANDLE_RE.match(value):
        return "handle", value.lstrip("@")
    return _parse_channel_url(value) or ("search", value)


def parse_video_id(reference: str) -> str | None:
    """Extract a video id from an id or any YouTube video URL.

    Args:
        reference: A bare video id or a watch/youtu.be/shorts/embed URL.

    Returns:
        The 11-character video id, or ``None`` if none could be extracted.
    """
    value = reference.strip()
    if _VIDEO_ID_RE.match(value) and "/" not in value:
        return value
    for pattern in _VIDEO_URL_RES:
        match = pattern.search(value)
        if match:
            return match.group(1)
    return None


def parse_date_filter(value: str) -> datetime:
    """Parse a date filter into an aware UTC datetime.

    Accepts a relative offset (``24h``, ``7d``, ``3w``, ``6m``, ``1y`` — months
    and years are approximated as 30 and 365 days), a plain date
    (``2025-01-31``), or an RFC 3339 timestamp.

    Args:
        value: The filter expression.

    Returns:
        The resolved instant, in UTC.

    Raises:
        InvalidDateError: If the expression is not understood.
    """
    text = value.strip()

    relative = _RELATIVE_RE.match(text)
    if relative:
        amount = int(relative.group(1))
        days = amount * _RELATIVE_UNITS[relative.group(2).lower()]
        return datetime.now(UTC) - timedelta(days=days)

    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        raise InvalidDateError(value) from None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def to_rfc3339(moment: datetime) -> str:
    """Render a datetime the way the YouTube Data API expects it.

    Args:
        moment: Any datetime; naive values are treated as UTC.

    Returns:
        An RFC 3339 timestamp ending in ``Z``.
    """
    aware = moment if moment.tzinfo else moment.replace(tzinfo=UTC)
    return aware.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_api_timestamp(value: str | None) -> datetime | None:
    """Parse a timestamp returned by the YouTube Data API.

    Args:
        value: An RFC 3339 string, or ``None``.

    Returns:
        The parsed instant in UTC, or ``None`` when the input is missing or
        malformed.
    """
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def parse_iso_duration(value: str | None) -> int | None:
    """Convert an ISO 8601 duration (``PT12M34S``) to whole seconds.

    Args:
        value: The duration string from ``videos.contentDetails.duration``.

    Returns:
        The duration in seconds, or ``None`` for missing or live-stream values.
    """
    if not value:
        return None
    match = _DURATION_RE.match(value)
    if not match:
        return None
    parts = {key: int(raw) for key, raw in match.groupdict(default="0").items()}
    return (
        parts["days"] * 86400
        + parts["hours"] * 3600
        + parts["minutes"] * 60
        + parts["seconds"]
    )


def format_timestamp(seconds: float) -> str:
    """Format a position in a video as ``MM:SS`` or ``H:MM:SS``.

    Args:
        seconds: Offset from the start of the video.

    Returns:
        The formatted timestamp.
    """
    total = max(0, int(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def format_duration(seconds: int | None) -> str | None:
    """Render a video duration for display.

    Args:
        seconds: Duration in seconds, or ``None``.

    Returns:
        The formatted duration, or ``None`` when the input is ``None``.
    """
    return None if seconds is None else format_timestamp(seconds)


def extract_links(text: str) -> list[str]:
    """Pull the unique http(s) links out of a video description.

    Args:
        text: The description body.

    Returns:
        Links in the order they appear, with trailing sentence punctuation
        stripped and duplicates removed.
    """
    seen: dict[str, None] = {}
    for raw in _URL_RE.findall(text or ""):
        link = raw.rstrip(_TRAILING_PUNCTUATION)
        seen.setdefault(link, None)
    return list(seen)


def watch_url(video_id: str) -> str:
    """Build the canonical watch URL for a video id.

    Args:
        video_id: The 11-character video id.

    Returns:
        The full watch URL.
    """
    return f"https://www.youtube.com/watch?v={video_id}"


def timestamp_url(video_id: str, seconds: float) -> str:
    """Build a watch URL that starts playback at an offset.

    Args:
        video_id: The 11-character video id.
        seconds: Offset from the start of the video; negatives clamp to zero.

    Returns:
        The watch URL with YouTube's ``t`` parameter, in whole seconds.
    """
    return f"{watch_url(video_id)}&t={max(0, int(seconds))}"


def format_timestamp_link(video_id: str, seconds: float) -> str:
    """Render a position in a video as a Markdown link that seeks to it.

    The timestamp keeps its square brackets inside the link text, so it still
    reads as ``[MM:SS]`` once rendered and stays quotable as a citation.

    Args:
        video_id: The 11-character video id.
        seconds: Offset from the start of the video.

    Returns:
        A Markdown link such as ``[[03:15]](https://...&t=195)``.
    """
    return f"[[{format_timestamp(seconds)}]]({timestamp_url(video_id, seconds)})"

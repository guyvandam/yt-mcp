"""Transcript retrieval.

The YouTube Data API only serves caption tracks to the channel owner via OAuth,
so transcripts come from ``youtube-transcript-api``, which reads the same public
caption tracks the web player uses. No API key or quota is involved.

Because those requests look like a player rather than an API client, YouTube
judges them by IP: residential addresses are served, and the cloud ranges a
deployment runs in are blocked. A proxy is therefore optional locally and
required in deployment — see :func:`yt_mcp.config.proxy_config`.
"""

from functools import partial
from typing import Any

from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import CouldNotRetrieveTranscript, RequestBlocked

from yt_mcp.config import (
    PROXY_URL_ENV,
    WEBSHARE_USERNAME_ENV,
    proxy_config,
)
from yt_mcp.errors import (
    TranscriptBlockedError,
    TranscriptUnavailableError,
    VideoNotFoundError,
)
from yt_mcp.models import Transcript
from yt_mcp.parsing import format_timestamp_link, parse_video_id, watch_url

DEFAULT_CHUNK_SECONDS = 30.0
"""Default window that raw caption cues are merged into, to keep output compact."""


def _api() -> YouTubeTranscriptApi:
    """Build a caption client bound to the configured proxy, if any.

    Returns:
        The client. The transcript handles it hands out keep its session, so the
        later ``fetch()`` goes through the same proxy as the listing.
    """
    return YouTubeTranscriptApi(proxy_config=proxy_config())


def _blocked(video_id: str) -> TranscriptBlockedError:
    """Build the error for a caption request YouTube refused by IP.

    Args:
        video_id: The video whose captions were refused.

    Returns:
        The error, naming the proxy environment variables that fix it.
    """
    return TranscriptBlockedError(video_id, PROXY_URL_ENV, WEBSHARE_USERNAME_ENV)


def get_transcript(
    reference: str,
    *,
    languages: list[str] | None,
    chunk_seconds: float,
    start_seconds: float | None,
    end_seconds: float | None,
) -> Transcript:
    """Fetch a video's transcript as timestamped lines.

    Args:
        reference: A video id or any YouTube video URL.
        languages: Preferred language codes in priority order; when none match,
            or none are given, the video's original spoken language is used.
        chunk_seconds: Merge caption cues into windows of about this length. Use
            ``0`` to keep YouTube's raw cues.
        start_seconds: Drop everything before this offset, or ``None``.
        end_seconds: Drop everything at or after this offset, or ``None``.

    Returns:
        The transcript, with ``text`` formatted as ``[[MM:SS]](url) line`` rows
        whose links seek to that moment in the video.

    Raises:
        VideoNotFoundError: If the reference cannot be parsed.
        TranscriptBlockedError: If YouTube blocked this host's IP.
        TranscriptUnavailableError: If the video has no retrievable transcript.
    """
    video_id = parse_video_id(reference)
    if not video_id:
        raise VideoNotFoundError(reference)

    available, chosen = _select_transcript(video_id, languages)
    try:
        fetched = chosen.fetch()
    except RequestBlocked:
        raise _blocked(video_id) from None
    except CouldNotRetrieveTranscript as error:
        raise TranscriptUnavailableError(video_id, _reason(error)) from None

    snippets = [
        snippet
        for snippet in fetched.snippets
        if _within(snippet.start, start_seconds, end_seconds)
    ]
    if not snippets:
        raise TranscriptUnavailableError(video_id, "no caption cues in that time range")

    lines = _chunk(snippets, chunk_seconds, video_id)
    last = snippets[-1]

    return Transcript(
        video_id=video_id,
        url=watch_url(video_id),
        language=fetched.language,
        language_code=fetched.language_code,
        is_generated=fetched.is_generated,
        available_languages=available,
        segment_count=len(lines),
        start_seconds=round(snippets[0].start, 2),
        end_seconds=round(last.start + last.duration, 2),
        text="\n".join(lines),
    )


def _select_transcript(
    video_id: str, languages: list[str] | None
) -> tuple[list[str], Any]:
    """Choose which caption track to fetch.

    Args:
        video_id: The video to inspect.
        languages: Preferred language codes in priority order, or ``None``.

    Returns:
        The available language codes and the chosen transcript handle.

    Raises:
        TranscriptBlockedError: If YouTube blocked this host's IP.
        TranscriptUnavailableError: If the video exposes no transcripts.
    """
    try:
        listing = _api().list(video_id)
    except RequestBlocked:
        raise _blocked(video_id) from None
    except CouldNotRetrieveTranscript as error:
        raise TranscriptUnavailableError(video_id, _reason(error)) from None

    tracks = list(listing)
    if not tracks:
        raise TranscriptUnavailableError(video_id, "the video has no caption tracks")
    available = [track.language_code for track in tracks]

    if languages:
        try:
            return available, listing.find_transcript(languages)
        except CouldNotRetrieveTranscript:
            pass

    # With no preference, follow the original audio rather than a community
    # translation: YouTube only auto-generates in the language that was spoken.
    generated = next((track for track in tracks if track.is_generated), None)
    if not generated:
        return available, tracks[0]
    try:
        # Prefer the creator's own captions for that language over the machine ones.
        return available, listing.find_transcript([generated.language_code])
    except CouldNotRetrieveTranscript:
        return available, generated


def _within(start: float, lower: float | None, upper: float | None) -> bool:
    """Test a cue offset against the requested window.

    Args:
        start: The cue's start offset in seconds.
        lower: Inclusive lower bound, or ``None``.
        upper: Exclusive upper bound, or ``None``.

    Returns:
        Whether the cue falls inside the window.
    """
    if lower is not None and start < lower:
        return False
    return not (upper is not None and start >= upper)


def _chunk(snippets: list[Any], chunk_seconds: float, video_id: str) -> list[str]:
    """Merge caption cues into timestamped lines.

    Args:
        snippets: Caption cues, in playback order.
        chunk_seconds: Approximate window per output line; ``0`` keeps one line
            per cue.
        video_id: The video the cues came from, used to build the seek links.

    Returns:
        Lines formatted as ``[[MM:SS]](watch url with &t=) text``.
    """
    stamp = partial(format_timestamp_link, video_id)
    if chunk_seconds <= 0:
        return [f"{stamp(s.start)} {_clean(s.text)}" for s in snippets]

    lines: list[str] = []
    window_start = snippets[0].start
    buffer: list[str] = []

    for snippet in snippets:
        if buffer and snippet.start - window_start >= chunk_seconds:
            lines.append(f"{stamp(window_start)} {' '.join(buffer)}")
            window_start = snippet.start
            buffer = []
        text = _clean(snippet.text)
        if text:
            buffer.append(text)

    if buffer:
        lines.append(f"{stamp(window_start)} {' '.join(buffer)}")
    return lines


def _clean(text: str) -> str:
    """Normalise a caption cue's whitespace.

    Args:
        text: The raw cue text.

    Returns:
        The cue on a single line with collapsed whitespace.
    """
    return " ".join(text.split())


def _reason(error: CouldNotRetrieveTranscript) -> str:
    """Reduce a transcript-api exception to a short explanation.

    Args:
        error: The raised exception.

    Returns:
        A one-line reason, taken from the exception's cause message.
    """
    cause = getattr(error, "cause", "") or type(error).__name__
    return " ".join(str(cause).split())

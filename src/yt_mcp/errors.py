"""Tool-facing exceptions.

Every exception here derives from :class:`fastmcp.exceptions.ToolError`, whose
message is forwarded verbatim to the MCP client. Messages are built inside the
exception classes so callers raise them without inline strings.
"""

from fastmcp.exceptions import ToolError


class MissingApiKeyError(ToolError):
    """The YouTube Data API key is not configured."""

    def __init__(self, env_var: str) -> None:
        """Build the error for a missing API key environment variable."""
        super().__init__(
            f"{env_var} is not set. Create an API key in the Google Cloud console "
            f"(enable 'YouTube Data API v3') and put it in the project's .env file "
            f"as {env_var}=...",
        )


class ChannelNotFoundError(ToolError):
    """No channel matched the caller's reference."""

    def __init__(self, reference: str) -> None:
        """Build the error for an unresolvable channel reference."""
        super().__init__(
            f"No YouTube channel matched {reference!r}. Pass a handle (@mkbhd), a "
            f"channel URL, a channel id (UC...), or an exact channel name.",
        )


class VideoNotFoundError(ToolError):
    """No video matched the caller's reference."""

    def __init__(self, reference: str) -> None:
        """Build the error for an unresolvable video reference."""
        super().__init__(
            f"No YouTube video matched {reference!r}. Pass a video id or a watch/"
            f"youtu.be/shorts URL. The video may also be private or deleted.",
        )


class TranscriptUnavailableError(ToolError):
    """The video has no transcript that can be fetched."""

    def __init__(self, video_id: str, reason: str) -> None:
        """Build the error for a video whose transcript cannot be retrieved."""
        super().__init__(f"No transcript available for video {video_id}: {reason}")


class TranscriptBlockedError(ToolError):
    """YouTube refused the caption request because of the caller's IP."""

    def __init__(self, video_id: str, url_env: str, webshare_env: str) -> None:
        """Build the error naming the env vars that configure a proxy."""
        super().__init__(
            f"YouTube blocked the caption request for video {video_id} by IP. This "
            f"host's IP is rate limited or belongs to a cloud provider, whose "
            f"ranges YouTube blocks; the video itself is fine. Route captions "
            f"through a residential proxy by setting {url_env}, or {webshare_env} "
            f"with its password.",
        )


class InvalidDateError(ToolError):
    """A date filter could not be parsed."""

    def __init__(self, value: str) -> None:
        """Build the error for an unparseable date filter."""
        super().__init__(
            f"Could not parse date {value!r}. Use a relative offset (24h, 7d, 3w, "
            f"6m, 1y), a date (2025-01-31), or an RFC 3339 timestamp "
            f"(2025-01-31T00:00:00Z).",
        )


class YouTubeApiError(ToolError):
    """The YouTube Data API rejected the request."""

    def __init__(self, status: int, reason: str, detail: str) -> None:
        """Build the error from an HTTP status, API reason code and message."""
        hint = _HINTS.get(reason, "")
        super().__init__(f"YouTube Data API error {status} ({reason}): {detail}{hint}")


_HINTS = {
    "quotaExceeded": (
        " — the daily quota for this API key is spent; it resets at midnight "
        "Pacific time."
    ),
    "keyInvalid": " — the API key is malformed or belongs to a different project.",
    "accessNotConfigured": (
        " — enable 'YouTube Data API v3' for this project in the Google Cloud console."
    ),
    "forbidden": " — the API key may be IP/referrer restricted.",
}

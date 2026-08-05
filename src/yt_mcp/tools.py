"""The MCP tools, registered against the server instance on import."""

from typing import Annotated, Literal

from yt_mcp import youtube
from yt_mcp.models import Channel, Transcript, VideoDetails, VideoList
from yt_mcp.parsing import parse_date_filter
from yt_mcp.server import mcp
from yt_mcp.transcripts import DEFAULT_CHUNK_SECONDS, get_transcript

SEARCH_RESULT_CAP = 50
"""Upper bound on search results; every page of search costs 100 quota units."""

LIST_RESULT_CAP = 200
"""Upper bound on listing results; listing costs 1 unit per 50 videos."""

ChannelArg = Annotated[
    str,
    "Channel handle (@mkbhd), channel URL, channel id (UC...), or channel name",
]
VideoArg = Annotated[str, "Video id, or a watch / youtu.be / shorts URL"]
PublishedAfterArg = Annotated[
    str | None,
    "Only videos published at or after this point: 7d, 6m, 1y, 2025-01-31, or RFC 3339",
]
PublishedBeforeArg = Annotated[
    str | None,
    "Only videos published at or before this point, same formats as published_after",
]


@mcp.tool
def find_channel(channel: ChannelArg) -> Channel:
    """Resolve a channel handle, URL, id or name to a channel with its stats.

    Useful on its own to confirm which channel a name refers to before searching.
    """
    return youtube.resolve_channel(channel)


@mcp.tool
def search_channel_videos(
    channel: ChannelArg,
    query: Annotated[str, "What to search for within the channel's videos"],
    max_results: Annotated[int, "How many videos to return (1-50)"] = 10,
    order: Annotated[
        Literal["relevance", "date", "viewCount", "rating", "title"],
        "Result ordering; 'relevance' matches the query best, 'date' is newest first",
    ] = "relevance",
    published_after: PublishedAfterArg = None,
    published_before: PublishedBeforeArg = None,
) -> VideoList:
    """Search one channel's videos by keyword, e.g. the latest iPhone review on MKBHD.

    Costs 100 YouTube quota units per 50 results. When you want recent uploads and
    have no keyword, use list_channel_videos instead — it is 100x cheaper.
    """
    resolved = youtube.resolve_channel(channel)
    after = parse_date_filter(published_after) if published_after else None
    before = parse_date_filter(published_before) if published_before else None

    videos, truncated = youtube.search_channel_videos(
        resolved,
        query,
        max_results=max(1, min(max_results, SEARCH_RESULT_CAP)),
        order=order,
        published_after=after,
        published_before=before,
    )
    return VideoList(
        channel=resolved,
        query=query,
        published_after=after,
        published_before=before,
        count=len(videos),
        videos=videos,
        truncated=truncated,
    )


@mcp.tool
def list_channel_videos(
    channel: ChannelArg,
    max_results: Annotated[int, "How many videos to return (1-200)"] = 25,
    published_after: PublishedAfterArg = None,
    published_before: PublishedBeforeArg = None,
) -> VideoList:
    """List a channel's uploads newest first, optionally within a date range.

    Example: everything MKBHD posted in the last year, via published_after='1y'.
    """
    resolved = youtube.resolve_channel(channel)
    after = parse_date_filter(published_after) if published_after else None
    before = parse_date_filter(published_before) if published_before else None

    videos, truncated = youtube.list_channel_videos(
        resolved,
        max_results=max(1, min(max_results, LIST_RESULT_CAP)),
        published_after=after,
        published_before=before,
    )
    return VideoList(
        channel=resolved,
        published_after=after,
        published_before=before,
        count=len(videos),
        videos=videos,
        truncated=truncated,
    )


@mcp.tool
def get_video_transcript(
    video: VideoArg,
    languages: Annotated[
        list[str] | None,
        "Preferred language codes in priority order, e.g. ['en', 'en-US']; "
        "defaults to the video's original spoken language",
    ] = None,
    chunk_seconds: Annotated[
        float,
        "Merge caption cues into windows of about this many seconds; 0 keeps raw cues",
    ] = DEFAULT_CHUNK_SECONDS,
    start_seconds: Annotated[
        float | None,
        "Only return the transcript from this offset onward",
    ] = None,
    end_seconds: Annotated[
        float | None,
        "Only return the transcript up to this offset",
    ] = None,
) -> Transcript:
    """Get a video's transcript as '[MM:SS] text' lines you can quote and cite.

    Quote the timestamps back so claims stay traceable, e.g. "at [03:15] he says
    the battery is 17% larger than last year". Narrow long videos with
    start_seconds and end_seconds. Reads public caption tracks, so it costs no
    API quota.
    """
    return get_transcript(
        video,
        languages=languages,
        chunk_seconds=chunk_seconds,
        start_seconds=start_seconds,
        end_seconds=end_seconds,
    )


@mcp.tool
def get_video_details(video: VideoArg) -> VideoDetails:
    """Get a video's full description, extracted links, tags and engagement counts.

    The links list is what the creator cited in the description — sources,
    products, sponsors and their own other videos.
    """
    return youtube.get_video_details(video)

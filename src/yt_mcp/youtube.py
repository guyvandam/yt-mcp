"""Thin wrapper over the YouTube Data API v3.

Quota notes (units per call, 10 000/day by default): ``search.list`` costs 100,
everything else used here costs 1. ``list_channel_videos`` therefore walks the
channel's uploads playlist instead of searching.
"""

import json
import threading
from datetime import datetime
from itertools import islice
from typing import Any

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from yt_mcp.config import settings
from yt_mcp.errors import ChannelNotFoundError, VideoNotFoundError, YouTubeApiError
from yt_mcp.models import Channel, Video, VideoDetails
from yt_mcp.parsing import (
    extract_links,
    format_duration,
    parse_api_timestamp,
    parse_channel_reference,
    parse_iso_duration,
    parse_video_id,
    to_rfc3339,
    watch_url,
)

MAX_IDS_PER_REQUEST = 50
"""Ceiling the API imposes on batched id lookups and page sizes."""

SHORT_FORM_SECONDS = 60
"""Duration at or below which a video is flagged as short-form."""

_EXCERPT_CHARS = 220

_local = threading.local()
_channel_cache: dict[str, Channel] = {}
_channel_cache_lock = threading.Lock()


def _client() -> Any:
    """Return this thread's YouTube API client.

    ``httplib2`` connections are not thread-safe and FastMCP runs sync tools in a
    threadpool, so each worker thread gets its own client.

    Returns:
        A discovery ``Resource`` for the YouTube Data API v3.
    """
    client = getattr(_local, "client", None)
    if client is None:
        client = build(
            "youtube",
            "v3",
            developerKey=settings().api_key,
            cache_discovery=False,
        )
        _local.client = client
    return client


def _execute(request: Any) -> dict[str, Any]:
    """Run an API request, translating transport errors into tool errors.

    Args:
        request: A prepared googleapiclient request.

    Returns:
        The decoded JSON response.

    Raises:
        YouTubeApiError: If the API returns a non-2xx response.
    """
    try:
        return request.execute()
    except HttpError as error:
        status = error.resp.status if error.resp else 0
        reason, detail = _describe(error)
        raise YouTubeApiError(status, reason, detail) from None


def _describe(error: HttpError) -> tuple[str, str]:
    """Pull the reason code and message out of an API error body.

    Args:
        error: The raised transport error.

    Returns:
        A ``(reason, message)`` pair, falling back to generic values.
    """
    try:
        body = json.loads(error.content.decode("utf-8"))["error"]
        first = body.get("errors", [{}])[0]
        return first.get("reason", "unknown"), body.get("message", str(error))
    except (ValueError, KeyError, AttributeError, UnicodeDecodeError):
        return "unknown", str(error)


# --------------------------------------------------------------------------- #
# Channels
# --------------------------------------------------------------------------- #


def resolve_channel(reference: str) -> Channel:
    """Resolve any channel reference to a full channel record.

    Results are memoised for the life of the process, so repeated tool calls
    against the same channel cost no quota.

    Args:
        reference: Channel id, ``@handle``, channel URL or channel name.

    Returns:
        The resolved channel.

    Raises:
        ChannelNotFoundError: If nothing matches the reference.
    """
    key = reference.strip().lower()
    with _channel_cache_lock:
        cached = _channel_cache.get(key)
    if cached:
        return cached

    kind, value = parse_channel_reference(reference)
    channel_id = value if kind == "id" else _lookup_channel_id(kind, value, reference)
    channel = _fetch_channel(channel_id, reference)

    with _channel_cache_lock:
        _channel_cache[key] = channel
        _channel_cache[channel.id.lower()] = channel
    return channel


def _lookup_channel_id(kind: str, value: str, reference: str) -> str:
    """Turn a handle, legacy username or name into a channel id.

    Args:
        kind: One of ``handle``, ``username`` or ``search``.
        value: The extracted lookup value.
        reference: The caller's original input, used for error messages.

    Returns:
        The channel id.

    Raises:
        ChannelNotFoundError: If no channel matches.
    """
    if kind in ("handle", "username"):
        param = "forHandle" if kind == "handle" else "forUsername"
        response = _execute(_client().channels().list(part="id", **{param: value}))
        items = response.get("items", [])
        if items:
            return items[0]["id"]
        if kind == "username":
            raise ChannelNotFoundError(reference)
        # Handles are not always registered; fall through to a search.

    response = _execute(
        _client().search().list(part="snippet", q=value, type="channel", maxResults=1),
    )
    items = response.get("items", [])
    if not items:
        raise ChannelNotFoundError(reference)
    return items[0]["snippet"]["channelId"]


def _fetch_channel(channel_id: str, reference: str) -> Channel:
    """Load the full channel resource for an id.

    Args:
        channel_id: The channel id to fetch.
        reference: The caller's original input, used for error messages.

    Returns:
        The channel record.

    Raises:
        ChannelNotFoundError: If the id resolves to nothing.
    """
    response = _execute(
        _client()
        .channels()
        .list(part="snippet,statistics,contentDetails", id=channel_id),
    )
    items = response.get("items", [])
    if not items:
        raise ChannelNotFoundError(reference)

    item = items[0]
    snippet = item.get("snippet", {})
    stats = item.get("statistics", {})
    handle = snippet.get("customUrl")
    if handle and not handle.startswith("@"):
        handle = f"@{handle}"

    return Channel(
        id=item["id"],
        title=snippet.get("title", ""),
        handle=handle,
        url=f"https://www.youtube.com/{handle or 'channel/' + item['id']}",
        description=snippet.get("description", ""),
        subscriber_count=(
            None
            if stats.get("hiddenSubscriberCount")
            else _as_int(stats.get("subscriberCount"))
        ),
        video_count=_as_int(stats.get("videoCount")),
        uploads_playlist_id=(
            item.get("contentDetails", {}).get("relatedPlaylists", {}).get("uploads")
        ),
    )


# --------------------------------------------------------------------------- #
# Videos
# --------------------------------------------------------------------------- #


def search_channel_videos(
    channel: Channel,
    query: str,
    *,
    max_results: int,
    order: str,
    published_after: datetime | None,
    published_before: datetime | None,
) -> tuple[list[Video], bool]:
    """Search a single channel's videos.

    Args:
        channel: The channel to search within.
        query: Search terms.
        max_results: Maximum videos to return.
        order: A ``search.list`` order value, e.g. ``relevance`` or ``date``.
        published_after: Lower bound on publish date, or ``None``.
        published_before: Upper bound on publish date, or ``None``.

    Returns:
        The matching videos and a flag indicating more results were available.
    """
    params: dict[str, Any] = {
        "part": "id",
        "channelId": channel.id,
        "q": query,
        "type": "video",
        "order": order,
        "maxResults": min(max_results, MAX_IDS_PER_REQUEST),
    }
    if published_after:
        params["publishedAfter"] = to_rfc3339(published_after)
    if published_before:
        params["publishedBefore"] = to_rfc3339(published_before)

    video_ids: list[str] = []
    page_token: str | None = None
    while len(video_ids) < max_results:
        response = _execute(_client().search().list(**params, pageToken=page_token))
        video_ids.extend(
            item["id"]["videoId"]
            for item in response.get("items", [])
            if item.get("id", {}).get("videoId")
        )
        page_token = response.get("nextPageToken")
        if not page_token:
            break

    truncated = len(video_ids) > max_results or bool(page_token)
    videos = hydrate_videos(video_ids[:max_results])
    if order == "date":
        videos.sort(key=_published_sort_key, reverse=True)
    return videos, truncated


def list_channel_videos(
    channel: Channel,
    *,
    max_results: int,
    published_after: datetime | None,
    published_before: datetime | None,
) -> tuple[list[Video], bool]:
    """List a channel's uploads, newest first, optionally bounded by date.

    Walks the channel's uploads playlist (1 quota unit per 50 videos) and stops
    as soon as it passes ``published_after``.

    Args:
        channel: The channel whose uploads to list.
        max_results: Maximum videos to return.
        published_after: Lower bound on publish date, or ``None``.
        published_before: Upper bound on publish date, or ``None``.

    Returns:
        The matching videos and a flag indicating more videos were available.

    Raises:
        ChannelNotFoundError: If the channel exposes no uploads playlist.
    """
    if not channel.uploads_playlist_id:
        raise ChannelNotFoundError(channel.id)

    collected: list[str] = []
    page_token: str | None = None
    exhausted = False
    while len(collected) < max_results and not exhausted:
        response = _execute(
            _client()
            .playlistItems()
            .list(
                part="contentDetails",
                playlistId=channel.uploads_playlist_id,
                maxResults=MAX_IDS_PER_REQUEST,
                pageToken=page_token,
            ),
        )
        page_ids, exhausted = _filter_playlist_page(
            response.get("items", []),
            published_after,
            published_before,
        )
        collected.extend(page_ids)
        page_token = response.get("nextPageToken")
        exhausted = exhausted or not page_token

    truncated = len(collected) > max_results or not exhausted
    return hydrate_videos(collected[:max_results]), truncated


def _filter_playlist_page(
    items: list[dict[str, Any]],
    published_after: datetime | None,
    published_before: datetime | None,
) -> tuple[list[str], bool]:
    """Apply date bounds to one page of uploads-playlist items.

    Args:
        items: Raw ``playlistItems`` entries.
        published_after: Lower bound on publish date, or ``None``.
        published_before: Upper bound on publish date, or ``None``.

    Returns:
        The surviving video ids and whether the page crossed
        ``published_after`` — the playlist is newest-first, so that ends paging.
    """
    kept: list[str] = []
    for item in items:
        details = item.get("contentDetails", {})
        video_id = details.get("videoId")
        if not video_id:
            continue
        published = parse_api_timestamp(details.get("videoPublishedAt"))
        if published_after and published and published < published_after:
            return kept, True
        if published_before and published and published > published_before:
            continue
        kept.append(video_id)
    return kept, False


def hydrate_videos(video_ids: list[str]) -> list[Video]:
    """Fetch metadata for video ids, preserving the input order.

    Args:
        video_ids: Video ids, in the order they should be returned.

    Returns:
        One :class:`~yt_mcp.models.Video` per id that still resolves.
    """
    if not video_ids:
        return []
    by_id = {item["id"]: item for item in _fetch_video_items(video_ids)}
    return [_to_video(by_id[vid]) for vid in video_ids if vid in by_id]


def get_video_details(reference: str) -> VideoDetails:
    """Load one video with its full description, links and engagement counts.

    Args:
        reference: A video id or any YouTube video URL.

    Returns:
        The full video record.

    Raises:
        VideoNotFoundError: If the reference cannot be parsed or resolved.
    """
    video_id = parse_video_id(reference)
    if not video_id:
        raise VideoNotFoundError(reference)

    items = _fetch_video_items([video_id])
    if not items:
        raise VideoNotFoundError(reference)

    item = items[0]
    snippet = item.get("snippet", {})
    stats = item.get("statistics", {})
    description = snippet.get("description", "")
    base = _to_video(item)

    return VideoDetails(
        **base.model_dump(),
        description=description,
        links=extract_links(description),
        tags=snippet.get("tags", []),
        like_count=_as_int(stats.get("likeCount")),
        comment_count=_as_int(stats.get("commentCount")),
        has_captions=_as_bool(item.get("contentDetails", {}).get("caption")),
    )


def _fetch_video_items(video_ids: list[str]) -> list[dict[str, Any]]:
    """Fetch raw ``videos.list`` resources in batches of 50.

    Args:
        video_ids: Video ids to look up.

    Returns:
        The raw API items, in whatever order the API returns them.
    """
    items: list[dict[str, Any]] = []
    iterator = iter(video_ids)
    while batch := list(islice(iterator, MAX_IDS_PER_REQUEST)):
        response = _execute(
            _client()
            .videos()
            .list(part="snippet,contentDetails,statistics", id=",".join(batch)),
        )
        items.extend(response.get("items", []))
    return items


def _to_video(item: dict[str, Any]) -> Video:
    """Convert a raw ``videos.list`` resource into a :class:`Video`.

    Args:
        item: The raw API resource.

    Returns:
        The mapped video.
    """
    snippet = item.get("snippet", {})
    description = snippet.get("description", "")
    seconds = parse_iso_duration(item.get("contentDetails", {}).get("duration"))

    return Video(
        id=item["id"],
        title=snippet.get("title", ""),
        url=watch_url(item["id"]),
        channel_id=snippet.get("channelId", ""),
        channel_title=snippet.get("channelTitle", ""),
        published_at=parse_api_timestamp(snippet.get("publishedAt")),
        duration=format_duration(seconds),
        duration_seconds=seconds,
        is_short_form=seconds is not None and seconds <= SHORT_FORM_SECONDS,
        view_count=_as_int(item.get("statistics", {}).get("viewCount")),
        description_excerpt=_excerpt(description),
    )


def _excerpt(description: str) -> str:
    """Trim a description down to a preview.

    Args:
        description: The full description.

    Returns:
        The first ``_EXCERPT_CHARS`` characters, ellipsised when cut.
    """
    flat = " ".join(description.split())
    if len(flat) <= _EXCERPT_CHARS:
        return flat
    return f"{flat[:_EXCERPT_CHARS].rstrip()}…"


def _published_sort_key(video: Video) -> float:
    """Sort key placing videos without a publish date last.

    Args:
        video: The video to key.

    Returns:
        The publish timestamp, or ``-inf`` when unknown.
    """
    return video.published_at.timestamp() if video.published_at else float("-inf")


def _as_int(value: str | None) -> int | None:
    """Coerce an API count string to an int.

    Args:
        value: The raw string, or ``None``.

    Returns:
        The parsed integer, or ``None`` when absent or non-numeric.
    """
    try:
        return int(value) if value is not None else None
    except ValueError:
        return None


def _as_bool(value: str | None) -> bool | None:
    """Coerce the API's ``"true"``/``"false"`` strings to a bool.

    Args:
        value: The raw string, or ``None``.

    Returns:
        The parsed boolean, or ``None`` when absent.
    """
    return None if value is None else value == "true"

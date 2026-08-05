"""Tests for the YouTube Data API mapping layer, against a faked client."""

from datetime import UTC, datetime
from typing import Any

import pytest

from yt_mcp import youtube
from yt_mcp.config import API_KEY_ENV, settings
from yt_mcp.errors import ChannelNotFoundError, MissingApiKeyError, VideoNotFoundError

CHANNEL_ID = "UCBJycsmduvYEL83R_U4JriQ"
UPLOADS_ID = "UUBJycsmduvYEL83R_U4JriQ"

CHANNEL_ITEM = {
    "id": CHANNEL_ID,
    "snippet": {
        "title": "Marques Brownlee",
        "customUrl": "@mkbhd",
        "description": "Quality Tech Videos",
    },
    "statistics": {"subscriberCount": "20100000", "videoCount": "1700"},
    "contentDetails": {"relatedPlaylists": {"uploads": UPLOADS_ID}},
}

VIDEO_ITEM = {
    "id": "dQw4w9WgXcQ",
    "snippet": {
        "title": "iPhone 17 Pro Review",
        "channelId": CHANNEL_ID,
        "channelTitle": "Marques Brownlee",
        "publishedAt": "2025-09-19T13:00:00Z",
        "description": "Battery is 17% larger.\nGear: https://shop.example.com/x.",
        "tags": ["iphone", "review"],
    },
    "contentDetails": {"duration": "PT12M34S", "caption": "true"},
    "statistics": {
        "viewCount": "5000000",
        "likeCount": "200000",
        "commentCount": "9000",
    },
}


class FakeRequest:
    """A prepared request that simply replays a canned response."""

    def __init__(self, response: dict[str, Any]) -> None:
        """Store the response this request will return."""
        self._response = response

    def execute(self) -> dict[str, Any]:
        """Return the canned response."""
        return self._response


class FakeEndpoint:
    """One API collection, e.g. ``channels``, recording the calls it receives."""

    def __init__(
        self, pages: list[dict[str, Any]], calls: list[dict[str, Any]]
    ) -> None:
        """Store the pages to hand out and the shared call log."""
        self._pages = pages
        self._calls = calls

    def list(self, **kwargs: Any) -> FakeRequest:
        """Record the call and return the next page."""
        self._calls.append(kwargs)
        page = self._pages.pop(0) if len(self._pages) > 1 else self._pages[0]
        return FakeRequest(page)


class FakeClient:
    """Stand-in for the discovery ``Resource`` returned by ``build``."""

    def __init__(self, **pages: list[dict[str, Any]]) -> None:
        """Register canned pages per endpoint name."""
        self.calls: list[dict[str, Any]] = []
        self._endpoints = {
            name: FakeEndpoint(value, self.calls) for name, value in pages.items()
        }

    def __getattr__(self, name: str) -> Any:
        """Expose each registered endpoint as a zero-argument method."""
        endpoint = self._endpoints[name]
        return lambda: endpoint


@pytest.fixture(autouse=True)
def _clear_channel_cache() -> None:
    """Keep the process-wide channel cache from leaking between tests."""
    youtube._channel_cache.clear()


def _install(monkeypatch: pytest.MonkeyPatch, client: FakeClient) -> None:
    """Point the module's client factory at a fake client."""
    monkeypatch.setattr(youtube, "_client", lambda: client)


def test_settings_without_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """A missing API key surfaces as an actionable tool error."""
    settings.cache_clear()
    monkeypatch.delenv(API_KEY_ENV, raising=False)
    monkeypatch.setattr("yt_mcp.config.load_dotenv", lambda *_: None)
    with pytest.raises(MissingApiKeyError, match=API_KEY_ENV):
        settings()
    settings.cache_clear()


def test_resolve_channel_by_handle(monkeypatch: pytest.MonkeyPatch) -> None:
    """A handle resolves via forHandle and maps onto the channel model."""
    client = FakeClient(channels=[{"items": [CHANNEL_ITEM]}])
    _install(monkeypatch, client)

    channel = youtube.resolve_channel("@mkbhd")

    assert client.calls[0]["forHandle"] == "mkbhd"
    assert channel.id == CHANNEL_ID
    assert channel.handle == "@mkbhd"
    assert channel.url == "https://www.youtube.com/@mkbhd"
    assert channel.subscriber_count == 20100000
    assert channel.uploads_playlist_id == UPLOADS_ID


def test_resolve_channel_is_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    """A second lookup of the same channel spends no further quota."""
    client = FakeClient(channels=[{"items": [CHANNEL_ITEM]}])
    _install(monkeypatch, client)

    youtube.resolve_channel("@mkbhd")
    call_count = len(client.calls)
    youtube.resolve_channel("@MKBHD")

    assert len(client.calls) == call_count


def test_resolve_channel_hides_subscriber_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Channels that hide their subscriber count report null, not zero."""
    item = {**CHANNEL_ITEM, "statistics": {"hiddenSubscriberCount": True}}
    _install(monkeypatch, FakeClient(channels=[{"items": [item]}]))

    assert youtube.resolve_channel(CHANNEL_ID).subscriber_count is None


def test_resolve_channel_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    """An id that resolves to nothing raises a tool-facing error."""
    _install(monkeypatch, FakeClient(channels=[{"items": []}]))

    with pytest.raises(ChannelNotFoundError):
        youtube.resolve_channel(CHANNEL_ID)


def test_get_video_details_extracts_links(monkeypatch: pytest.MonkeyPatch) -> None:
    """Details carry the full description, its links, tags and counts."""
    _install(monkeypatch, FakeClient(videos=[{"items": [VIDEO_ITEM]}]))

    details = youtube.get_video_details("https://youtu.be/dQw4w9WgXcQ")

    assert details.id == "dQw4w9WgXcQ"
    assert details.duration == "12:34"
    assert details.duration_seconds == 754
    assert details.is_short_form is False
    assert details.view_count == 5000000
    assert details.links == ["https://shop.example.com/x"]
    assert details.tags == ["iphone", "review"]
    assert details.has_captions is True
    assert details.published_at == datetime(2025, 9, 19, 13, 0, tzinfo=UTC)


def test_get_video_details_rejects_bad_reference() -> None:
    """A reference with no extractable video id fails before any API call."""
    with pytest.raises(VideoNotFoundError):
        youtube.get_video_details("definitely not a video")


def test_short_form_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    """Videos of a minute or less are flagged as likely Shorts."""
    item = {**VIDEO_ITEM, "contentDetails": {"duration": "PT45S"}}
    _install(monkeypatch, FakeClient(videos=[{"items": [item]}]))

    assert youtube.get_video_details("dQw4w9WgXcQ").is_short_form is True


def test_hydrate_videos_preserves_order(monkeypatch: pytest.MonkeyPatch) -> None:
    """Results follow the requested id order, not the API's, and drop unknowns."""
    second = {**VIDEO_ITEM, "id": "abcdefghijk"}
    _install(monkeypatch, FakeClient(videos=[{"items": [second, VIDEO_ITEM]}]))

    videos = youtube.hydrate_videos(["dQw4w9WgXcQ", "abcdefghijk", "missing1234"])

    assert [video.id for video in videos] == ["dQw4w9WgXcQ", "abcdefghijk"]


def _playlist_page(*published: str) -> dict[str, Any]:
    """Build a playlistItems page from publish timestamps."""
    return {
        "items": [
            {
                "contentDetails": {
                    "videoId": f"vid{index:08d}",
                    "videoPublishedAt": stamp,
                }
            }
            for index, stamp in enumerate(published)
        ],
    }


def test_filter_playlist_page_stops_at_lower_bound() -> None:
    """Paging ends as soon as the newest-first playlist crosses published_after."""
    page = _playlist_page(
        "2025-06-01T00:00:00Z",
        "2025-02-01T00:00:00Z",
        "2024-06-01T00:00:00Z",
        "2024-01-01T00:00:00Z",
    )
    after = datetime(2025, 1, 1, tzinfo=UTC)

    kept, exhausted = youtube._filter_playlist_page(page["items"], after, None)

    assert kept == ["vid00000000", "vid00000001"]
    assert exhausted is True


def test_list_channel_videos_walks_uploads_playlist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Listing pages the uploads playlist and hydrates the surviving ids."""
    page = _playlist_page("2025-06-01T00:00:00Z", "2023-01-01T00:00:00Z")
    hydrated = [
        {**VIDEO_ITEM, "id": "vid00000000"},
        {**VIDEO_ITEM, "id": "vid00000001"},
    ]
    client = FakeClient(
        channels=[{"items": [CHANNEL_ITEM]}],
        playlistItems=[page],
        videos=[{"items": hydrated}],
    )
    _install(monkeypatch, client)
    channel = youtube.resolve_channel("@mkbhd")

    videos, truncated = youtube.list_channel_videos(
        channel,
        max_results=25,
        published_after=datetime(2025, 1, 1, tzinfo=UTC),
        published_before=None,
    )

    playlist_call = next(c for c in client.calls if "playlistId" in c)
    assert playlist_call["playlistId"] == UPLOADS_ID
    assert [video.id for video in videos] == ["vid00000000"]
    assert truncated is False


def test_search_channel_videos_scopes_and_bounds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Search is scoped to the channel and forwards the date bounds as RFC 3339."""
    search_page = {"items": [{"id": {"videoId": "dQw4w9WgXcQ"}}]}
    client = FakeClient(
        channels=[{"items": [CHANNEL_ITEM]}],
        search=[search_page],
        videos=[{"items": [VIDEO_ITEM]}],
    )
    _install(monkeypatch, client)
    channel = youtube.resolve_channel("@mkbhd")

    videos, truncated = youtube.search_channel_videos(
        channel,
        "iphone review",
        max_results=10,
        order="date",
        published_after=datetime(2025, 1, 1, tzinfo=UTC),
        published_before=None,
    )

    search_call = next(c for c in client.calls if "q" in c)
    assert search_call["channelId"] == CHANNEL_ID
    assert search_call["type"] == "video"
    assert search_call["publishedAfter"] == "2025-01-01T00:00:00Z"
    assert [video.title for video in videos] == ["iPhone 17 Pro Review"]
    assert truncated is False


def test_filter_playlist_page_skips_above_upper_bound() -> None:
    """Videos newer than published_before are skipped without ending the walk."""
    page = _playlist_page("2025-06-01T00:00:00Z", "2025-02-01T00:00:00Z")
    before = datetime(2025, 3, 1, tzinfo=UTC)

    kept, exhausted = youtube._filter_playlist_page(page["items"], None, before)

    assert kept == ["vid00000001"]
    assert exhausted is False

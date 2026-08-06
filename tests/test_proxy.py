"""Tests for the caption-fetch proxy, which unblocks transcripts in deployment.

YouTube serves caption tracks to residential IPs and blocks the datacenter IPs a
host runs on, so the deployed server needs its caption requests routed through a
proxy while a local checkout needs none.
"""

from collections.abc import Iterator

import pytest
from youtube_transcript_api._errors import IpBlocked, RequestBlocked
from youtube_transcript_api.proxies import GenericProxyConfig, WebshareProxyConfig

from yt_mcp import transcripts
from yt_mcp.config import (
    PROXY_URL_ENV,
    WEBSHARE_PASSWORD_ENV,
    WEBSHARE_USERNAME_ENV,
    proxy_config,
)
from yt_mcp.errors import TranscriptBlockedError

PROXY_ENV_VARS = (PROXY_URL_ENV, WEBSHARE_USERNAME_ENV, WEBSHARE_PASSWORD_ENV)


@pytest.fixture(autouse=True)
def clean_proxy_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Start each test with no proxy configured and no memoised answer."""
    for name in PROXY_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    proxy_config.cache_clear()
    yield
    proxy_config.cache_clear()


def test_no_proxy_when_unconfigured() -> None:
    """A local checkout with no proxy env vars fetches captions directly."""
    assert proxy_config() is None


def test_generic_proxy_from_url(monkeypatch: pytest.MonkeyPatch) -> None:
    """A single proxy URL is used for both http and https caption requests."""
    monkeypatch.setenv(PROXY_URL_ENV, "http://user:pass@proxy.example.com:8080")

    config = proxy_config()

    assert isinstance(config, GenericProxyConfig)
    assert config.to_requests_dict() == {
        "http": "http://user:pass@proxy.example.com:8080",
        "https": "http://user:pass@proxy.example.com:8080",
    }


def test_webshare_credentials_win_over_url(monkeypatch: pytest.MonkeyPatch) -> None:
    """Webshare's rotating residential pool is preferred over a fixed proxy."""
    monkeypatch.setenv(PROXY_URL_ENV, "http://proxy.example.com:8080")
    monkeypatch.setenv(WEBSHARE_USERNAME_ENV, "user")
    monkeypatch.setenv(WEBSHARE_PASSWORD_ENV, "pass")

    assert isinstance(proxy_config(), WebshareProxyConfig)


def test_half_configured_webshare_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    """A username without a password is ignored rather than half-applied."""
    monkeypatch.setenv(PROXY_URL_ENV, "http://proxy.example.com:8080")
    monkeypatch.setenv(WEBSHARE_USERNAME_ENV, "user")

    assert isinstance(proxy_config(), GenericProxyConfig)


def test_blank_values_are_not_a_proxy(monkeypatch: pytest.MonkeyPatch) -> None:
    """An empty host secret means unset, not a proxy at the empty address."""
    monkeypatch.setenv(PROXY_URL_ENV, "   ")

    assert proxy_config() is None


def test_api_is_built_with_the_configured_proxy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The proxy reaches the transcript client, not just the settings layer."""
    monkeypatch.setenv(PROXY_URL_ENV, "http://proxy.example.com:8080")

    session = transcripts._api()._fetcher._http_client

    assert session.proxies == {
        "http": "http://proxy.example.com:8080",
        "https": "http://proxy.example.com:8080",
    }


def test_unconfigured_api_has_no_proxy() -> None:
    """Without env vars the client goes straight to YouTube."""
    assert transcripts._api()._fetcher._http_client.proxies == {}


@pytest.mark.parametrize("blocked", [RequestBlocked, IpBlocked])
def test_ip_block_raises_an_actionable_error(
    monkeypatch: pytest.MonkeyPatch, blocked: type[RequestBlocked]
) -> None:
    """A blocked IP is reported as a proxy problem, not a missing transcript."""

    def blocked_listing(self: object, video_id: str) -> None:
        raise blocked(video_id)

    monkeypatch.setattr(
        "youtube_transcript_api.YouTubeTranscriptApi.list", blocked_listing
    )

    with pytest.raises(TranscriptBlockedError) as caught:
        transcripts.get_transcript(
            "dQw4w9WgXcQ",
            languages=None,
            chunk_seconds=30.0,
            start_seconds=None,
            end_seconds=None,
        )

    message = str(caught.value)
    assert PROXY_URL_ENV in message
    assert WEBSHARE_USERNAME_ENV in message
    # The library's own message is a 12-line essay; the tool caller gets one line.
    assert "\n" not in message

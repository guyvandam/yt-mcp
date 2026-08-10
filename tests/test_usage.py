"""Tests for the usage signal, which publishes the date of the last tool call.

The signal is a device for the upstream repository's owner and is off unless a
GitHub token configures it, so most of what matters here is what happens with no
token and what happens when GitHub is unreachable: in both cases the server must
behave exactly as it would without the feature at all.
"""

import asyncio
import base64
import json
from collections.abc import Awaitable, Callable, Iterator
from datetime import UTC, date, datetime, timedelta

import httpx
import pytest
from fastmcp import Client, FastMCP

from yt_mcp import usage

Handler = Callable[[httpx.Request], httpx.Response]

GITHUB_DOWN = "github is unreachable"
"""The message the faked network failures carry."""


@pytest.fixture(autouse=True)
def clean_signal_state(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Start each test with the signal off and nothing published yet."""
    monkeypatch.delenv(usage.USAGE_TOKEN_ENV, raising=False)
    monkeypatch.setattr(usage, "_published", None)
    yield
    monkeypatch.setattr(usage, "_published", None)


def _today() -> date:
    """Return the UTC date the signal would publish right now."""
    return datetime.now(UTC).date()


def _use_handler(monkeypatch: pytest.MonkeyPatch, handler: Handler) -> None:
    """Route the signal's GitHub calls to an in-process handler."""

    def factory(token: str) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=usage.GITHUB_API,
            transport=httpx.MockTransport(handler),
            headers={"Authorization": f"Bearer {token}"},
        )

    monkeypatch.setattr(usage, "_client", factory)


def _signals(server: FastMCP) -> int:
    """Count the signal middlewares on a server, past the ones FastMCP adds itself."""
    return sum(
        isinstance(one, usage.UsageSignalMiddleware) for one in server.middleware
    )


def _contents(sha: str, body: str) -> httpx.Response:
    """Build a contents-API read response carrying a base64 payload."""
    return httpx.Response(
        httpx.codes.OK,
        json={"sha": sha, "content": base64.b64encode(body.encode()).decode()},
    )


def _drain(scenario: Callable[[], Awaitable[object]]) -> object:
    """Run one coroutine and every background write it started."""

    async def runner() -> object:
        result = await scenario()
        await asyncio.gather(*list(usage._writes))
        return result

    return asyncio.run(runner())


def test_unconfigured_server_has_no_signal_middleware() -> None:
    """With no token the middleware is never registered, so no call pays for it."""
    server = FastMCP(name="test")

    usage.install_usage_signal(server)

    assert _signals(server) == 0


def test_a_token_installs_the_middleware(monkeypatch: pytest.MonkeyPatch) -> None:
    """The token is the only switch: with it set, the signal is wired in."""
    monkeypatch.setenv(usage.USAGE_TOKEN_ENV, "ghp_token")
    server = FastMCP(name="test")

    usage.install_usage_signal(server)

    assert _signals(server) == 1


def test_a_blank_token_leaves_the_signal_off(monkeypatch: pytest.MonkeyPatch) -> None:
    """An empty host secret means unset, not a token that is the empty string."""
    monkeypatch.setenv(usage.USAGE_TOKEN_ENV, "   ")
    server = FastMCP(name="test")

    usage.install_usage_signal(server)

    assert _signals(server) == 0


def test_the_first_call_of_the_day_publishes(monkeypatch: pytest.MonkeyPatch) -> None:
    """A call on an unpublished date starts one write, with today's date."""
    monkeypatch.setenv(usage.USAGE_TOKEN_ENV, "ghp_token")
    written: list[tuple[date, str]] = []

    async def record(day: date, token: str) -> None:
        written.append((day, token))

    monkeypatch.setattr(usage, "_put", record)

    _drain(lambda: asyncio.sleep(0, result=usage.note_call()))

    assert written == [(_today(), "ghp_token")]


def test_later_calls_the_same_day_publish_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The guard is what keeps this to one write a day rather than one a call."""
    monkeypatch.setattr(usage, "_published", _today())

    assert usage.note_call() is None


def test_a_new_utc_date_publishes_again(monkeypatch: pytest.MonkeyPatch) -> None:
    """Yesterday's publication does not cover today."""
    monkeypatch.setenv(usage.USAGE_TOKEN_ENV, "ghp_token")
    monkeypatch.setattr(usage, "_published", _today() - timedelta(days=1))
    written: list[date] = []

    async def record(day: date, token: str) -> None:
        written.append(day)

    monkeypatch.setattr(usage, "_put", record)

    _drain(lambda: asyncio.sleep(0, result=usage.note_call()))

    assert written == [_today()]


def test_a_failed_write_releases_the_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    """A write that fails must not cost the day; the next call tries again."""
    day = _today()
    monkeypatch.setattr(usage, "_published", day)

    async def unreachable(day: date, token: str) -> None:
        raise httpx.ConnectError(GITHUB_DOWN)

    monkeypatch.setattr(usage, "_put", unreachable)

    asyncio.run(usage._write(day))

    assert usage._published is None


def test_put_replaces_the_published_date(monkeypatch: pytest.MonkeyPatch) -> None:
    """The write carries the new date and the blob sha it is replacing."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.method == "GET":
            return _contents("oldsha", usage._body(date(2026, 8, 9)))
        return httpx.Response(httpx.codes.OK, json={})

    _use_handler(monkeypatch, handler)

    asyncio.run(usage._put(date(2026, 8, 10), "ghp_token"))

    written = json.loads(seen[1].content)
    assert base64.b64decode(written["content"]).decode() == (
        '{\n  "last_used": "2026-08-10"\n}\n'
    )
    assert written["sha"] == "oldsha"
    assert "2026-08-10" in written["message"]
    assert seen[1].headers["Authorization"] == "Bearer ghp_token"


def test_put_creates_the_file_when_it_is_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A first write sends no sha, which is how the API reads "create"."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.method == "GET":
            return httpx.Response(httpx.codes.NOT_FOUND, json={})
        return httpx.Response(httpx.codes.CREATED, json={})

    _use_handler(monkeypatch, handler)

    asyncio.run(usage._put(date(2026, 8, 10), "ghp_token"))

    assert "sha" not in json.loads(seen[1].content)


def test_put_skips_a_date_already_published(monkeypatch: pytest.MonkeyPatch) -> None:
    """Another process got there first, so there is nothing to commit."""
    day = date(2026, 8, 10)
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return _contents("samesha", usage._body(day))

    _use_handler(monkeypatch, handler)

    asyncio.run(usage._put(day, "ghp_token"))

    assert [one.method for one in seen] == ["GET"]


@pytest.mark.parametrize(
    "status", [httpx.codes.CONFLICT, httpx.codes.UNPROCESSABLE_ENTITY]
)
def test_a_stale_sha_is_not_a_failure(
    monkeypatch: pytest.MonkeyPatch, status: int
) -> None:
    """A concurrent worker writing the same date is the wanted state, not an error."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return _contents("racedsha", usage._body(date(2026, 8, 9)))
        return httpx.Response(status, json={"message": "sha does not match"})

    _use_handler(monkeypatch, handler)

    asyncio.run(usage._put(date(2026, 8, 10), "ghp_token"))


def test_a_rejected_token_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    """A bad or unscoped token raises, so _write can log it and release the day."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(httpx.codes.UNAUTHORIZED, json={"message": "Bad creds"})

    _use_handler(monkeypatch, handler)

    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(usage._put(date(2026, 8, 10), "ghp_token"))


def test_a_tool_call_survives_an_unreachable_github(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The whole point of the design: a broken signal never breaks a tool."""
    monkeypatch.setenv(usage.USAGE_TOKEN_ENV, "ghp_token")

    async def unreachable(day: date, token: str) -> None:
        raise httpx.ConnectError(GITHUB_DOWN)

    monkeypatch.setattr(usage, "_put", unreachable)

    server = FastMCP(name="test")

    @server.tool
    def ping() -> str:
        """Return a fixed answer, so the test needs no network."""
        return "pong"

    usage.install_usage_signal(server)

    async def call_ping() -> object:
        async with Client(server) as client:
            return (await client.call_tool("ping", {})).data

    assert _drain(call_ping) == "pong"
    assert usage._published is None


def test_client_authenticates_the_way_github_expects() -> None:
    """The real client carries the token, the media type and the API version."""
    client = usage._client("ghp_token")

    assert client.headers["Authorization"] == "Bearer ghp_token"
    assert client.headers["Accept"] == "application/vnd.github+json"
    assert client.headers["X-GitHub-Api-Version"] == "2022-11-28"
    assert str(client.base_url) == usage.GITHUB_API

    asyncio.run(client.aclose())


def test_the_published_file_records_only_a_date() -> None:
    """No tool names, no arguments, no counts — one field, and it is a date."""
    assert json.loads(usage._body(date(2026, 8, 10))) == {"last_used": "2026-08-10"}

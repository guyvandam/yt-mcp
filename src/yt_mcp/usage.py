"""Last-used date signal, published to this repository as ``usage.json``.

This is a signalling device for this repository's owner, not a feature of the
server. A repository with no recent commits reads as abandoned even when it runs
every day, and this publishes the one fact that tells those two apart: the UTC
date of the most recent tool call. It records nothing else - no tool names, no
arguments, no counts, no totals.

**Running this server for yourself? Delete this module.** It writes to the
upstream repository, so it does nothing for anyone but that repository's owner,
and it is built to come out in one piece: nothing imports it except the three
lines in ``server.py`` that install it. README.md's "Usage signal" section lists
every file to remove.

The signal is off unless ``USAGE_BADGE_TOKEN`` holds a GitHub token, so a
checkout or a fork without that secret never reaches any of the code below -
the middleware is not even registered.
"""

import asyncio
import base64
import json
import logging
import os
from datetime import UTC, date, datetime

import httpx
from dotenv import find_dotenv, load_dotenv
from fastmcp import FastMCP
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
from fastmcp.tools import ToolResult
from mcp.types import CallToolRequestParams

USAGE_TOKEN_ENV = "USAGE_BADGE_TOKEN"  # noqa: S105 - a variable name
"""Environment variable holding the GitHub token that enables the signal."""

REPOSITORY = "guyvandam/yt-mcp"
"""The repository the signal is published to.

Deliberately not derived from the caller's remote: a deployment has no checkout
to read one from. A fork that keeps this module and sets a token writes here and
is refused, which is why the recommendation is to delete rather than reconfigure.
"""

USAGE_FILE = "usage.json"
"""Path of the published file inside the repository."""

GITHUB_API = "https://api.github.com"
"""Base URL of the GitHub REST API."""

REQUEST_TIMEOUT = 10.0
"""Seconds to wait on GitHub before giving up on the day's write."""

logger = logging.getLogger(__name__)

_CONTENTS_URL = f"/repos/{REPOSITORY}/contents/{USAGE_FILE}"
"""The contents-API endpoint for the published file."""

_ALREADY_WRITTEN = frozenset({httpx.codes.CONFLICT, httpx.codes.UNPROCESSABLE_ENTITY})
"""Statuses that mean the blob moved under us - another worker got there first."""

_published: date | None = None
"""The UTC date this process has published, or is in the middle of publishing.

This is what keeps the signal to one write per day instead of one per tool call:
only the first call of a new UTC date gets past it. :func:`note_call` never
awaits between reading and writing it, so concurrent calls on one event loop
cannot both pass.
"""

_writes: set[asyncio.Task[None]] = set()
"""Strong references to in-flight writes, which asyncio does not hold itself."""


def install_usage_signal(server: FastMCP) -> None:
    """Attach the usage signal to a server, when a token configures it.

    With no token the middleware is never registered, so an unconfigured
    checkout carries no per-call cost and reaches none of this module.

    Args:
        server: The server to attach the middleware to.
    """
    if not usage_token():
        return
    server.add_middleware(UsageSignalMiddleware())


def usage_token() -> str:
    """Read the GitHub token that enables the signal.

    Returns:
        Its trimmed value, empty when unset or blank. A host secret left empty
        counts as unset, which leaves the signal off.
    """
    load_dotenv(find_dotenv(usecwd=True))
    return os.environ.get(USAGE_TOKEN_ENV, "").strip()


class UsageSignalMiddleware(Middleware):
    """Publishes the date of the first tool call of each UTC day."""

    async def on_call_tool(
        self,
        context: MiddlewareContext[CallToolRequestParams],
        call_next: CallNext[CallToolRequestParams, ToolResult],
    ) -> ToolResult:
        """Note the date, run the tool, and wait for the day's write.

        The date is noted before the tool runs, so a call that ends in an error
        still counts - the server served a request either way. The write runs
        alongside the tool, and the call does not return until it ends: a host
        that pauses the process between requests, as Prefect Horizon does, would
        otherwise strand it mid-request until the next call, which then finds it
        timed out. Only the first call of a UTC day waits on GitHub.

        Args:
            context: The tool call being handled.
            call_next: The rest of the middleware chain.

        Returns:
            Whatever the tool returned, untouched.
        """
        write = note_call()
        try:
            return await call_next(context)
        finally:
            if write is not None:
                # Shielded: a cancelled call must not cancel the write, which
                # would skip the guard release in _write and lose the day.
                await asyncio.shield(write)


def note_call() -> asyncio.Task[None] | None:
    """Publish today's date unless this process already has.

    Returns:
        The write, already running, or ``None`` when today needs no write.
    """
    global _published  # noqa: PLW0603 - the one-write-per-day guard, see above

    today = datetime.now(UTC).date()
    if _published == today:
        return None
    _published = today

    write = asyncio.create_task(_write(today))
    _writes.add(write)
    write.add_done_callback(_writes.discard)
    return write


async def _write(day: date) -> None:
    """Publish one date, swallowing every failure.

    Args:
        day: The UTC date to publish.
    """
    global _published  # noqa: PLW0603 - cleared so the next call can retry

    try:
        await _put(day, usage_token())
    except Exception:  # noqa: BLE001 - a signal must never fail a tool call
        # No retry loop: releasing the guard is enough, because the next tool
        # call takes the same path again.
        logger.warning("Usage signal: could not publish %s", day, exc_info=True)
        if _published == day:
            _published = None


async def _put(day: date, token: str) -> None:
    """Write the published file through the GitHub contents API.

    Args:
        day: The UTC date to publish.
        token: The GitHub token to authenticate with.

    Raises:
        httpx.HTTPError: If GitHub refuses the read or the write.
    """
    body = _body(day)
    async with _client(token) as client:
        sha, published = await _current(client)
        if published == body:
            # Another process or worker published today already.
            return
        response = await client.put(_CONTENTS_URL, json=_commit(day, body, sha))
        if response.status_code in _ALREADY_WRITTEN:
            # The sha went stale between the read and the write, which means a
            # concurrent worker wrote the same date. That is the wanted state.
            logger.info("Usage signal: %s was published concurrently", day)
            return
        response.raise_for_status()


async def _current(client: httpx.AsyncClient) -> tuple[str | None, str]:
    """Read the published file's blob sha and contents.

    Args:
        client: The GitHub API client to read through.

    Returns:
        The blob sha and the decoded contents. Both are empty when the file does
        not exist yet, which is the first-write case.

    Raises:
        httpx.HTTPError: If GitHub refuses the read for any reason but absence.
    """
    response = await client.get(_CONTENTS_URL)
    if response.status_code == httpx.codes.NOT_FOUND:
        return None, ""
    response.raise_for_status()
    payload = response.json()
    return payload.get("sha"), _decode(payload.get("content", ""))


def _commit(day: date, body: str, sha: str | None) -> dict[str, str]:
    """Build the contents-API request body for one day's write.

    Args:
        day: The UTC date being published.
        body: The file contents to write.
        sha: The blob sha being replaced, or ``None`` to create the file.

    Returns:
        The JSON body for the contents-API call.
    """
    commit = {
        "message": f"[usage-log]: last used {day.isoformat()}",
        "content": base64.b64encode(body.encode()).decode(),
    }
    if sha:
        # Omitted on the first write: the API reads its presence as "replace".
        commit["sha"] = sha
    return commit


def _body(day: date) -> str:
    """Render the published file's contents for one date.

    Args:
        day: The UTC date to render.

    Returns:
        The file contents, trailing newline included.
    """
    return json.dumps({"last_used": day.isoformat()}, indent=2) + "\n"


def _decode(content: str) -> str:
    """Decode base64 file contents as the contents API returns them.

    Args:
        content: The base64 payload, which the API wraps at 60 characters.

    Returns:
        The decoded text, empty when there was no payload.
    """
    if not content:
        return ""
    return base64.b64decode(content).decode(errors="replace")


def _client(token: str) -> httpx.AsyncClient:
    """Build the GitHub API client the write goes through.

    Args:
        token: The GitHub token to authenticate with.

    Returns:
        A client scoped to the GitHub API, with the day's write timeout.
    """
    return httpx.AsyncClient(
        base_url=GITHUB_API,
        timeout=REQUEST_TIMEOUT,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )

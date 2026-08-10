[![github repo](https://img.shields.io/badge/github-repo-blue?logo=github)](https://github.com/guyvandam/yt-mcp)
[![python](https://img.shields.io/badge/python-3.13%2B-blue?logo=python&logoColor=white)](https://www.python.org/downloads/)
[![tests](https://img.shields.io/badge/tests-79%20passing-brightgreen?logo=pytest&logoColor=white)](#development)
[![in use](https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fraw.githubusercontent.com%2Fguyvandam%2Fyt-mcp%2Fmain%2Fusage.json&query=%24.last_used&label=in%20use&color=brightgreen)](#usage-signal)

Quiet repo, working server: the last badge is the date this server last served a tool call, published by the server itself. See "Usage signal".

## Setup

- Reads `YOUTUBE_API_KEY` from `.env` at the project root; `.env.example` is the template.
- The key is a Google Cloud API key with "YouTube Data API v3" enabled.
- `uv sync` installs.
- `uv run yt-mcp` serves MCP over stdio.
- `claude mcp add yt -- uv run --directory "$PWD" yt-mcp`, run from the repo root, registers it with Claude Code.

## Deployment

- `main.py` is the entrypoint hosts load, and `fastmcp.json` points at `main.py:mcp`.
- Set the host's entrypoint to `main.py:mcp` — `src/yt_mcp/server.py` holds a bare server instance, because hosts load the entrypoint by file path and never run the package `__init__.py` that registers the tools.
- `YOUTUBE_API_KEY` is read from the environment, so set it as a host secret; there is no `.env` in a deployment.
- Set proxy credentials as host secrets too, or `get_video_transcript` fails on every video while the other tools keep working — a host's IP is in a cloud range, and YouTube blocks those from caption tracks. See "Caption IP blocks".
- `uv run fastmcp inspect main.py:mcp` shows what a host will see, tool count included.
- `USAGE_BADGE_TOKEN` is optional and only useful to this repository's owner; leave it unset. See "Usage signal".

## Tools

- `search_channel_videos` searches one channel's videos by keyword — search MKBHD channel for the latest iphone review.
- `list_channel_videos` lists a channel's videos newest first, filtered by date — everything from the last year.
- `get_video_transcript` extracts a video's transcript with timestamps.
- `get_video_details` returns a video's description, with the external links the creator cited pulled out for citation.
- `find_channel` resolves a channel and returns its stats.

## References

- Channels are given as `@mkbhd`, a channel URL, a `UC...` id, or a channel name.
- Videos are given as an id or any watch / `youtu.be` / shorts URL.
- Date filters take relative offsets (`7d`, `6m`, `1y`), dates (`2025-01-31`), or RFC 3339 timestamps; months and years are 30 and 365 days.

## Transcripts

- Lines are formatted `[[MM:SS]](watch url with &t=seconds) text`, gaining an hour component past an hour — `[[03:15]](https://www.youtube.com/watch?v=ID&t=195) the battery is 17% larger than previous year`.
- The timestamp is a Markdown link that seeks to that moment, so a quoted line carries its own clickable citation; the link points at the start of the merged window, not the last cue in it.
- `chunk_seconds` merges caption cues into windows of that length; `0` keeps YouTube's raw cues.
- `start_seconds` and `end_seconds` narrow a long video to one stretch.
- `languages` picks the track by language code; with none given the video's original spoken language is used.
- Transcripts come from public caption tracks rather than the Data API, so they need no key and cost no quota.

## Caption IP blocks

- Caption tracks are served to the player rather than to the Data API, so YouTube judges the request by IP instead of by key: it blocks cloud provider ranges outright, and rate limits any single address that pulls transcripts in bulk. Both surface as `TranscriptBlockedError`, and both are about the caller, not the video.
- A deployment therefore needs a proxy where a local checkout usually does not — the host's address is in a blocked range from the first request.
- `WEBSHARE_PROXY_USERNAME` and `WEBSHARE_PROXY_PASSWORD` route captions through a rotating residential pool; set both. Rotation is what outlasts the rate limit, so this is the option to reach for.
- `YOUTUBE_PROXY_URL` routes them through a single proxy instead, used for `http` and `https` alike. It is simpler, and it gets banned in turn once enough requests come from that one address.
- Webshare wins when both are configured. With neither set, requests go direct.
- The Data API tools are unaffected: they authenticate with the key and never hit this.

## Usage signal

**This is a signalling device for this repository's owner, not a feature of the server. If you are running yt-mcp for yourself, delete it — see "Removing it" below.**

- The problem it solves is a presentation one: a repository whose last commit is months old reads as abandoned, whether or not it is. This publishes the one fact that separates a finished project from a dead one — the date it last did work.
- The middleware notes the UTC date of each tool call and, on the first call of a new date, commits `usage.json` to this repository through the GitHub contents API. The README badge renders that file.
- One write per UTC day, not one per call. A process that has already published today does nothing at all on later calls.
- The date is noted before the tool runs, so a call that ends in an error still counts. The server served a request either way.

### What it records

- One field: `{"last_used": "2026-08-10"}`. A UTC date.
- Not tool names, not arguments, not channel handles, not video ids, not search queries, not call counts, not totals. None of those are collected, so none of them can leak — which matters, because this repository is public and so is `usage.json`.
- It reveals when the server was last used, which cuts both ways: the badge advertises a lapse as plainly as it advertises activity.

### Turning it on

- Unset `USAGE_BADGE_TOKEN` is the default and the recommended state. With no token the middleware is never registered, so nothing in `usage.py` runs and a tool call costs exactly what it costs without the feature.
- With a token set, the signal is on. `USAGE_BADGE_TOKEN` deliberately is not named `GITHUB_TOKEN`: GitHub Actions injects that name automatically, which would switch the signal on inside CI.
- The token is a fine-grained personal access token with **Contents: read and write** on this repository and nothing else. Set it as a host secret next to `YOUTUBE_API_KEY` — it never belongs in the repository, and `.env` is gitignored.
- `REPOSITORY` in `src/yt_mcp/usage.py` names the target. A fork that keeps this module writes to the upstream repository and is refused, which is a reason to delete rather than reconfigure.

### What it costs

- One commit per active day, authored by whoever owns the token, on top of whatever real history the repository has.
- A `contents: write` token inside a running server. Fine-grained tokens cannot be scoped to a single file, so that token can push anything to this repository. That is the trade the feature makes for keeping its log in the repository instead of somewhere else.
- Nothing on the request path. The write runs as a background task; no caller waits on GitHub.

### When it fails

- Every failure is swallowed and logged at warning level. A tool call never fails because the badge did not update.
- A failed write releases the day, so the next tool call tries again. There is no retry loop.
- Two workers racing to publish the same date is a non-event: the second sees the file already current, or gets a stale-sha rejection, and treats either as done.

### Removing it

Five deletions, in any order. Nothing else references any of it.

| Delete | |
| --- | --- |
| `src/yt_mcp/usage.py` | the mechanism |
| `tests/test_usage.py` | its tests |
| the import and `install_usage_signal(server)` call in `_create_server`, `src/yt_mcp/server.py` | unregisters it |
| `usage.json`, and the badge and this section from `README.md` | removes the published date and its docs |
| `USAGE_BADGE_TOKEN` from `.env.example` | removes the last trace |

`httpx` in `pyproject.toml` is there for this feature alone, though it arrives as a `fastmcp` dependency regardless.

## Quota

- The default daily quota is 10,000 units.
- `search_channel_videos` costs 100 units per 50 results, plus 1 to hydrate them.
- `list_channel_videos` walks the channel's uploads playlist and costs 1 unit per 50 videos walked, plus 1 per 50 hydrated.
- `find_channel` and `get_video_details` cost 1 unit.
- `get_video_transcript` costs nothing.
- Channel lookups are memoised for the life of the process.

## Development

- `uv run pytest` runs the suite.
- `lint-py src tests` runs ruff format, ruff check, ty and complexipy.
- The Data API layer is covered against a faked client; only the transcript path touches the network.

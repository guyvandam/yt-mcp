<div align="center">

<a href="#usage-signal"><img alt="server last used" height="46" src="https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fraw.githubusercontent.com%2Fguyvandam%2Fyt-mcp%2Fmain%2Fusage.json&query=%24.last_used&label=server%20last%20used&labelColor=24292f&color=2ea043&style=for-the-badge&logo=youtube&logoColor=white"></a>

**working code** - the server writes last usage date to `usage.json` itself, on its first tool call of each day. A stale commit log here means the code is finished, not abandoned. See [Usage signal](#usage-signal).

</div>

[![github repo](https://img.shields.io/badge/github-repo-blue?logo=github)](https://github.com/guyvandam/yt-mcp)
[![python](https://img.shields.io/badge/python-3.13%2B-blue?logo=python&logoColor=white)](https://www.python.org/downloads/)
[![tests](https://img.shields.io/badge/tests-79%20passing-brightgreen?logo=pytest&logoColor=white)](#development)

## Setup

- Reads `YOUTUBE_API_KEY` from `.env` at the project root; `.env.example` is the template.
- The key is a Google Cloud API key with "YouTube Data API v3" enabled.
- `uv sync` installs.
- `uv run yt-mcp` serves MCP over stdio.
- `claude mcp add yt -- uv run --directory "$PWD" yt-mcp`, run from the repo root, registers it with Claude Code.

## Deployment

- designed to by deployed on *Prefect Horizon* but YouTube api blocks servers IPs for the transcript fetch.
- personally running locally to avoid setting up proxy.

## Tools

- `search_channel_videos` searches one channel's videos by keyword - search MKBHD channel for the latest iphone review.
- `list_channel_videos` lists a channel's videos newest first, filtered by date - everything from the last year.
- `get_video_transcript` extracts a video's transcript with timestamps.
- `get_video_details` returns a video's description, with the external links the creator cited pulled out for citation.
- `find_channel` resolves a channel and returns its stats.

## References

- Channels are given as `@mkbhd`, a channel URL, a `UC...` id, or a channel name.
- Videos are given as an id or any watch / `youtu.be` / shorts URL.
- Date filters take relative offsets (`7d`, `6m`, `1y`), dates (`2025-01-31`), or RFC 3339 timestamps; months and years are 30 and 365 days.

## Transcripts

- Lines are formatted `[[MM:SS]](watch url with &t=seconds) text`, gaining an hour component past an hour - `[[03:15]](https://www.youtube.com/watch?v=ID&t=195) the battery is 17% larger than previous year`.
- The timestamp is a Markdown link that seeks to that moment, so a quoted line carries its own clickable citation; the link points at the start of the merged window, not the last cue in it.
- `chunk_seconds` merges caption cues into windows of that length; `0` keeps YouTube's raw cues.
- `start_seconds` and `end_seconds` narrow a long video to one stretch.
- `languages` picks the track by language code; with none given the video's original spoken language is used.
- Transcripts come from public caption tracks rather than the Data API, so they need no key and cost no quota.

## Caption IP blocks

- Caption tracks are served to the player rather than to the Data API, so YouTube judges the request by IP instead of by key: it blocks cloud provider ranges outright, and rate limits any single address that pulls transcripts in bulk. Both surface as `TranscriptBlockedError`, and both are about the caller, not the video.


## Usage signal

**This is a signalling device. Not a feature of the server. If you are running yt-mcp for yourself, delete it - see "Removing it" below.**

- The problem it solves is a presentation one: a repository whose last commit is months old reads as abandoned, whether or not it is.
- The middleware notes the UTC date of each tool call and, on the first call of a new date, commits `usage.json` to this repository through the GitHub contents API. The README badge renders that file.
- One write per UTC day, not one per call. 
- **records one field**: `{"last_used": "2026-08-10"}`. A UTC date.

### Turning it on

- Unset `USAGE_BADGE_TOKEN` is the default and the recommended state. With no token the middleware is never registered, so nothing in `usage.py` runs and a tool call costs exactly what it costs without the feature.
- With a token set, the signal is on. `USAGE_BADGE_TOKEN` deliberately is not named `GITHUB_TOKEN`: GitHub Actions injects that name automatically, which would switch the signal on inside CI.
- The token is a fine-grained personal access token with **Contents: read and write** on this repository and nothing else. Set it as a host secret next to `YOUTUBE_API_KEY` - it never belongs in the repository, and `.env` is gitignored.
- `REPOSITORY` in `src/yt_mcp/usage.py` names the target. A fork that keeps this module writes to the upstream repository and is refused, which is a reason to delete rather than reconfigure.


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
nnel lookups are memoised for the life of the process.

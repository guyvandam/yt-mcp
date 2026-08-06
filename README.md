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

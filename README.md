## Setup

- Reads `YOUTUBE_API_KEY` from `.env` at the project root; `.env.example` is the template.
- The key is a Google Cloud API key with "YouTube Data API v3" enabled.
- `uv sync` installs.
- `uv run yt-mcp` serves MCP over stdio.
- `claude mcp add yt -- uv run --directory "$PWD" yt-mcp`, run from the repo root, registers it with Claude Code.

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

- Lines are formatted `[MM:SS] text`, gaining an hour component past an hour — `[03:15] the battery is 17% larger than previous year`.
- `chunk_seconds` merges caption cues into windows of that length; `0` keeps YouTube's raw cues.
- `start_seconds` and `end_seconds` narrow a long video to one stretch.
- `languages` picks the track by language code; with none given the video's original spoken language is used.
- Transcripts come from public caption tracks rather than the Data API, so they need no key and cost no quota.

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

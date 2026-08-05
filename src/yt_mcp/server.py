"""The MCP server instance that the tool modules register against."""

from fastmcp import FastMCP

mcp: FastMCP = FastMCP(
    name="yt-mcp",
    instructions=(
        "Search YouTube channels, list their videos with date filters, and read "
        "video descriptions and timestamped transcripts.\n"
        "- Channels can be given as a handle (@mkbhd), a URL, a UC... id, or a name.\n"
        "- Videos can be given as an id or any watch / youtu.be / shorts URL.\n"
        "- Date filters accept relative offsets (7d, 6m, 1y), dates (2025-01-31) "
        "or RFC 3339 timestamps.\n"
        "- Use search_channel_videos to find a video, then get_video_transcript for "
        "what was said and when, and get_video_details for the description and the "
        "links the creator cited."
    ),
)

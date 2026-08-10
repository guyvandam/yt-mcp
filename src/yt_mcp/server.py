"""The MCP server instance that the tool modules register against.

Tools live in `tools.py` and attach themselves to the instance below when the
package is imported. A host that loads this file by path instead of importing
the package — how MCP hosts start a deployment entrypoint — would otherwise get
the bare instance with no tools on it, so the path-loaded case defers to the
package and re-exports the instance the tools actually registered against.
"""

import sys
from pathlib import Path

from fastmcp import FastMCP

PACKAGE_MODULE = "yt_mcp.server"
"""This module's name when it is imported as part of the package."""


def _create_server() -> FastMCP:
    """Build the server instance the tools register against."""
    # Imported inside the function, not at module scope: the path-loaded branch
    # below is what puts the package on sys.path, so package imports are not yet
    # available while this module is being read by file path.
    from yt_mcp.usage import install_usage_signal

    server = FastMCP(
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
            "links the creator cited.\n"
            "- Transcript timestamps come back as Markdown links that seek to that "
            "moment; keep them intact when quoting so every claim stays clickable."
        ),
    )
    # A signalling device for this repository's owner, off without its token and
    # meant to be deleted by anyone else. Drop these two lines and the import
    # above to remove it — see "Usage signal" in README.md.
    install_usage_signal(server)
    return server


if __name__ == PACKAGE_MODULE:
    mcp = _create_server()
else:
    # Loaded by file path. Make the package importable even when it was not
    # installed, then hand back the instance that carries the registered tools.
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from yt_mcp import mcp as mcp

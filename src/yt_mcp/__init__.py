"""YouTube MCP server — channel search, video listing, transcripts and descriptions."""

from yt_mcp import tools as tools  # noqa: F401 — importing registers the MCP tools
from yt_mcp.server import mcp

__all__ = ["mcp", "tools"]

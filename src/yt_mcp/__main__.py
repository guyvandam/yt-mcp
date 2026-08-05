"""Console entry point: run the server over stdio."""

from yt_mcp import mcp


def main() -> None:
    """Start the MCP server on stdio."""
    mcp.run()


if __name__ == "__main__":
    main()

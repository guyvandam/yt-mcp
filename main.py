"""Deployment entrypoint: the server with every tool registered.

Hosts load this file by path rather than importing it as part of the package, so
the import below is what runs `yt_mcp/__init__.py` and registers the tools.
Pointing a host straight at `src/yt_mcp/server.py` yields a server that connects
and advertises zero tools.
"""

from yt_mcp import mcp

__all__ = ["mcp"]


if __name__ == "__main__":
    mcp.run()

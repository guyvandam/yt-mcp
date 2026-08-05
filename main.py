"""Deployment entrypoint: the server with every tool registered.

Hosts load this file by path rather than importing it as part of the package, so
the import below is what runs `yt_mcp/__init__.py` and registers the tools.
Pointing a host straight at `src/yt_mcp/server.py` yields a server that connects
and advertises zero tools.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from yt_mcp import mcp  # noqa: E402 — the path above makes this import work uninstalled

__all__ = ["mcp"]


if __name__ == "__main__":
    mcp.run()

"""Tests that the deployed entrypoint exposes the tools.

A host such as Prefect Horizon loads the entrypoint file by path instead of
importing it as part of the package, which skips `yt_mcp/__init__.py` and so
skips tool registration. These tests load it the same way to catch that.
"""

import asyncio
import importlib.util
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
EXPECTED_TOOLS = {
    "find_channel",
    "search_channel_videos",
    "list_channel_videos",
    "get_video_transcript",
    "get_video_details",
}


@pytest.fixture(scope="module")
def deployment_config() -> dict:
    """The fastmcp.json a host reads to find the server object."""
    return json.loads((REPO_ROOT / "fastmcp.json").read_text())


def load_by_path(path: Path, attribute: str):
    """Load a module from its file path and return one of its attributes."""
    spec = importlib.util.spec_from_file_location(f"_probe_{path.stem}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return getattr(module, attribute)


def test_configured_entrypoint_registers_every_tool(deployment_config: dict) -> None:
    """Path-loading the configured entrypoint yields a server with the tools."""
    source = deployment_config["source"]
    server = load_by_path(REPO_ROOT / source["path"], source["entrypoint"])

    tools = asyncio.run(server.list_tools())

    assert {tool.name for tool in tools} == EXPECTED_TOOLS

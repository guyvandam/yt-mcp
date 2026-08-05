"""Environment-backed configuration."""

import os
from dataclasses import dataclass
from functools import lru_cache

from dotenv import find_dotenv, load_dotenv

from yt_mcp.errors import MissingApiKeyError

API_KEY_ENV = "YOUTUBE_API_KEY"
"""Environment variable holding the Google Cloud YouTube Data API v3 key."""


@dataclass(frozen=True, slots=True)
class Settings:
    """Resolved runtime settings."""

    api_key: str


@lru_cache(maxsize=1)
def settings() -> Settings:
    """Load settings from the environment, falling back to a .env file.

    The .env file is looked up from the working directory upwards, so the server
    works the same whether it runs from a checkout or from an installed package.
    Variables already set in the environment always win.

    Returns:
        The resolved settings.

    Raises:
        MissingApiKeyError: If no API key is present in the environment.
    """
    load_dotenv(find_dotenv(usecwd=True))
    api_key = os.environ.get(API_KEY_ENV, "").strip()
    if not api_key:
        raise MissingApiKeyError(API_KEY_ENV)
    return Settings(api_key=api_key)

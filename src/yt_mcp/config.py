"""Environment-backed configuration."""

import os
from dataclasses import dataclass
from functools import lru_cache

from dotenv import find_dotenv, load_dotenv
from youtube_transcript_api.proxies import (
    GenericProxyConfig,
    ProxyConfig,
    WebshareProxyConfig,
)

from yt_mcp.errors import MissingApiKeyError

API_KEY_ENV = "YOUTUBE_API_KEY"
"""Environment variable holding the Google Cloud YouTube Data API v3 key."""

PROXY_URL_ENV = "YOUTUBE_PROXY_URL"
"""Environment variable holding a proxy URL for caption requests."""

WEBSHARE_USERNAME_ENV = "WEBSHARE_PROXY_USERNAME"
"""Environment variable holding the Webshare residential proxy username."""

WEBSHARE_PASSWORD_ENV = "WEBSHARE_PROXY_PASSWORD"  # noqa: S105 — a variable name
"""Environment variable holding the Webshare residential proxy password."""


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
    api_key = _env(API_KEY_ENV)
    if not api_key:
        raise MissingApiKeyError(API_KEY_ENV)
    return Settings(api_key=api_key)


@lru_cache(maxsize=1)
def proxy_config() -> ProxyConfig | None:
    """Resolve the proxy that caption requests go through, if any.

    YouTube serves caption tracks to residential IPs and blocks the datacenter
    IPs a host runs on, so a deployment needs a proxy where a local checkout
    needs none. Webshare wins when its credentials are present, because its pool
    rotates residential exit IPs and a single fixed proxy eventually gets banned.

    Returns:
        The proxy configuration, or ``None`` to reach YouTube directly.
    """
    username = _env(WEBSHARE_USERNAME_ENV)
    password = _env(WEBSHARE_PASSWORD_ENV)
    if username and password:
        return WebshareProxyConfig(proxy_username=username, proxy_password=password)

    url = _env(PROXY_URL_ENV)
    if url:
        # One URL covers both schemes: the proxy is the hop, not the destination.
        return GenericProxyConfig(http_url=url, https_url=url)
    return None


def _env(name: str) -> str:
    """Read one environment variable, falling back to a .env file.

    Args:
        name: The variable to read.

    Returns:
        Its trimmed value, empty when unset or blank. A host secret left empty
        counts as unset rather than as a configured empty value.
    """
    load_dotenv(find_dotenv(usecwd=True))
    return os.environ.get(name, "").strip()

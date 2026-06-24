"""Optional outbound proxy seam for all fetch tiers.

When PROXY_URL is not set (the default), every method returns None and every
tier fetches over the host's direct egress, unchanged.  When PROXY_URL is set,
the helper methods return the proxy dict in the format each tier expects:

  - curl_cffi:       {"http": url, "https": url}
  - Playwright:      {"server": url} (may include username/password keys)
  - FlareSolverr:    {"url": url}   (the 'proxy' field inside the request JSON)
"""

from typing import Any

from src.config.config import settings


class ProxyProvider:
    """Reads proxy configuration once from settings and provides per-tier helpers."""

    def __init__(self) -> None:
        self._url: str | None = settings.PROXY_URL or None

    @property
    def enabled(self) -> bool:
        return self._url is not None

    def for_curl_cffi(self) -> dict[str, str] | None:
        """Return proxies dict suitable for curl_cffi's ``proxies=`` kwarg, or None."""
        if self._url is None:
            return None
        return {"http": self._url, "https": self._url}

    def for_playwright(self) -> dict[str, str] | None:
        """Return proxy dict suitable for Playwright's ``proxy=`` context kwarg, or None."""
        if self._url is None:
            return None
        return {"server": self._url}

    def for_flaresolverr(self) -> dict[str, Any] | None:
        """Return proxy dict for FlareSolverr's ``proxy`` payload field, or None."""
        if self._url is None:
            return None
        return {"url": self._url}


proxy_provider = ProxyProvider()

"""Optional outbound proxy seam for all fetch tiers.

When PROXY_URL is not set (the default), every method returns None and every
tier fetches over the host's direct egress, unchanged.  When PROXY_URL is set,
the helper methods return the proxy dict in the format each tier expects:

  - curl_cffi:       {"http": url, "https": url}
  - Playwright:      {"server": url} (may include username/password keys)

The same abstraction offers the customer-supplied crawl proxy
CRAWL_PROXY_URL. It is used only by crawl jobs, never by single
reads: the crawl worker runs every fetch inside ``crawl_proxy()``, and inside
that context the helpers serve the crawl proxy whenever it is set, ahead of
PROXY_URL. Single reads never enter the context and keep using PROXY_URL
only. The project never runs a proxy.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from urllib.parse import urlparse

from src.config.config import settings

_crawl_mode: ContextVar[bool] = ContextVar("crawl_proxy_mode", default=False)


@contextmanager
def crawl_proxy() -> Iterator[None]:
    """Mark the current context as a crawl fetch."""
    token = _crawl_mode.set(True)
    try:
        yield
    finally:
        _crawl_mode.reset(token)


def _crawl_url() -> str | None:
    url = settings.CRAWL_PROXY_URL or ""
    if url and _crawl_mode.get():
        return url
    return None


def _playwright_server(url: str) -> dict[str, str]:
    parsed = urlparse(url)
    proxy: dict[str, str] = {"server": url}
    if parsed.username is not None:
        proxy["username"] = parsed.username
    if parsed.password is not None:
        proxy["password"] = parsed.password
    return proxy


class ProxyProvider:
    """Reads proxy configuration once from settings and provides per-tier helpers."""

    def __init__(self) -> None:
        self._url: str | None = settings.PROXY_URL or None

    @property
    def enabled(self) -> bool:
        return self._url is not None

    def for_curl_cffi(self) -> dict[str, str] | None:
        """Return proxies dict suitable for curl_cffi's ``proxies=`` kwarg, or None."""
        crawl = _crawl_url()
        if crawl is not None:
            return {"http": crawl, "https": crawl}
        if self._url is None:
            return None
        return {"http": self._url, "https": self._url}

    def for_playwright(self) -> dict[str, str] | None:
        """Return proxy dict suitable for Playwright's ``proxy=`` context kwarg, or None."""
        crawl = _crawl_url()
        if crawl is not None:
            return _playwright_server(crawl)
        if self._url is None:
            return None
        return _playwright_server(self._url)


proxy_provider = ProxyProvider()

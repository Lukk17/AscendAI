"""Guarded conditional fetch of the crawl jobs (design D4 and D6).

The recrawl probe sends ``If-None-Match`` and ``If-Modified-Since`` through
the same guard and connect-time pinning as a single read, so a 304 answer
costs one light request and the page file is copied forward without any
page bytes passing the service. Like every crawl fetch it runs inside the
crawl proxy context of the worker (design D7).
"""

import logging
from dataclasses import dataclass

from ascend_python_common.uri_guard import FetchPolicy, UnsafeUriError, check_fetch_uri
from curl_cffi import CurlOpt, requests

from src.config.config import settings
from src.fetch.pinned_fetch import _resolve_entries, follow_pinned_redirects, make_send_hop
from src.proxy.proxy_provider import proxy_provider

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ConditionalProbe:
    status: int | None
    etag: str | None
    last_modified: str | None


def _fetch_policy() -> FetchPolicy:
    return FetchPolicy(
        allowed_hosts=tuple(settings.ALLOWED_PRIVATE_HOSTS),
        file_root=None,
        max_redirect_hops=settings.FETCH_MAX_REDIRECT_HOPS,
    )


async def conditional_probe(
    url: str, *, etag: str | None = None, last_modified: str | None = None
) -> ConditionalProbe:
    """Send a conditional GET and answer its status with fresh validators.

    A ``None`` status means the probe itself failed: no request answered,
    or the guard refused a hop. The caller reads the page unconditionally.
    """
    policy = _fetch_policy()
    try:
        first = await check_fetch_uri(url, policy)
    except UnsafeUriError:
        return ConditionalProbe(None, None, None)
    headers: dict[str, str] = {}
    if etag is not None:
        headers["If-None-Match"] = etag
    if last_modified is not None:
        headers["If-Modified-Since"] = last_modified
    extra: dict[str, object] = {}
    proxies = proxy_provider.for_curl_cffi()
    if proxies is not None:
        extra["proxies"] = proxies
    try:
        async with requests.AsyncSession(impersonate="chrome120") as session:
            send_hop = make_send_hop(session, headers, {}, settings.EXTRACT_TIMEOUT, extra)
            try:
                final = await follow_pinned_redirects(first, policy, send_hop)
            except UnsafeUriError:
                return ConditionalProbe(None, None, None)
    except Exception as exc:
        logger.warning("crawl: conditional probe of %s failed: %s", url, exc)
        return ConditionalProbe(None, None, None)
    response = final.answer
    return ConditionalProbe(
        response.status_code,
        response.headers.get("etag"),
        response.headers.get("last-modified"),
    )


async def head_validators(url: str) -> tuple[str | None, str | None]:
    """Read the cache validators of *url* with a guarded HEAD request.

    A fresh page write stores these in the recrawl state, so the next job of
    the same scope sends conditional requests (design D6). Answers
    ``(None, None)`` when the guard refuses, the request fails, or the answer
    is not a 200.
    """
    policy = _fetch_policy()
    try:
        first = await check_fetch_uri(url, policy)
    except UnsafeUriError:
        return None, None
    kwargs: dict[str, object] = {}
    proxies = proxy_provider.for_curl_cffi()
    if proxies is not None:
        kwargs["proxies"] = proxies
    try:
        async with requests.AsyncSession(impersonate="chrome120") as session:
            session.curl_options[CurlOpt.RESOLVE] = _resolve_entries(first)
            response = await session.head(
                first.url, timeout=settings.EXTRACT_TIMEOUT, allow_redirects=False, **kwargs
            )
    except Exception as exc:
        logger.warning("crawl: HEAD probe of %s failed: %s", url, exc)
        return None, None
    if response.status_code != 200:
        return None, None
    return response.headers.get("etag"), response.headers.get("last-modified")

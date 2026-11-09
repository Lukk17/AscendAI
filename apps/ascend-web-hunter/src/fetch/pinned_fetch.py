"""Pinned curl_cffi hop for the guarded redirect loop.

One function opens no session of its own: the caller opens the
``curl_cffi`` session, this module pins each checked hop through
``CURLOPT_RESOLVE`` and hands the loop to the library's
``follow_guarded_redirects``. It writes no redirect loop of its own.
"""

import asyncio
import ipaddress
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager, suppress
from typing import Any, Final
from urllib.parse import urlsplit

import tldextract
from ascend_python_common.uri_guard import (
    FetchPolicy,
    FetchTarget,
    HopAnswer,
    follow_guarded_redirects,
)
from curl_cffi import CurlOpt

NO_COMPRESSION_HEADERS: Final[dict[str, str]] = {"Accept-Encoding": "identity"}

_HTTPS_SCHEME: Final[str] = "https"
_STREAM_STOP_GRACE_SECONDS: Final[float] = 1.0

_COOKIE_SITE_EXTRACT = tldextract.TLDExtract(
    suffix_list_urls=(), cache_dir=None, include_psl_private_domains=True
)


def _resolve_entries(target: FetchTarget) -> list[str]:
    if target.host is None or target.port is None:
        return []
    try:
        ipaddress.ip_address(target.host)
    except ValueError:
        pass
    else:
        return []
    if not target.addresses:
        return []
    rendered = ",".join(f"[{a}]" if ":" in a else a for a in target.addresses)
    return [f"{target.host}:{target.port}:{rendered}"]


async def follow_pinned_redirects(
    first: FetchTarget,
    policy: FetchPolicy,
    send_request: Callable[[FetchTarget], Awaitable[HopAnswer[Any]]],
) -> HopAnswer[Any]:
    """Follow the guarded redirect chain for one already-checked *first* hop."""
    return await follow_guarded_redirects(first, policy, send_request)


async def stop_stream(response: Any) -> None:
    """Abort a streamed curl_cffi transfer and close it without draining the rest of the body."""
    response.quit_now.set()
    with suppress(TimeoutError):
        async with asyncio.timeout(_STREAM_STOP_GRACE_SECONDS):
            await response.aclose()


@asynccontextmanager
async def stopping_hops(
    send_hop: Callable[[FetchTarget], Awaitable[HopAnswer[Any]]],
) -> AsyncIterator[Callable[[FetchTarget], Awaitable[HopAnswer[Any]]]]:
    """Wrap a streamed *send_hop* so each answer is stopped, undrained, before the next hop or on exit."""
    latest: Any = None

    async def stop_latest() -> None:
        nonlocal latest
        response, latest = latest, None
        if response is not None:
            await stop_stream(response)

    async def tracked_hop(target: FetchTarget) -> HopAnswer[Any]:
        nonlocal latest
        await stop_latest()
        answer = await send_hop(target)
        latest = answer.answer
        return answer

    try:
        yield tracked_hop
    finally:
        await stop_latest()


def leave_bodies_undecoded(session: Any) -> None:
    """Stop libcurl inflating response bodies on *session*, so a byte cap counts the bytes on the wire."""
    session.curl_options[CurlOpt.HTTP_CONTENT_DECODING] = 0


def _cookie_site(url: str) -> str:
    host = urlsplit(url).hostname or ""
    extracted = _COOKIE_SITE_EXTRACT(host)
    if extracted.domain and extracted.suffix:
        return f"{extracted.domain}.{extracted.suffix}"

    return host


def cookies_stay_on_site(first_url: str) -> Callable[[str], bool]:
    """Build the check that a hop is on the site of *first_url*, and on https when it was.

    The site is the registrable domain under the public and the private suffix lists, so
    two owners of one private suffix such as github.io are two sites.
    """
    site = _cookie_site(first_url)
    needs_https = urlsplit(first_url).scheme == _HTTPS_SCHEME

    def is_on_site(hop_url: str) -> bool:
        if needs_https and urlsplit(hop_url).scheme != _HTTPS_SCHEME:
            return False

        return _cookie_site(hop_url) == site

    return is_on_site


def make_send_hop(
    session: Any,
    headers: dict[str, str],
    cookies: dict[str, str],
    timeout_seconds: float,
    extra_kwargs: dict[str, Any],
    send_cookies_to: Callable[[str], bool],
) -> Callable[[FetchTarget], Awaitable[HopAnswer[Any]]]:
    """Build the curl_cffi hop that pins each target and sends *cookies* where *send_cookies_to* allows."""

    async def send_hop(target: FetchTarget) -> HopAnswer[Any]:
        session.curl_options[CurlOpt.RESOLVE] = _resolve_entries(target)
        hop_kwargs: dict[str, Any] = dict(extra_kwargs)
        hop_cookies = cookies
        if cookies and not send_cookies_to(target.url):
            session.cookies.clear()
            hop_cookies = {}
        response = await session.get(
            target.url,
            headers=headers,
            cookies=hop_cookies,
            timeout=timeout_seconds,
            allow_redirects=False,
            **hop_kwargs,
        )
        return HopAnswer(
            status=response.status_code,
            location=response.headers.get("location"),
            answer=response,
        )

    return send_hop

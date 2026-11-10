"""Guarded fetches of the crawl jobs: the recrawl probe and the robots.txt fetch."""

import asyncio
import logging
from dataclasses import dataclass
from typing import Final

from ascend_python_common.uri_guard import UnsafeUriError, check_fetch_uri
from curl_cffi import requests

from src.config.config import settings
from src.fetch.capped_inflate import ContentDecodingError, read_inflated_prefix
from src.fetch.pinned_fetch import (
    NO_COMPRESSION_HEADERS,
    cookies_stay_on_site,
    follow_pinned_redirects,
    leave_bodies_undecoded,
    make_send_hop,
    stopping_hops,
)
from src.observability.safe_address import address_without_query, exception_text_without_queries
from src.proxy.proxy_provider import proxy_provider
from src.reader.browser_guard import web_hunter_fetch_policy
from src.reader.cloudflare.cookie_manager import cookie_manager

logger = logging.getLogger(__name__)

CRAWL_USER_AGENT: Final[str] = "ascend-web-hunter-crawl"

_SUCCESS_FLOOR: Final[int] = 200
_REDIRECT_FLOOR: Final[int] = 300


@dataclass(frozen=True)
class ConditionalProbe:
    status: int | None
    etag: str | None
    last_modified: str | None


@dataclass(frozen=True, slots=True)
class RobotsFetch:
    """The final answer to one robots.txt fetch. A None *status* means no server answered."""

    status: int | None
    body: str = ""


def _hop_extra(*, stream: bool) -> dict[str, object]:
    extra: dict[str, object] = {"stream": True} if stream else {}
    proxies = proxy_provider.for_curl_cffi()
    if proxies is not None:
        extra["proxies"] = proxies
    return extra


async def conditional_probe(
    url: str,
    *,
    etag: str | None = None,
    last_modified: str | None = None,
    profile: str | None = None,
) -> ConditionalProbe:
    """Send a conditional GET and answer its status with fresh validators.

    A ``None`` status means the probe itself failed: no request answered,
    or the guard refused a hop. The caller reads the page unconditionally.
    """
    policy = web_hunter_fetch_policy()
    try:
        first = await check_fetch_uri(url, policy)
    except UnsafeUriError:
        return ConditionalProbe(None, None, None)
    extra = _hop_extra(stream=True)
    try:
        cookies = await cookie_manager.get_flat_cookies(url, profile)
        headers = await _probe_headers(url, profile, etag, last_modified)
        async with requests.AsyncSession(impersonate="chrome120") as session:
            leave_bodies_undecoded(session)
            send_hop = make_send_hop(
                session, headers, cookies, settings.EXTRACT_TIMEOUT, extra, cookies_stay_on_site(url)
            )
            async with asyncio.timeout(settings.EXTRACT_TIMEOUT), stopping_hops(send_hop) as tracked_hop:
                try:
                    final = await follow_pinned_redirects(first, policy, tracked_hop)
                except UnsafeUriError:
                    return ConditionalProbe(None, None, None)
                response = final.answer
                return ConditionalProbe(
                    response.status_code,
                    response.headers.get("etag"),
                    response.headers.get("last-modified"),
                )
    except Exception as exc:
        logger.warning(
            "crawl: conditional probe of %s failed: %s",
            address_without_query(url),
            exception_text_without_queries(exc),
        )
        return ConditionalProbe(None, None, None)


async def _probe_headers(
    url: str, profile: str | None, etag: str | None, last_modified: str | None
) -> dict[str, str]:
    headers: dict[str, str] = {}
    stored_ua = await cookie_manager.get_user_agent(url, profile)
    if stored_ua is not None:
        headers["User-Agent"] = stored_ua
    if etag is not None:
        headers["If-None-Match"] = etag
    if last_modified is not None:
        headers["If-Modified-Since"] = last_modified
    return headers


async def fetch_robots_txt(url: str, profile: str | None) -> RobotsFetch:
    """Fetch one robots.txt with the session of *profile*, following redirects, and answer status and body.

    Reading stops at CRAWL_ROBOTS_MAX_BYTES and the body keeps the whole lines
    before it. The file is requested uncompressed and left undecoded by libcurl,
    and a body the server compressed anyway is inflated here within the same
    limit. A connection or transport failure, or a success that cannot be
    decoded, answers a None status, which the caller reads as an unreachable file.

    Raises:
        UnsafeUriError: when the guard refuses the address or a redirect hop.
    """
    policy = web_hunter_fetch_policy()
    first = await check_fetch_uri(url, policy)
    cookies = await cookie_manager.get_flat_cookies(url, profile)
    stored_ua = await cookie_manager.get_user_agent(url, profile)
    headers = {"User-Agent": stored_ua or CRAWL_USER_AGENT, **NO_COMPRESSION_HEADERS}
    extra = _hop_extra(stream=True)
    try:
        async with requests.AsyncSession(impersonate="chrome120") as session:
            leave_bodies_undecoded(session)
            send_hop = make_send_hop(
                session, headers, cookies, settings.EXTRACT_TIMEOUT, extra, cookies_stay_on_site(url)
            )
            async with stopping_hops(send_hop) as tracked_hop:
                final = await follow_pinned_redirects(first, policy, tracked_hop)
                status = final.answer.status_code
                try:
                    raw, cut = await read_inflated_prefix(final.answer, settings.CRAWL_ROBOTS_MAX_BYTES)
                except ContentDecodingError as exc:
                    logger.warning(
                        "crawl: robots.txt %s has a body that cannot be decoded: %s",
                        address_without_query(url),
                        exc,
                    )
                    return RobotsFetch(None if _SUCCESS_FLOOR <= status < _REDIRECT_FLOOR else status)
            if cut:
                logger.warning(
                    "crawl: robots.txt %s is larger than %d bytes, the rest is ignored",
                    address_without_query(url),
                    settings.CRAWL_ROBOTS_MAX_BYTES,
                )
                raw = raw[: max(raw.rfind(b"\n"), raw.rfind(b"\r")) + 1]
            return RobotsFetch(status, raw.decode("utf-8-sig", errors="replace"))
    except requests.exceptions.RequestException as exc:
        logger.warning(
            "crawl: robots.txt fetch of %s failed: %s",
            address_without_query(url),
            exception_text_without_queries(exc),
        )
        return RobotsFetch(None)

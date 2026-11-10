"""Bounded byte fetch for routed files.

``stream_to_file`` downloads one URL to a temporary file without ever holding
the whole body in memory. The first URL and every redirect hop pass the same
guard the read tiers face, each hop pinned through ``CURLOPT_RESOLVE`` by
``src.fetch.pinned_fetch``, and the redirect chain itself is the library's
``follow_guarded_redirects``. This module writes no redirect loop of its own.

The body streams in chunks with ``stream=True``: a final answer outside 2xx is
refused before one body byte is read, a declared ``Content-Length`` above
*max_bytes* is refused the same way, also when the server closes before
sending a body and curl fails the transfer, and a body that passes the limit
mid-stream is stopped and its partial file deleted. libcurl decoding is off,
so a compressed body is inflated here and the limit counts the inflated bytes,
and a compressed file that stops before its content coding ends is a failure.
A written file that the caller does not receive is deleted on every exit.
Each redirect answer is stopped, undrained, before the next hop is sent.
"""

import logging
import tempfile
from pathlib import Path
from typing import Any

from ascend_python_common.uri_guard import (
    FetchPolicy,
    FetchTarget,
    HopAnswer,
    UnsafeUriError,
    check_fetch_uri,
    follow_guarded_redirects,
)
from curl_cffi import CurlOpt, requests
from curl_cffi.requests.exceptions import RequestException

from src.fetch.capped_inflate import BodyOverLimitError, declared_content_length, drain_inflated
from src.fetch.pinned_fetch import _resolve_entries, leave_bodies_undecoded, stopping_hops
from src.observability.safe_address import address_without_query

logger = logging.getLogger(__name__)

_SUCCESS_STATUSES = range(200, 300)


class DocumentTooLargeError(Exception):
    """The answer declares or delivers more bytes than the cap allows."""


def _discard_spool(path: Path) -> None:
    path.unlink(missing_ok=True)


async def stream_to_file(
    url: str,
    max_bytes: int,
    *,
    policy: FetchPolicy,
    headers: dict[str, str] | None = None,
    cookies: dict[str, str] | None = None,
    timeout_seconds: float = 30.0,
) -> Path | None:
    """Fetch *url* to a temporary file capped at *max_bytes*.

    Returns the file path when a 2xx body fits the cap, and None when the
    guard refuses a hop, the final answer is not 2xx, the chain runs past the
    hop budget, or the transport fails. A partial file never survives.

    Raises:
        DocumentTooLargeError: a 2xx answer declares or delivers more than *max_bytes*.
    """
    safe_url = address_without_query(url)
    try:
        first = await check_fetch_uri(url, policy)
    except UnsafeUriError:
        logger.warning("byte_fetch: SSRF guard refused %s", safe_url)
        return None

    sent_headers: dict[str, str] = headers or {}
    sent_cookies: dict[str, str] = cookies or {}
    spool: Path | None = None
    delivered = False

    try:
        async with requests.AsyncSession(impersonate="chrome120") as session:
            leave_bodies_undecoded(session)

            async def send_hop(target: FetchTarget) -> HopAnswer[Any]:
                session.curl_options[CurlOpt.RESOLVE] = _resolve_entries(target)
                try:
                    response = await session.request(
                        "GET",
                        target.url,
                        headers=sent_headers,
                        cookies=sent_cookies,
                        timeout=timeout_seconds,
                        allow_redirects=False,
                        stream=True,
                    )
                except RequestException as failure:
                    _refuse_declared_oversize(failure.response, max_bytes, safe_url)
                    raise
                return HopAnswer(
                    status=response.status_code,
                    location=response.headers.get("location"),
                    answer=response,
                )

            async with stopping_hops(send_hop) as tracked_hop:
                final = await follow_guarded_redirects(first, policy, tracked_hop)
                spool = await _drain_final_to_file(final, max_bytes, safe_url)
        delivered = True

        return spool
    except DocumentTooLargeError:
        raise
    except Exception as e:
        logger.warning("byte_fetch failed for URL %s: %s", safe_url, type(e).__name__)
        return None
    finally:
        if spool is not None and not delivered:
            _discard_spool(spool)


def _refuse_declared_oversize(response: Any, max_bytes: int, safe_url: str) -> None:
    """Raise when a 2xx answer declares a body above the cap."""
    if response is None or response.status_code not in _SUCCESS_STATUSES:
        return
    declared = declared_content_length(response.headers)
    if declared is not None and declared > max_bytes:
        logger.warning("byte_fetch refused %s: declared %d bytes above the cap", safe_url, declared)
        raise DocumentTooLargeError(safe_url)


async def _drain_final_to_file(final: HopAnswer[Any], max_bytes: int, safe_url: str) -> Path | None:
    """Write the final hop body to a temp file, honouring the byte cap."""
    response: Any = final.answer
    if response.status_code not in _SUCCESS_STATUSES:
        logger.warning("byte_fetch refused %s: the answer was HTTP %d", safe_url, response.status_code)
        return None
    _refuse_declared_oversize(response, max_bytes, safe_url)
    over = False
    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp_path = Path(tmp.name)
            try:
                await drain_inflated(response, max_bytes, tmp.write, require_whole=True)
            except BodyOverLimitError:
                logger.warning("byte_fetch stopped %s: body passed the cap", safe_url)
                over = True
    except BaseException:
        if tmp_path is not None:
            _discard_spool(tmp_path)
        raise
    if over:
        _discard_spool(tmp_path)
        raise DocumentTooLargeError(safe_url)
    return tmp_path

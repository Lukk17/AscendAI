"""Bounded byte fetch for routed files (design D6).

``stream_to_file`` downloads one URL to a temporary file without ever holding
the whole body in memory. The first URL and every redirect hop pass the same
guard the read tiers face, each hop pinned through ``CURLOPT_RESOLVE`` by
``src.fetch.pinned_fetch``, and the redirect chain itself is the library's
``follow_guarded_redirects``. This module writes no redirect loop of its own.

The body streams in chunks with ``stream=True``: a declared ``Content-Length``
above *max_bytes* is refused before one body byte is read, and a body that
passes the limit mid-stream is stopped and its partial file deleted.
"""

import logging
import tempfile
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from ascend_python_common.startup_banner import strip_user_info
from ascend_python_common.uri_guard import (
    FetchPolicy,
    FetchTarget,
    HopAnswer,
    UnsafeUriError,
    check_fetch_uri,
    follow_guarded_redirects,
)
from curl_cffi import CurlOpt, requests

from src.fetch.pinned_fetch import _resolve_entries

logger = logging.getLogger(__name__)


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

    Returns the file path when the whole body fits the cap, and None when the
    guard refuses a hop, a declared length is already above the cap, the stream
    passes the cap, the chain runs past the hop budget, or the transport fails.
    A partial file never survives: it is deleted before None is returned.
    """
    safe_url = strip_user_info(url)
    try:
        first = await check_fetch_uri(url, policy)
    except UnsafeUriError:
        logger.warning("byte_fetch: SSRF guard refused %s", safe_url)
        return None

    sent_headers: dict[str, str] = headers or {}
    sent_cookies: dict[str, str] = cookies or {}

    try:
        # noinspection PyArgumentList
        async with requests.AsyncSession(impersonate="chrome120") as session:
            open_responses: list[Any] = []

            async def send_hop(target: FetchTarget) -> HopAnswer[Any]:
                session.curl_options[CurlOpt.RESOLVE] = _resolve_entries(target)
                response = await session.request(
                    "GET",
                    target.url,
                    headers=sent_headers,
                    cookies=sent_cookies,
                    timeout=timeout_seconds,
                    allow_redirects=False,
                    stream=True,
                )
                open_responses.append(response)
                return HopAnswer(
                    status=response.status_code,
                    location=response.headers.get("location"),
                    answer=response,
                )

            final = await _follow_and_close_intermediates(first, policy, send_hop, open_responses)
            return await _drain_final_to_file(final, max_bytes, safe_url)
    except Exception as e:
        logger.warning("byte_fetch failed for URL %s: %s", safe_url, strip_user_info(str(e)))
        return None


async def _follow_and_close_intermediates(
    first: FetchTarget,
    policy: FetchPolicy,
    send_hop: Callable[[FetchTarget], Awaitable[HopAnswer[Any]]],
    open_responses: list[Any],
) -> HopAnswer[Any]:
    """Run the library redirect loop, then close every hop but the final one."""
    final = await follow_guarded_redirects(first, policy, send_hop)
    for response in open_responses:
        if response is not final.answer:
            await response.aclose()
    return final


async def _drain_final_to_file(final: HopAnswer[Any], max_bytes: int, safe_url: str) -> Path | None:
    """Write the final hop body to a temp file, honouring the byte cap."""
    response: Any = final.answer
    try:
        raw_length: str | None = response.headers.get("content-length")
        declared: int | None = int(raw_length) if raw_length is not None else None
        if declared is not None and declared > max_bytes:
            logger.warning("byte_fetch refused %s: declared %d bytes above the cap", safe_url, declared)
            return None
        over = False
        try:
            with tempfile.NamedTemporaryFile(delete=False) as tmp:
                tmp_path = Path(tmp.name)
                total = 0
                async for chunk in response.aiter_content():
                    data = bytes(chunk)
                    total += len(data)
                    if total > max_bytes:
                        logger.warning("byte_fetch stopped %s: body passed the cap", safe_url)
                        over = True
                        break
                    tmp.write(data)
        except Exception:
            _discard_spool(tmp_path)
            raise
        if over:
            _discard_spool(tmp_path)
            return None
        return tmp_path
    finally:
        await response.aclose()

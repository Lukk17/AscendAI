"""Pinned curl_cffi hop for the guarded redirect loop (design D6).

One function opens no session of its own: the caller opens the
``curl_cffi`` session, this module pins each checked hop through
``CURLOPT_RESOLVE`` and hands the loop to the library's
``follow_guarded_redirects``. It writes no redirect loop of its own.
"""

import ipaddress
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from ascend_python_common.uri_guard import (
    FetchPolicy,
    FetchTarget,
    HopAnswer,
    follow_guarded_redirects,
)
from curl_cffi import CurlOpt

logger = logging.getLogger(__name__)


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


def make_send_hop(
    session: Any,
    headers: dict[str, str],
    cookies: dict[str, str],
    timeout_seconds: float,
    extra_kwargs: dict[str, Any],
) -> Callable[[FetchTarget], Awaitable[HopAnswer[Any]]]:
    """Build the curl_cffi hop that pins each checked target before sending it."""

    async def send_hop(target: FetchTarget) -> HopAnswer[Any]:
        session.curl_options[CurlOpt.RESOLVE] = _resolve_entries(target)
        hop_kwargs: dict[str, Any] = dict(extra_kwargs)
        response = await session.get(
            target.url,
            headers=headers,
            cookies=cookies,
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

import asyncio
import logging
import re
from collections.abc import Awaitable, Callable, Mapping
from typing import Any, Final

from ascend_python_common.uri_guard import (
    FetchPolicy,
    FetchTarget,
    HopAnswer,
    UnsafeUriError,
    check_fetch_uri,
)
from curl_cffi import requests

from src.api.exceptions import ChallengeDetectedException
from src.config.config import settings
from src.fetch.capped_inflate import read_inflated_body
from src.fetch.pinned_fetch import (
    NO_COMPRESSION_HEADERS,
    _resolve_entries,
    cookies_stay_on_site,
    follow_pinned_redirects,
    leave_bodies_undecoded,
    make_send_hop,
    stopping_hops,
)
from src.observability.safe_address import address_without_query, exception_text_without_queries
from src.proxy.proxy_provider import proxy_provider
from src.reader.browser_guard import web_hunter_fetch_policy
from src.reader.strategies.base_strategy import FetchedHtml

__all__ = ["_resolve_entries", "fetch_with_curl_cffi"]
from src.reader.cloudflare.challenge_detector import ChallengeDetector
from src.reader.cloudflare.challenge_signals import (
    assess,
    log_verdict,
    record_verdict,
    set_cookie_names,
)
from src.reader.cloudflare.cookie_manager import cookie_manager

logger = logging.getLogger(__name__)

_CURL_TIER = "curl_cffi"

_FALLBACK_CHARSET: Final[str] = "utf-8"

_CHARSET_PARAMETER: Final[re.Pattern[str]] = re.compile(r"charset=[\"']?([\w.:-]+)", re.IGNORECASE)

WEB_CHARSETS: Final[frozenset[str]] = frozenset(
    {
        "ascii",
        "us-ascii",
        "utf-8",
        "utf8",
        "utf-16",
        "utf-16be",
        "utf-16le",
        "iso-8859-1",
        "iso_8859-1",
        "iso8859-1",
        "iso-8859-2",
        "iso_8859-2",
        "iso8859-2",
        "iso-8859-3",
        "iso8859-3",
        "iso-8859-4",
        "iso8859-4",
        "iso-8859-5",
        "iso8859-5",
        "iso-8859-6",
        "iso8859-6",
        "iso-8859-7",
        "iso8859-7",
        "iso-8859-8",
        "iso8859-8",
        "iso-8859-9",
        "iso8859-9",
        "iso-8859-10",
        "iso8859-10",
        "iso-8859-11",
        "iso-8859-13",
        "iso8859-13",
        "iso-8859-14",
        "iso8859-14",
        "iso-8859-15",
        "iso8859-15",
        "iso-8859-16",
        "iso8859-16",
        "latin1",
        "latin-1",
        "latin2",
        "cp874",
        "windows-1250",
        "windows-1251",
        "windows-1252",
        "windows-1253",
        "windows-1254",
        "windows-1255",
        "windows-1256",
        "windows-1257",
        "windows-1258",
        "cp932",
        "cp1250",
        "cp1251",
        "cp1252",
        "koi8-r",
        "koi8-u",
        "ibm866",
        "macintosh",
        "tis-620",
        "big5",
        "big5-hkscs",
        "euc-jp",
        "euc-kr",
        "euc_kr",
        "ks_c_5601-1987",
        "cp949",
        "gb2312",
        "gbk",
        "gb18030",
        "iso-2022-jp",
        "shift_jis",
        "shift-jis",
        "sjis",
    }
)

_CODEC_OF_WEB_LABEL: Final[Mapping[str, str]] = {
    "windows-874": "cp874",
    "windows-31j": "cp932",
    "windows-949": "cp949",
}

BodyUnpack = Callable[[bytes, str | None], bytes | None]


async def fetch_with_curl_cffi(
    url: str,
    user_agent_provider: Callable[[], str],
    strategy_label: str,
    profile: str | None = None,
    *,
    max_bytes: int | None = None,
    unpack: BodyUnpack | None = None,
) -> str:
    """
    Shared curl_cffi fetch used by BeautifulSoupStrategy and TrafilaturaStrategy.
    Injects auth+WAF cookies from the session store when present, raises
    ChallengeDetectedException on detected login/WAF walls, returns empty string
    on transport errors and on a first URL the guard refuses.

    Every hop streams with libcurl decoding off, and the body is inflated in
    Python according to its Content-Encoding. A declared length above the limit
    is refused before the body is read, and reading stops once the bytes on the
    wire or the inflated bytes pass the limit. Such a body answers an empty
    string and is logged.

    The limit is *max_bytes* when set, and READ_RESPONSE_MAX_BYTES otherwise.
    With *max_bytes* set the body is requested uncompressed and read as UTF-8
    whatever charset the server declares. With *unpack* set as well, the
    inflated body and its Content-Type pass through it before decoding, and a
    None from it is skipped the same way.

    Without *max_bytes* the impersonated request headers stay as they are and the
    body decodes with the declared charset when it is on WEB_CHARSETS, and as
    UTF-8 otherwise, so a server cannot pick the codec.

    Redirects go through the library's follow_guarded_redirects: each hop's
    Location is resolved against the URL of the hop that returned it, per RFC
    9110 section 10.2.2, checked with the same guard an absolute URL faces, and
    pinned to the checked addresses through CURLOPT_RESOLVE. A hop the guard
    refuses raises UnsafeUriError and no request is sent to it.
    """
    policy = web_hunter_fetch_policy()
    safe_url = address_without_query(url)
    try:
        first = await check_fetch_uri(url, policy)
    except UnsafeUriError:
        logger.warning("%s: SSRF guard refused %s", strategy_label, safe_url)
        return ""

    flat_cookies = await cookie_manager.get_flat_cookies(url, profile)
    stored_ua = await cookie_manager.get_user_agent(url, profile)

    headers: dict[str, str] = {"User-Agent": stored_ua or user_agent_provider()}

    curl_proxies = proxy_provider.for_curl_cffi()

    try:
        # noinspection PyArgumentList
        async with requests.AsyncSession(impersonate="chrome120") as session:
            extra_kwargs: dict[str, Any] = {"stream": True}
            if curl_proxies is not None:
                extra_kwargs["proxies"] = curl_proxies

            leave_bodies_undecoded(session)
            if max_bytes is not None:
                headers.update(NO_COMPRESSION_HEADERS)

            send_hop = make_send_hop(
                session,
                headers,
                flat_cookies,
                settings.EXTRACT_TIMEOUT,
                extra_kwargs,
                cookies_stay_on_site(url),
            )

            async with asyncio.timeout(settings.EXTRACT_TIMEOUT):
                if max_bytes is None:
                    return await _read_capped(
                        first,
                        policy,
                        send_hop,
                        settings.READ_RESPONSE_MAX_BYTES,
                        strategy_label,
                        safe_url,
                        None,
                        _allowed_charset,
                    )
                return await _read_capped(
                    first, policy, send_hop, max_bytes, strategy_label, safe_url, unpack, _always_utf8
                )
    except (ChallengeDetectedException, UnsafeUriError):
        raise
    except Exception as e:
        logger.warning(
            "%s failed to fetch URL %s: %s", strategy_label, safe_url, exception_text_without_queries(e)
        )

        return ""


SendHop = Callable[[FetchTarget], Awaitable[HopAnswer[Any]]]


async def _read_capped(
    first: FetchTarget,
    policy: FetchPolicy,
    send_hop: SendHop,
    max_bytes: int,
    strategy_label: str,
    safe_url: str,
    unpack: BodyUnpack | None,
    charset_of: Callable[[str | None], str],
) -> str:
    async with stopping_hops(send_hop) as tracked_hop:
        try:
            final = await follow_pinned_redirects(first, policy, tracked_hop)
        except UnsafeUriError:
            logger.warning("%s: SSRF guard blocked redirect from %s", strategy_label, safe_url)
            raise

        raw = await read_inflated_body(final.answer, max_bytes)
        content_type = final.answer.headers.get("content-type")
        if raw is not None and unpack is not None:
            raw = unpack(raw, content_type)
        if raw is None:
            logger.warning(
                "%s: body of %s is above the cap of %d bytes, skipped", strategy_label, safe_url, max_bytes
            )
            return ""

        body = raw.decode(charset_of(content_type), errors="replace")

        return await _judged_body(final.answer, body, strategy_label, safe_url)


def _always_utf8(_content_type: str | None) -> str:
    return _FALLBACK_CHARSET


def _allowed_charset(content_type: str | None) -> str:
    declared = _CHARSET_PARAMETER.search(content_type or "")
    label = declared.group(1).lower() if declared else _FALLBACK_CHARSET
    charset = _CODEC_OF_WEB_LABEL.get(label, label)

    return charset if charset in WEB_CHARSETS else _FALLBACK_CHARSET


async def _judged_body(response: Any, body: str, strategy_label: str, safe_url: str) -> FetchedHtml:
    verdict = await asyncio.to_thread(
        assess,
        response.status_code,
        body,
        dict(response.headers),
        set_cookie_names(response.headers),
    )
    record_verdict(verdict, _CURL_TIER)
    log_verdict(verdict, _CURL_TIER, safe_url)

    login = ChallengeDetector.login_wall_verdict(
        verdict, body, requested_url=safe_url, final_url=str(response.url)
    )
    if login is not None:
        logger.warning("%s: Login wall detected on %s", strategy_label, safe_url)
        raise ChallengeDetectedException(login)

    if verdict.wall:
        logger.warning("%s: WAF/Cloudflare block detected on %s", strategy_label, safe_url)
        raise ChallengeDetectedException(verdict)

    response.raise_for_status()

    return FetchedHtml(body, response.headers)

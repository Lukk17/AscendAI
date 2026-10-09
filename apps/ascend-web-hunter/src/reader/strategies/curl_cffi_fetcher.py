import ipaddress
import logging
from collections.abc import Callable
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

from src.api.exceptions import ChallengeDetectedException
from src.config.config import settings
from src.proxy.proxy_provider import proxy_provider
from src.reader.cloudflare.challenge_detector import ChallengeDetector
from src.reader.cloudflare.cookie_manager import cookie_manager

logger = logging.getLogger(__name__)


def _fetch_policy() -> FetchPolicy:
    return FetchPolicy(
        allowed_hosts=tuple(settings.ALLOWED_PRIVATE_HOSTS),
        file_root=None,
        max_redirect_hops=settings.FETCH_MAX_REDIRECT_HOPS,
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


async def fetch_with_curl_cffi(
    url: str,
    user_agent_provider: Callable[[], str],
    strategy_label: str,
    profile: str | None = None,
) -> str:
    """
    Shared curl_cffi fetch used by BeautifulSoupStrategy and TrafilaturaStrategy.
    Injects auth+WAF cookies from the session store when present, raises
    ChallengeDetectedException on detected login/WAF walls, returns empty string
    on transport errors.

    Redirects go through the library's follow_guarded_redirects: each hop's
    Location is resolved against the URL of the hop that returned it, per RFC
    9110 section 10.2.2, checked with the same guard an absolute URL faces, and
    pinned to the checked addresses through CURLOPT_RESOLVE. A hop the guard
    refuses raises UnsafeUriError and no request is sent to it.
    """
    policy = _fetch_policy()
    safe_url = strip_user_info(url)
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
            extra_kwargs: dict[str, Any] = {}
            if curl_proxies is not None:
                extra_kwargs["proxies"] = curl_proxies

            async def send_hop(target: FetchTarget) -> HopAnswer[Any]:
                session.curl_options[CurlOpt.RESOLVE] = _resolve_entries(target)
                hop_kwargs: dict[str, Any] = dict(extra_kwargs)
                response = await session.get(
                    target.url,
                    headers=headers,
                    cookies=flat_cookies,
                    timeout=settings.EXTRACT_TIMEOUT,
                    allow_redirects=False,
                    **hop_kwargs,
                )
                return HopAnswer(
                    status=response.status_code,
                    location=response.headers.get("location"),
                    answer=response,
                )

            try:
                final = await follow_guarded_redirects(first, policy, send_hop)
            except UnsafeUriError:
                logger.warning("%s: SSRF guard blocked redirect from %s", strategy_label, safe_url)
                return ""

            response = final.answer

            if ChallengeDetector.is_login_required(response.text):
                logger.warning("%s: Login wall detected on %s", strategy_label, safe_url)
                raise ChallengeDetectedException(intervention_type="login")

            if ChallengeDetector.is_blocked(response.status_code, response.text):
                logger.warning("%s: WAF/Cloudflare block detected on %s", strategy_label, safe_url)
                raise ChallengeDetectedException(intervention_type="captcha")

            response.raise_for_status()

            return str(response.text)
    except ChallengeDetectedException:
        raise
    except Exception as e:
        logger.warning("%s failed to fetch URL %s: %s", strategy_label, safe_url, strip_user_info(str(e)))

        return ""

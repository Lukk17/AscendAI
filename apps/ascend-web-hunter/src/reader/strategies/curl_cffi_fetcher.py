import logging
from collections.abc import Callable
from typing import Any
from urllib.parse import urljoin

from curl_cffi import CurlOpt, requests

from src.api.exceptions import ChallengeDetectedException
from src.config.config import settings
from src.proxy.proxy_provider import proxy_provider
from src.reader.cloudflare.challenge_detector import ChallengeDetector
from src.reader.cloudflare.cookie_manager import cookie_manager
from src.validator.url_validator import pin_safe_host

logger = logging.getLogger(__name__)

_MAX_REDIRECTS = 10


def _pin_session_to(session: Any, url: str) -> bool:
    """Pin the session's next connect to the addresses validated for *url*.

    libcurl consults CURLOPT_RESOLVE before the system resolver, so the socket
    opens against an address the SSRF guard authorised in the same lookup.
    Returns False when the host resolves to anything non-public, in which case
    no request may be issued for it at all.
    """
    pinned = pin_safe_host(url)
    if pinned is None:
        return False

    session.curl_options[CurlOpt.RESOLVE] = pinned.curl_resolve_entries()

    return True


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

    Redirects are followed manually so each hop can be re-validated with the SSRF
    guard before proceeding. A relative `Location` is resolved against the URL of
    the hop that returned it, per RFC 9110 section 10.2.2, and the resolved
    absolute URL then faces the same validation an absolute one does. The initial
    URL and every hop are pinned to the addresses that same validation resolved,
    so the connection cannot land on a second, rebound answer.
    """
    flat_cookies = await cookie_manager.get_flat_cookies(url, profile)
    stored_ua = await cookie_manager.get_user_agent(url, profile)

    headers: dict[str, str] = {"User-Agent": stored_ua or user_agent_provider()}

    curl_proxies = proxy_provider.for_curl_cffi()

    try:
        # noinspection PyArgumentList
        async with requests.AsyncSession(impersonate="chrome120") as session:
            # Disable automatic redirect following so we can re-validate each hop.
            extra_kwargs: dict[str, Any] = {}
            if curl_proxies is not None:
                extra_kwargs["proxies"] = curl_proxies

            if not _pin_session_to(session, url):
                logger.warning("%s: SSRF guard refused %s", strategy_label, url)

                return ""

            response = await session.get(
                url,
                headers=headers,
                cookies=flat_cookies,
                timeout=settings.EXTRACT_TIMEOUT,
                allow_redirects=False,
                **extra_kwargs,
            )

            # Follow up to _MAX_REDIRECTS hops, resolving and validating each Location
            # against the URL of the hop that returned it before fetching.
            hops = 0
            current_url = url
            while response.status_code in (301, 302, 303, 307, 308) and hops < _MAX_REDIRECTS:
                location = response.headers.get("location", "")
                if not location:
                    break

                hop_url = urljoin(current_url, location)

                if not _pin_session_to(session, hop_url):
                    logger.warning(
                        "%s: SSRF guard blocked redirect to %s from %s",
                        strategy_label,
                        hop_url,
                        current_url,
                    )
                    return ""

                hop_kwargs: dict[str, Any] = {}
                if curl_proxies is not None:
                    hop_kwargs["proxies"] = curl_proxies
                response = await session.get(
                    hop_url,
                    headers=headers,
                    cookies=flat_cookies,
                    timeout=settings.EXTRACT_TIMEOUT,
                    allow_redirects=False,
                    **hop_kwargs,
                )
                current_url = hop_url
                hops += 1

            if ChallengeDetector.is_login_required(response.text):
                logger.warning("%s: Login wall detected on %s", strategy_label, url)
                raise ChallengeDetectedException(intervention_type="login")

            if ChallengeDetector.is_blocked(response.status_code, response.text):
                logger.warning("%s: WAF/Cloudflare block detected on %s", strategy_label, url)
                raise ChallengeDetectedException(intervention_type="captcha")

            response.raise_for_status()

            return str(response.text)
    except ChallengeDetectedException:
        raise
    except Exception as e:
        logger.warning("%s failed to fetch URL %s: %s", strategy_label, url, e)

        return ""

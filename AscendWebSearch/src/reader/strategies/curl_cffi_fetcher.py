import logging
from collections.abc import Callable

from curl_cffi import requests

from src.api.exceptions import ChallengeDetectedException
from src.config.config import settings
from src.reader.cloudflare.challenge_detector import ChallengeDetector
from src.reader.cloudflare.cookie_manager import cookie_manager
from src.validator.url_validator import is_safe_external_url, validate_redirect_chain

logger = logging.getLogger(__name__)

_MAX_REDIRECTS = 10


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
    guard before proceeding, closing the DNS-rebinding TOCTOU window.
    """
    flat_cookies = await cookie_manager.get_flat_cookies(url, profile)
    stored_ua = await cookie_manager.get_user_agent(url, profile)

    headers: dict[str, str] = {"User-Agent": stored_ua or user_agent_provider()}

    try:
        # noinspection PyArgumentList
        async with requests.AsyncSession(impersonate="chrome120") as session:
            # Disable automatic redirect following so we can re-validate each hop.
            response = await session.get(
                url,
                headers=headers,
                cookies=flat_cookies,
                timeout=settings.EXTRACT_TIMEOUT,
                allow_redirects=False,
            )

            # Follow up to _MAX_REDIRECTS hops, validating each Location before fetching.
            hops = 0
            while response.status_code in (301, 302, 303, 307, 308) and hops < _MAX_REDIRECTS:
                location = response.headers.get("location", "")
                if not location:
                    break

                if not is_safe_external_url(location):
                    logger.warning(
                        "%s: SSRF guard blocked redirect to %s from %s", strategy_label, location, url
                    )
                    return ""

                response = await session.get(
                    location,
                    headers=headers,
                    cookies=flat_cookies,
                    timeout=settings.EXTRACT_TIMEOUT,
                    allow_redirects=False,
                )
                hops += 1

            if ChallengeDetector.is_login_required(response.url, response.text):
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

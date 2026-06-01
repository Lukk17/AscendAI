import logging
from collections.abc import Callable

from curl_cffi import requests

from src.api.exceptions import ChallengeDetectedException
from src.config.config import settings
from src.reader.cloudflare.challenge_detector import ChallengeDetector
from src.reader.cloudflare.cookie_manager import cookie_manager

logger = logging.getLogger(__name__)


async def fetch_with_curl_cffi(
    url: str,
    user_agent_provider: Callable[[], str],
    strategy_label: str,
) -> str:
    """
    Shared curl_cffi fetch used by BeautifulSoupStrategy and TrafilaturaStrategy.
    Applies cached Cloudflare clearance cookies if any, raises ChallengeDetectedException
    on detected login/WAF walls, returns empty string on transport errors.
    """
    clearance_data = await cookie_manager.get_session_data(url)
    headers: dict[str, str] = {}
    cookies: dict[str, str] = {}

    if clearance_data:
        cookies = clearance_data.get("cookies", {})
        headers["User-Agent"] = clearance_data.get("user_agent", user_agent_provider())
    else:
        headers["User-Agent"] = user_agent_provider()

    try:
        # noinspection PyArgumentList
        async with requests.AsyncSession(impersonate="chrome120") as session:
            response = await session.get(
                url,
                headers=headers,
                cookies=cookies,
                timeout=settings.EXTRACT_TIMEOUT,
                allow_redirects=True,
            )

            if ChallengeDetector.is_login_required(response.url, response.text):
                logger.warning(f"{strategy_label}: Login wall detected on {url}")
                raise ChallengeDetectedException(intervention_type="login")

            if ChallengeDetector.is_blocked(response.status_code, response.text):
                logger.warning(f"{strategy_label}: WAF/Cloudflare block detected on {url}")
                raise ChallengeDetectedException(intervention_type="captcha")

            response.raise_for_status()

            return str(response.text)
    except ChallengeDetectedException:
        raise
    except Exception as e:
        logger.warning(f"{strategy_label} failed to fetch URL {url}: {e}")

        return ""

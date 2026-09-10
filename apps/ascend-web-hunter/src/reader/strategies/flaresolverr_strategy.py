import logging

import trafilatura
from curl_cffi import requests

from src.api.exceptions import ChallengeDetectedException
from src.circuit_breaker.breaker import flaresolverr_breaker
from src.config.config import settings
from src.proxy.proxy_provider import proxy_provider
from src.reader.cloudflare.challenge_detector import ChallengeDetector
from src.reader.cloudflare.cookie_manager import PRODUCED_BY_FLARESOLVERR, cookie_manager
from src.reader.strategies.base_strategy import BaseStrategy

logger = logging.getLogger(__name__)


class FlareSolverrStrategy(BaseStrategy):
    def __init__(self, profile: str | None = None) -> None:
        self.profile = profile

    async def extract(self, url: str) -> str:
        html = await self.get_html(url)
        if not html:
            return ""

        extracted: str | None = trafilatura.extract(html)
        return extracted or ""

    async def get_html(self, url: str) -> str:
        if not settings.FLARESOLVERR_URL:
            logger.warning("FlareSolverrStrategy skipped: FLARESOLVERR_URL not configured")
            return ""

        if flaresolverr_breaker.is_open:
            logger.warning("FlareSolverrStrategy: circuit breaker OPEN, skipping FlareSolverr for %s", url)
            return ""

        timeout = settings.EXTRACT_TIMEOUT * 2
        payload: dict = {"cmd": "request.get", "url": url, "maxTimeout": int((timeout - 2) * 1000)}

        # Inject any stored auth+WAF cookies via FlareSolverr's cookie array.
        saved_flat = await cookie_manager.get_flat_cookies(url, self.profile)
        if saved_flat:
            payload["cookies"] = [{"name": k, "value": v} for k, v in saved_flat.items()]
            logger.debug("FlareSolverrStrategy: injecting %d stored cookies for %s", len(saved_flat), url)

        # Inject optional proxy.
        fs_proxy = proxy_provider.for_flaresolverr()
        if fs_proxy is not None:
            payload["proxy"] = fs_proxy

        try:
            # noinspection PyArgumentList
            async with requests.AsyncSession() as session:
                response = await session.post(settings.FLARESOLVERR_URL, json=payload, timeout=timeout)
                response.raise_for_status()
                data = response.json()

                if data.get("status") == "ok":
                    solution = data.get("solution", {})
                    html = solution.get("response", "")

                    cookies_list = solution.get("cookies", [])
                    user_agent = solution.get("userAgent", "")

                    cookie_dict = {
                        c.get("name"): c.get("value") for c in cookies_list if "name" in c and "value" in c
                    }

                    # Persist unconditionally when the set is non-empty.
                    # Previously gated on cf_clearance presence, which silently
                    # discarded all LinkedIn auth cookies (li_at, JSESSIONID, etc.).
                    if cookie_dict:
                        await cookie_manager.save_flat_cookies(
                            url, cookie_dict, user_agent, self.profile, PRODUCED_BY_FLARESOLVERR
                        )

                    if ChallengeDetector.is_login_required(html):
                        logger.warning("FlareSolverrStrategy: Login wall detected on %s", url)
                        raise ChallengeDetectedException(intervention_type="login")

                    if ChallengeDetector.is_blocked(200, html):
                        logger.warning("FlareSolverrStrategy: WAF/Cloudflare block detected on %s", url)
                        raise ChallengeDetectedException(intervention_type="captcha")

                    flaresolverr_breaker.record_success()
                    return str(html)

                logger.warning("FlareSolverr failed on %s: %s", url, data.get("message"))
                flaresolverr_breaker.record_failure()
                return ""

        except ChallengeDetectedException:
            raise
        except Exception as e:
            flaresolverr_breaker.record_failure()
            return self._handle_error(url, e)

    @staticmethod
    def _handle_error(url: str, error: Exception) -> str:
        logger.warning("FlareSolverrStrategy error on %s: %s", url, error)
        return ""

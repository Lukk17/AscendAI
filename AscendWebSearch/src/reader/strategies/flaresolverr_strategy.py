import logging

import trafilatura
from curl_cffi import requests

from src.config.config import settings
from src.reader.cloudflare.cookie_manager import cookie_manager
from src.reader.strategies.base_strategy import BaseStrategy

logger = logging.getLogger(__name__)


class FlareSolverrStrategy(BaseStrategy):
    async def extract(self, url: str) -> str:
        html = await self.get_html(url)
        if not html:
            return ""

        extracted = trafilatura.extract(html)
        return extracted if extracted else ""

    async def get_html(self, url: str) -> str:
        if not settings.FLARESOLVERR_URL:
            logger.warning("FlareSolverrStrategy skipped: FLARESOLVERR_URL not configured")
            return ""

        timeout = settings.EXTRACT_TIMEOUT * 2
        payload = {
            "cmd": "request.get",
            "url": url,
            "maxTimeout": int((timeout - 2) * 1000)
        }

        try:
            async with requests.AsyncSession() as session:
                response = await session.post(
                    settings.FLARESOLVERR_URL,
                    json=payload,
                    timeout=timeout
                )
                response.raise_for_status()
                data = response.json()

                if data.get("status") == "ok":
                    solution = data.get("solution", {})
                    html = solution.get("response", "")

                    cookies_list = solution.get("cookies", [])
                    user_agent = solution.get("userAgent", "")

                    cookie_dict = {c.get("name"): c.get("value") for c in cookies_list if "name" in c and "value" in c}

                    if "cf_clearance" in cookie_dict:
                        await cookie_manager.save_clearance_data(url, cookie_dict, user_agent)

                    return html
                else:
                    logger.warning(f"FlareSolverr failed on {url}: {data.get('message')}")
                    return ""

        except Exception as e:
            return self._handle_error(url, e)

    def _handle_error(self, url: str, error: Exception) -> str:
        logger.warning(f"FlareSolverrStrategy error on {url}: {error}")
        return ""

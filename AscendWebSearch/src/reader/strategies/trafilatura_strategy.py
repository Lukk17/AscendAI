import logging

import trafilatura
from curl_cffi import requests

from src.config.config import settings
from src.reader.cloudflare.cloudflare_detector import CloudflareDetector
from src.reader.cloudflare.cookie_manager import cookie_manager
from src.reader.strategies.base_strategy import BaseStrategy

logger = logging.getLogger(__name__)


class TrafilaturaStrategy(BaseStrategy):
    def __init__(self, user_agent_provider):
        self.user_agent_provider = user_agent_provider

    async def extract(self, url: str) -> str:
        html = await self.get_html(url)
        if not html:
            return ""

        extracted = trafilatura.extract(html)
        return extracted if extracted else ""

    async def get_html(self, url: str) -> str:
        clearance_data = await cookie_manager.get_clearance_data(url)

        headers = {}
        cookies = {}

        if clearance_data:
            cookies = clearance_data.get("cookies", {})
            headers["User-Agent"] = clearance_data.get("user_agent", self.user_agent_provider())
        else:
            headers["User-Agent"] = self.user_agent_provider()

        try:
            async with requests.AsyncSession(impersonate="chrome120") as session:
                response = await session.get(
                    url,
                    headers=headers,
                    cookies=cookies,
                    timeout=settings.EXTRACT_TIMEOUT,
                    allow_redirects=True
                )

                if CloudflareDetector.is_blocked(response.status_code, response.text):
                    logger.warning(f"TrafilaturaStrategy: WAF/Cloudflare block detected on {url}")
                    return ""

                response.raise_for_status()
                return response.text

        except Exception as e:
            logger.warning(f"TrafilaturaStrategy failed to fetch URL {url}: {e}")
            return ""

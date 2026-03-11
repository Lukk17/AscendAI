import logging

from bs4 import BeautifulSoup
from curl_cffi import requests

from src.api.exceptions import ChallengeDetectedException
from src.config.config import settings
from src.reader.cloudflare.challenge_detector import ChallengeDetector
from src.reader.cloudflare.cookie_manager import cookie_manager
from src.reader.strategies.base_strategy import BaseStrategy

logger = logging.getLogger(__name__)
NOISE_TAGS = ['script', 'style', 'nav', 'footer', 'iframe']


class BeautifulSoupStrategy(BaseStrategy):
    def __init__(self, user_agent_provider):
        self.user_agent_provider = user_agent_provider

    async def extract(self, url: str) -> str:
        html = await self.get_html(url)
        if not html:
            return ""

        soup = BeautifulSoup(html, 'html.parser')
        self._remove_noise_tags(soup)
        return soup.get_text(separator=' ', strip=True)

    async def get_html(self, url: str) -> str:
        clearance_data = await cookie_manager.get_session_data(url)

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

                if ChallengeDetector.is_login_required(response.url, response.text):
                    logger.warning(f"BeautifulSoupStrategy: Login wall detected on {url}")
                    raise ChallengeDetectedException(intervention_type="login")

                if ChallengeDetector.is_blocked(response.status_code, response.text):
                    logger.warning(f"BeautifulSoupStrategy: WAF/Cloudflare block detected on {url}")
                    raise ChallengeDetectedException(intervention_type="captcha")

                response.raise_for_status()
                return response.text

        except Exception as e:
            logger.warning(f"BeautifulSoupStrategy failed to fetch URL {url}: {e}")
            return ""

    def _remove_noise_tags(self, soup: BeautifulSoup) -> None:
        for tag in soup(NOISE_TAGS):
            tag.decompose()

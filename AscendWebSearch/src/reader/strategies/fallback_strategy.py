import httpx
from bs4 import BeautifulSoup

from src.config.config import settings
from src.reader.strategies.base_strategy import BaseStrategy

NOISE_TAGS = ['script', 'style', 'nav', 'footer', 'iframe']


class FallbackStrategy(BaseStrategy):
    def __init__(self, user_agent_provider):
        self.user_agent_provider = user_agent_provider

    async def extract(self, url: str) -> str:
        html = await self.get_html(url)
        soup = BeautifulSoup(html, 'html.parser')
        self._remove_noise_tags(soup)
        return soup.get_text(separator=' ', strip=True)

    async def get_html(self, url: str) -> str:
        async with httpx.AsyncClient(
                follow_redirects=True,
                headers={"User-Agent": self.user_agent_provider()},
                timeout=settings.EXTRACT_TIMEOUT,
        ) as client:
            response = await client.get(url)
            response.raise_for_status()
            return response.text

    def _remove_noise_tags(self, soup: BeautifulSoup) -> None:
        for tag in soup(NOISE_TAGS):
            tag.decompose()

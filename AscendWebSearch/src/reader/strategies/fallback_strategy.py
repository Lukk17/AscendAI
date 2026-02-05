import httpx
from bs4 import BeautifulSoup

from src.config.config import settings
from src.reader.strategies.base_strategy import BaseStrategy


class FallbackStrategy(BaseStrategy):
    def __init__(self, user_agent_provider):
        self.user_agent_provider = user_agent_provider

    async def extract(self, url: str) -> str:
        async with httpx.AsyncClient(
                follow_redirects=True,
                headers={"User-Agent": self.user_agent_provider()},
                timeout=settings.EXTRACT_TIMEOUT
        ) as client:
            response = await client.get(url)
            response.raise_for_status()

            soup = BeautifulSoup(response.text, 'html.parser')
            self._clean_soup(soup)
            return soup.get_text(separator=' ', strip=True)

    def _clean_soup(self, soup: BeautifulSoup) -> None:
        for tag in soup(['script', 'style', 'nav', 'footer', 'iframe']):
            tag.decompose()

from collections.abc import Callable

from bs4 import BeautifulSoup

from src.reader.html_utils import remove_noise_tags
from src.reader.strategies.base_strategy import BaseStrategy
from src.reader.strategies.curl_cffi_fetcher import fetch_with_curl_cffi


class BeautifulSoupStrategy(BaseStrategy):
    def __init__(self, user_agent_provider: Callable[[], str]) -> None:
        self.user_agent_provider = user_agent_provider

    async def extract(self, url: str) -> str:
        html = await self.get_html(url)
        if not html:
            return ""

        soup = BeautifulSoup(html, "html.parser")
        remove_noise_tags(soup)

        return soup.get_text(separator=" ", strip=True)

    async def get_html(self, url: str) -> str:
        return await fetch_with_curl_cffi(url, self.user_agent_provider, "BeautifulSoupStrategy")

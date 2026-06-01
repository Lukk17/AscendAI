from collections.abc import Callable

import trafilatura

from src.reader.strategies.base_strategy import BaseStrategy
from src.reader.strategies.curl_cffi_fetcher import fetch_with_curl_cffi


class TrafilaturaStrategy(BaseStrategy):
    def __init__(self, user_agent_provider: Callable[[], str]) -> None:
        self.user_agent_provider = user_agent_provider

    async def extract(self, url: str) -> str:
        html = await self.get_html(url)
        if not html:
            return ""

        extracted: str | None = trafilatura.extract(html)

        return extracted or ""

    async def get_html(self, url: str) -> str:
        return await fetch_with_curl_cffi(url, self.user_agent_provider, "TrafilaturaStrategy")

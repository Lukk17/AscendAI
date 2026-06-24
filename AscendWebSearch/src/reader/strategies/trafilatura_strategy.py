from collections.abc import Callable

from src.reader.extraction import extract_text_with_fallback
from src.reader.strategies.base_strategy import BaseStrategy
from src.reader.strategies.curl_cffi_fetcher import fetch_with_curl_cffi


class TrafilaturaStrategy(BaseStrategy):
    def __init__(self, user_agent_provider: Callable[[], str], profile: str | None = None) -> None:
        self.user_agent_provider = user_agent_provider
        self.profile = profile

    async def extract(self, url: str) -> str:
        html = await self.get_html(url)
        if not html:
            return ""

        return extract_text_with_fallback(html)

    async def get_html(self, url: str) -> str:
        return await fetch_with_curl_cffi(url, self.user_agent_provider, "TrafilaturaStrategy", self.profile)

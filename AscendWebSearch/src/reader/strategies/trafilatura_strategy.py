import httpx
import trafilatura

from src.config.config import settings
from src.reader.strategies.base_strategy import BaseStrategy


class TrafilaturaStrategy(BaseStrategy):
    def __init__(self, user_agent_provider):
        self.user_agent_provider = user_agent_provider

    async def extract(self, url: str) -> str:
        async with httpx.AsyncClient(follow_redirects=True, timeout=settings.EXTRACT_TIMEOUT,
                                     headers={"User-Agent": self.user_agent_provider()}) as client:
            response = await client.get(url)
            response.raise_for_status()
            extracted = trafilatura.extract(response.text)
            return extracted if extracted else ""

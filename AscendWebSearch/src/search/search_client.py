import logging
import time
from typing import Any

import httpx
from bs4 import BeautifulSoup

from src.config.config import settings
from src.observability.metrics import SEARXNG_DURATION_SECONDS, SEARXNG_REQUESTS_TOTAL

logger = logging.getLogger(__name__)


class SearxngClient:
    def __init__(self, base_url: str = settings.SEARXNG_BASE_URL):
        self.base_url = base_url.rstrip("/")
        # AsyncClient because every caller is on the FastAPI event loop. Closing on
        # shutdown is wired via aclose() invoked from main.py's lifespan; without it
        # the connection pool leaks across reloads.
        self.client = httpx.AsyncClient(timeout=settings.SEARCH_TIMEOUT)

    async def aclose(self) -> None:
        await self.client.aclose()

    async def search(self, query: str, limit: int = 5, categories: str | None = None) -> list[dict[str, Any]]:
        url = f"{self.base_url}/search"
        params = {
            "q": query,
            "format": "html",
            "language": "en-US",
        }
        if categories:
            params["categories"] = categories

        headers = {
            "User-Agent": settings.SEARXNG_USER_AGENT,
            "X-Real-IP": settings.SEARXNG_X_REAL_IP,
            "X-Forwarded-For": settings.SEARXNG_X_FORWARDED_FOR,
        }

        started = time.perf_counter()

        try:
            response = await self.client.get(url, params=params, headers=headers)
            response.raise_for_status()
            SEARXNG_REQUESTS_TOTAL.labels(outcome="success").inc()
        except httpx.TimeoutException:
            SEARXNG_REQUESTS_TOTAL.labels(outcome="timeout").inc()
            raise
        except httpx.HTTPStatusError:
            SEARXNG_REQUESTS_TOTAL.labels(outcome="http_error").inc()
            raise
        except httpx.HTTPError:
            SEARXNG_REQUESTS_TOTAL.labels(outcome="transport_error").inc()
            raise
        finally:
            SEARXNG_DURATION_SECONDS.observe(time.perf_counter() - started)

        return self._parse_html_results(response.text, limit)

    def _parse_html_results(self, html_content: str, limit: int) -> list[dict[str, Any]]:
        soup = BeautifulSoup(html_content, "html.parser")
        results: list[dict[str, Any]] = []

        for article in soup.select("article.result"):
            if len(results) >= limit:
                break

            title_tag = article.select_one("h3 a")
            if not title_tag:
                continue

            url = title_tag.get("href")
            title = title_tag.get_text(strip=True)

            content_tag = article.select_one("p.content")
            content = content_tag.get_text(strip=True) if content_tag else ""

            results.append({"title": title, "url": url, "content": content})

        return results

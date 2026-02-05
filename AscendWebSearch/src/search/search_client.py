import logging
from typing import List, Dict, Any, Optional

import httpx
from bs4 import BeautifulSoup

from src.config.config import settings

logger = logging.getLogger(__name__)


class SearxngClient:
    def __init__(self, base_url: str = settings.SEARXNG_BASE_URL):
        self.base_url = base_url.rstrip("/")
        self.client = httpx.Client(timeout=settings.SEARCH_TIMEOUT)

    def search(self, query: str, limit: int = 5, categories: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Search using SearXNG.
        Returns a list of results.
        Raises exceptions for global handler to catch.
        """
        # Explicitly request HTML format to avoid 403 on disabled JSON
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
            "X-Forwarded-For": settings.SEARXNG_X_FORWARDED_FOR
        }

        response = self.client.get(url, params=params, headers=headers)
        response.raise_for_status()

        return self._parse_html_results(response.text, limit)

    def _parse_html_results(self, html_content: str, limit: int) -> List[Dict[str, Any]]:
        """
        Parses SearXNG HTML results into a list of dictionaries.
        """
        soup = BeautifulSoup(html_content, 'html.parser')
        results = []

        # specific to SearXNG default theme structure
        for article in soup.select('article.result'):
            if len(results) >= limit:
                break

            title_tag = article.select_one('h3 a')
            if not title_tag:
                continue

            url = title_tag.get('href')
            title = title_tag.get_text(strip=True)

            content_tag = article.select_one('p.content')
            content = content_tag.get_text(strip=True) if content_tag else ""

            results.append({
                "title": title,
                "url": url,
                "content": content
            })

        return results

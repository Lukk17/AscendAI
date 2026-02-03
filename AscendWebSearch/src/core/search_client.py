import httpx
import logging
from typing import List, Dict, Any, Optional
from src.core.config import settings

logger = logging.getLogger(__name__)

class SearxngClient:
    def __init__(self, base_url: str = settings.SEARXNG_BASE_URL):
        self.base_url = base_url.rstrip("/")
        self.client = httpx.Client(timeout=10.0)

    def search(self, query: str, limit: int = 5, categories: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Search using SearXNG.
        Returns a list of results.
        """
        url = f"{self.base_url}/search"
        params = {
            "q": query,
            "format": "json",
            "language": "en-US", # Default, can be parametrized later
        }
        if categories:
            params["categories"] = categories

        try:
            response = self.client.get(url, params=params)
            response.raise_for_status()
            data = response.json()
            
            results = data.get("results", [])
            # limit results
            return results[:limit]
            
        except httpx.RequestError as e:
            logger.error(f"An error occurred while requesting {e.request.url!r}.")
            return []
        except httpx.HTTPStatusError as e:
            logger.error(f"Error response {e.response.status_code} while requesting {e.request.url!r}.")
            return []
        except Exception as e:
            logger.error(f"Unexpected error during search: {e}")
            return []

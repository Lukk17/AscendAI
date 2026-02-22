from typing import List, Dict, Any

from fastapi import APIRouter, HTTPException

from src.reader.web_reader import WebReader
from src.search.search_client import SearxngClient

rest_router = APIRouter(prefix="/api/v1/web", tags=["web"])
search_client = SearxngClient()
web_reader = WebReader()


@rest_router.get("/search", response_model=List[Dict[str, Any]])
def search(query: str, limit: int = 5):
    """
    Search the web.
    """
    results = search_client.search(query=query, limit=limit)
    return results


@rest_router.get("/read")
async def read_url(url: str, include_links: bool = False, link_filter: str | None = None):
    """
    Extract content from a URL.
    Args:
        url: The URL to scrape.
        include_links: When True, returns annotated content with inline [N] link markers
                       and a numbered link map {1: url, 2: url, ...}.
        link_filter: Optional URL substring — when set, only links whose href contains
                     this string are included in the link map (e.g. '/job-offer/').
    """
    if not url:
        raise HTTPException(status_code=400, detail="URL is required")

    if include_links:
        result = await web_reader.read_with_links(url, link_filter)
        return {"url": url, **result}

    content = await web_reader.read(url)
    return {"url": url, "content": content}

from fastapi import APIRouter, HTTPException, Query
from typing import List, Dict, Any

from src.core.search_client import SearxngClient
from src.core.web_reader import WebReader

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
async def read_url(url: str):
    """
    Extract content from a URL.
    """
    if not url:
        raise HTTPException(status_code=400, detail="URL is required")
    
    content = await web_reader.read(url)
    return {"url": url, "content": content}

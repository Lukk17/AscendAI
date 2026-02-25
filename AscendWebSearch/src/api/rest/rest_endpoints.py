from typing import List, Dict, Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, HttpUrl

from src.reader.web_reader import WebReader
from src.search.search_client import SearxngClient

rest_router = APIRouter(prefix="/api/v1/web", tags=["web_v1"])
rest_router_v2 = APIRouter(prefix="/api/v2/web", tags=["web_v2"])

search_client = SearxngClient()
web_reader = WebReader()


class ReadRequest(BaseModel):
    url: HttpUrl
    include_links: bool = False
    link_filter: str | None = None
    heavy_mode: bool = False


@rest_router.get("/search", response_model=List[Dict[str, Any]])
def search(query: str, limit: int = 5):
    """
    Search the web.
    """
    results = search_client.search(query=query, limit=limit)
    return results


@rest_router.get("/read", responses={
    200: {
        "description": "Successful extraction or Captcha required",
        "content": {
            "application/json": {
                "examples": {
                    "success": {"value": {"url": "https://example.com", "content": "Text...", "status": "success",
                                          "mode": "1-beautifulsoup"}},
                    "captcha": {"value": {"url": "https://example.com", "status": "human_intervention_required",
                                          "intervention_type": "captcha",
                                          "vnc_url": "http://localhost:7900",
                                          "message": "Manual Captcha resolution required. Please visit: http://localhost:7900"}},
                    "login": {"value": {"url": "https://example.com", "status": "human_intervention_required",
                                          "intervention_type": "login",
                                          "vnc_url": "http://localhost:7900",
                                          "message": "Manual Login authentication required. Please visit: http://localhost:7900"}}
                }
            }
        }
    }
})
async def read_url(url: str, include_links: bool = False, link_filter: str | None = None, heavy_mode: bool = False):
    """
    Extract content from a URL.
    Args:
        url: The URL to scrape.
        include_links: When True, returns annotated content with inline [N] link markers
                       and a numbered link map {1: url, 2: url, ...}.
        link_filter: Optional URL substring — when set, only links whose href contains
                     this string are included in the link map (e.g. '/job-offer/').
        heavy_mode: If True, skips lightweight strategies and jumps straight to advanced browser strategies.
    """
    if not url:
        raise HTTPException(status_code=400, detail="URL is required")

    if include_links:
        result = await web_reader.read_with_links(url, link_filter, heavy_mode=heavy_mode)
    else:
        result = await web_reader.read(url, heavy_mode=heavy_mode)
    
    return {"url": url, **result}


@rest_router_v2.post("/read", responses={
    200: {
        "description": "Successful extraction or Captcha required",
        "content": {
            "application/json": {
                "examples": {
                    "success": {"value": {"url": "https://example.com?complex=1&auth=2", "content": "Text...", "status": "success",
                                          "mode": "1-beautifulsoup"}},
                    "captcha": {"value": {"url": "https://example.com", "status": "human_intervention_required",
                                          "intervention_type": "captcha",
                                          "vnc_url": "http://localhost:7900",
                                          "message": "Manual Captcha resolution required. Please visit: http://localhost:7900"}},
                    "login": {"value": {"url": "https://example.com", "status": "human_intervention_required",
                                          "intervention_type": "login",
                                          "vnc_url": "http://localhost:7900",
                                          "message": "Manual Login authentication required. Please visit: http://localhost:7900"}}
                }
            }
        }
    }
})
async def read_url_v2(request: ReadRequest):
    """
    Extract content from a URL via POST JSON.
    This is the recommended endpoint as it natively protects complex URL parameters (like & or ?continue=) from being hijacked by the HTTP Router.
    """
    url_str = str(request.url)
    if request.include_links:
        result = await web_reader.read_with_links(url_str, request.link_filter, heavy_mode=request.heavy_mode)
    else:
        result = await web_reader.read(url_str, heavy_mode=request.heavy_mode)
        
    return {"url": url_str, **result}

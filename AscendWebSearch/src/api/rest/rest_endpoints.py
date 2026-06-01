from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, HttpUrl

from src.reader.web_reader import WebReader
from src.search.search_client import SearxngClient
from src.validator.url_validator import is_safe_external_url

rest_router = APIRouter(prefix="/api/v1/web", tags=["web_v1"])
rest_router_v2 = APIRouter(prefix="/api/v2/web", tags=["web_v2"])

MAX_QUERY_LENGTH = 500

search_client = SearxngClient()
web_reader = WebReader()


class ReadRequest(BaseModel):
    url: HttpUrl
    include_links: bool = False
    link_filter: str | None = None
    heavy_mode: bool = False


@rest_router.get("/search")
async def search(query: str, limit: int = 5) -> list[dict[str, Any]]:
    """
    Search the web.
    """
    if not query or not query.strip():
        raise HTTPException(status_code=400, detail="query must not be empty")
    if len(query) > MAX_QUERY_LENGTH:
        raise HTTPException(
            status_code=400,
            detail=f"query exceeds maximum length of {MAX_QUERY_LENGTH} characters",
        )

    return await search_client.search(query=query, limit=limit)


_SUCCESS_EXAMPLE = {
    "url": "https://example.com?complex=1&auth=2",
    "content": "Text...",
    "status": "success",
    "mode": "1-beautifulsoup",
}
_CAPTCHA_EXAMPLE = {
    "url": "https://example.com",
    "status": "human_intervention_required",
    "intervention_type": "captcha",
    "vnc_url": "http://localhost:7900",
    "message": "Manual Captcha resolution required. Please visit: http://localhost:7900",
}
_LOGIN_EXAMPLE = {
    "url": "https://example.com",
    "status": "human_intervention_required",
    "intervention_type": "login",
    "vnc_url": "http://localhost:7900",
    "message": "Manual Login authentication required. Please visit: http://localhost:7900",
}


@rest_router_v2.post(
    "/read",
    responses={
        200: {
            "description": "Successful extraction or Captcha required",
            "content": {
                "application/json": {
                    "examples": {
                        "success": {"value": _SUCCESS_EXAMPLE},
                        "captcha": {"value": _CAPTCHA_EXAMPLE},
                        "login": {"value": _LOGIN_EXAMPLE},
                    },
                },
            },
        },
    },
)
async def read_url_v2(request: ReadRequest) -> dict[str, Any]:
    """
    Extract content from a URL via POST JSON.

    Recommended endpoint: protects complex URL parameters (& or ?continue=) from
    being hijacked by the HTTP router.
    """
    url_str = str(request.url)
    if not is_safe_external_url(url_str):
        raise HTTPException(
            status_code=400,
            detail="URL resolves to a private, loopback, link-local, or otherwise non-routable address",
        )
    if request.include_links:
        result = await web_reader.read_with_links(url_str, request.link_filter, heavy_mode=request.heavy_mode)
    else:
        result = await web_reader.read(url_str, heavy_mode=request.heavy_mode)

    return {"url": url_str, **result}

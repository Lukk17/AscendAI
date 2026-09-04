from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, HttpUrl

from src.reader.cloudflare.cookie_manager import cookie_manager
from src.reader.web_reader import WebReader
from src.search.search_client import SearxngClient
from src.session.session_manager import session_manager
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
    profile: str | None = None


class SessionEstablishRequest(BaseModel):
    url: HttpUrl
    profile: str | None = None


class SessionStatusRequest(BaseModel):
    url: HttpUrl
    profile: str | None = None


class SessionClearRequest(BaseModel):
    url: HttpUrl
    profile: str | None = None


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
        result = await web_reader.read_with_links(
            url_str,
            request.link_filter,
            heavy_mode=request.heavy_mode,
            profile=request.profile,
        )
    else:
        result = await web_reader.read(url_str, heavy_mode=request.heavy_mode, profile=request.profile)

    return {"url": url_str, **result}


@rest_router_v2.post("/session/establish")
async def establish_session(request: SessionEstablishRequest) -> dict[str, Any]:
    """
    Proactively open the NoVNC login flow for a URL.

    Always returns a 200 with the VNC URL so the caller can direct the user
    to complete the login in their browser.
    """
    url_str = str(request.url)
    if not is_safe_external_url(url_str):
        raise HTTPException(
            status_code=400,
            detail="URL resolves to a private, loopback, link-local, or otherwise non-routable address",
        )

    vnc_url = await session_manager.establish(url_str, request.profile)
    return {"status": "login_required", "target": url_str, "vnc_url": vnc_url}


@rest_router_v2.post("/session/status")
async def session_status(request: SessionStatusRequest) -> dict[str, Any]:
    """
    Query the auth session status for a URL + profile.
    """
    url_str = str(request.url)
    info = await session_manager.status(url_str, request.profile)
    return {"url": url_str, **info.to_dict()}


@rest_router_v2.post("/session/clear")
async def clear_session(request: SessionClearRequest) -> dict[str, Any]:
    """
    Delete the stored session for a URL + profile, including any cached read
    results for that domain.

    Idempotent: always returns 200, whether or not a session existed.
    """
    url_str = str(request.url)
    if not is_safe_external_url(url_str):
        raise HTTPException(
            status_code=400,
            detail="URL resolves to a private, loopback, link-local, or otherwise non-routable address",
        )

    existed = await session_manager.clear(url_str, request.profile)
    domain = cookie_manager._get_domain(url_str)  # noqa: SLF001
    cleared_cache_entries = web_reader.clear_cache_for_domain(domain)

    return {
        "status": "cleared",
        "url": url_str,
        "existed": existed,
        "cleared_cache_entries": cleared_cache_entries,
    }

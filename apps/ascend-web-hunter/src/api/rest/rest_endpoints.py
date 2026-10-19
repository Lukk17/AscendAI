import random
import re
import time
from typing import Any
from urllib.parse import urlparse

import tldextract
from ascend_python_common.uri_guard import FetchPolicy, UnsafeUriError, check_fetch_uri
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field, HttpUrl

from src.api.exceptions import InvalidProfileError, NoCookiesForDomainError
from src.config.config import settings
from src.reader.cloudflare.cookie_manager import PRODUCED_BY_IMPORT, cookie_manager
from src.reader.novnc.flow_registry import flow_shape, novnc_flow_registry
from src.reader.web_reader import OutputFormat, TierName, WebReader
from src.search.search_client import SearxngClient
from src.session.session_manager import session_manager

rest_router = APIRouter(prefix="/api/v1/web", tags=["web_v1"])
rest_router_v2 = APIRouter(prefix="/api/v2/web", tags=["web_v2"])
rest_session_router = APIRouter(prefix="/api/v2/session", tags=["web_session"])

MAX_QUERY_LENGTH = 500

search_client = SearxngClient()
web_reader = WebReader()


def _fetch_policy() -> FetchPolicy:
    return FetchPolicy(
        allowed_hosts=tuple(settings.ALLOWED_PRIVATE_HOSTS),
        file_root=None,
        max_redirect_hops=settings.FETCH_MAX_REDIRECT_HOPS,
    )


class ReadRequest(BaseModel):
    url: HttpUrl
    include_links: bool = False
    link_filter: str | None = None
    heavy_mode: bool = False
    profile: str | None = None
    output_format: OutputFormat = Field(
        default="text",
        description=(
            "'text' returns the flat content field. 'structured' adds title, author, date and "
            "sitename alongside it, and is not available together with include_links."
        ),
    )
    tier: TierName | None = Field(
        default=None,
        description=(
            "Start the extraction chain at this tier instead of where heavy_mode and the stored "
            "session's producer would start it. Escalation continues through the tiers after it."
        ),
    )


class SessionEstablishRequest(BaseModel):
    url: HttpUrl
    profile: str | None = None


class SessionStatusRequest(BaseModel):
    url: HttpUrl
    profile: str | None = None


class SessionClearRequest(BaseModel):
    url: HttpUrl
    profile: str | None = None


PROFILE_PATTERN = r"[A-Za-z0-9_-]{1,64}"

_WAF_COOKIE_NAMES = frozenset({"cf_clearance", "__cf_bm", "_cfuvid"})

_IMPORT_TLD_EXTRACT = tldextract.TLDExtract(suffix_list_urls=(), cache_dir=None)


class PlaywrightCookie(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    name: str
    value: str
    domain: str
    path: str = "/"
    expires: float = -1
    http_only: bool = Field(default=False, alias="httpOnly")
    secure: bool = False
    same_site: str = Field(default="Lax", alias="sameSite")


class PlaywrightLocalStorageItem(BaseModel):
    name: str
    value: str


class PlaywrightOrigin(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    origin: str
    local_storage: list[PlaywrightLocalStorageItem] = Field(
        default_factory=list, alias="localStorage"
    )


class PlaywrightStorageState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cookies: list[PlaywrightCookie] = Field(default_factory=list)
    origins: list[PlaywrightOrigin] = Field(default_factory=list)


class SessionImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: HttpUrl
    profile: str | None = None
    storage_state: PlaywrightStorageState
    user_agent: str | None = None


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
    "type": "https://ascend.ai/errors/human-intervention-required",
    "title": "Precondition Required",
    "status": 428,
    "detail": "Manual Captcha resolution required. Please visit: https://edge.example.com/novnc/host-1/vnc.html",
    "instance": "/api/v2/web/read",
    "code": "human_intervention_required",
    "traceId": "4bf92f3577b34da6a3ce929d0e0e4736",
    "intervention_type": "captcha",
    "vnc_url": "https://edge.example.com/novnc/host-1/vnc.html",
    "flow_id": "9f2c41ab77de",
    "joined": False,
    "window": {"slot": 0, "x": 0, "y": 0, "width": 1280, "height": 800},
}
_LOGIN_EXAMPLE = {
    "type": "https://ascend.ai/errors/human-intervention-required",
    "title": "Precondition Required",
    "status": 428,
    "detail": "Manual Login authentication required. Please visit: https://edge.example.com/novnc/host-1/vnc.html",
    "instance": "/api/v2/web/read",
    "code": "human_intervention_required",
    "traceId": "4bf92f3577b34da6a3ce929d0e0e4736",
    "intervention_type": "login",
    "vnc_url": "https://edge.example.com/novnc/host-1/vnc.html",
    "flow_id": "9f2c41ab77de",
    "joined": False,
    "window": {"slot": 0, "x": 0, "y": 0, "width": 1280, "height": 800},
}
_BUSY_EXAMPLE = {
    "type": "https://ascend.ai/errors/novnc-busy",
    "title": "Conflict",
    "status": 409,
    "detail": (
        "All 4 intervention windows are in use. "
        "The oldest is https://nowsecure.nl (profile=default). Try again shortly."
    ),
    "instance": "/api/v2/web/read",
    "code": "novnc_busy",
    "traceId": "4bf92f3577b34da6a3ce929d0e0e4736",
    "holder_url": "https://nowsecure.nl",
    "holder_profile": "default",
    "active_flows": 4,
    "max_concurrent_flows": 4,
    "flows": [
        {
            "flow_id": "9f2c41ab77de",
            "url": "https://nowsecure.nl",
            "domain": "nowsecure.nl",
            "profile": "default",
            "intervention_type": "captcha",
            "window": {"slot": 0, "x": 0, "y": 0, "width": 1280, "height": 800},
            "age_seconds": 207.3,
            "expires_in_seconds": 412.7,
            "vnc_url": "https://edge.example.com/novnc/host-1/vnc.html",
        }
    ],
}
_SESSION_EXPIRED_EXAMPLE = {
    "url": "https://example.com/feed",
    "content": "",
    "status": "session_expired",
    "profile": "work",
    "message": (
        "Stored session for example.com (profile=work) is no longer valid. "
        "Re-establish it with the session establish operation, then read again."
    ),
}


@rest_router_v2.post(
    "/read",
    responses={
        200: {
            "description": "Successful extraction, Captcha required, or an expired stored session",
            "content": {
                "application/json": {
                    "examples": {
                        "success": {"value": _SUCCESS_EXAMPLE},
                        "captcha": {"value": _CAPTCHA_EXAMPLE},
                        "login": {"value": _LOGIN_EXAMPLE},
                        "busy": {"value": _BUSY_EXAMPLE},
                        "session_expired": {"value": _SESSION_EXPIRED_EXAMPLE},
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
    await check_fetch_uri(url_str, _fetch_policy())
    if request.include_links and request.output_format == "structured":
        raise HTTPException(
            status_code=400,
            detail=(
                "output_format=structured is not available with include_links: the annotated-links "
                "response carries the flat content shape plus a link map"
            ),
        )
    if request.include_links:
        result = await web_reader.read_with_links(
            url_str,
            request.link_filter,
            heavy_mode=request.heavy_mode,
            profile=request.profile,
            output_format=request.output_format,
            tier=request.tier,
        )
    else:
        result = await web_reader.read(
            url_str,
            heavy_mode=request.heavy_mode,
            profile=request.profile,
            output_format=request.output_format,
            tier=request.tier,
        )

    return {"url": url_str, **result}


@rest_router_v2.post("/session/establish")
async def establish_session(request: SessionEstablishRequest) -> dict[str, Any]:
    """
    Proactively open the NoVNC login flow for a URL.

    Returns a 200 with the VNC URL so the caller can direct the user to
    complete the login in their browser. Returns 409 with `status: novnc_busy`
    when another NoVNC intervention already holds the shared browser/display;
    only one can run at a time.
    """
    url_str = str(request.url)
    await check_fetch_uri(url_str, _fetch_policy())

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
    await check_fetch_uri(url_str, _fetch_policy())

    existed = await session_manager.clear(url_str, request.profile)
    domain = cookie_manager.registrable_domain(url_str)
    cleared_cache_entries = web_reader.clear_cache_for_domain(domain)

    return {
        "status": "cleared",
        "url": url_str,
        "existed": existed,
        "cleared_cache_entries": cleared_cache_entries,
    }


@rest_router_v2.post("/session/import")
async def import_session(request: SessionImportRequest) -> dict[str, Any]:
    """
    Store a Playwright storage_state captured outside the service.

    Validates with no address lookup: the URL host must have a registrable
    domain, the profile must match the identifier pattern, and at least one
    cookie must belong to the domain. Drops other-domain cookies, saves with
    the import provenance, and purges the domain read cache like a clear.
    """
    url_str = str(request.url)
    parsed_host = urlparse(url_str).hostname or ""
    extracted = _IMPORT_TLD_EXTRACT(parsed_host.lower())
    if not extracted.domain or not extracted.suffix:
        raise UnsafeUriError(f"URL host has no registrable domain: {parsed_host}")
    domain = f"{extracted.domain}.{extracted.suffix}"

    effective_profile = (
        request.profile if request.profile is not None else settings.SESSION_DEFAULT_PROFILE
    )
    if re.fullmatch(PROFILE_PATTERN, effective_profile) is None:
        raise InvalidProfileError(f"profile must match {PROFILE_PATTERN}")

    kept = [
        cookie
        for cookie in request.storage_state.cookies
        if (cookie.domain.lstrip(".").lower() == domain)
        or (cookie.domain.lstrip(".").lower().endswith(f".{domain}"))
    ]
    dropped_cookies = len(request.storage_state.cookies) - len(kept)
    if not kept:
        raise NoCookiesForDomainError(f"no cookie belongs to {domain}")

    user_agent = request.user_agent or random.choice(web_reader.user_agents)
    filtered_state = {
        "cookies": [cookie.model_dump(by_alias=True) for cookie in kept],
        "origins": [origin.model_dump(by_alias=True) for origin in request.storage_state.origins],
    }
    await cookie_manager.save_storage_state(
        url_str,
        filtered_state,
        user_agent,
        effective_profile,
        produced_by=PRODUCED_BY_IMPORT,
    )
    web_reader.clear_cache_for_domain(domain)

    auth_cookies = sum(1 for cookie in kept if cookie.name not in _WAF_COOKIE_NAMES)
    waf_cookies = sum(1 for cookie in kept if cookie.name in _WAF_COOKIE_NAMES)

    return {
        "status": "imported",
        "domain": domain,
        "profile": effective_profile,
        "auth_cookies": auth_cookies,
        "waf_cookies": waf_cookies,
        "dropped_cookies": dropped_cookies,
    }


@rest_session_router.get("/interventions")
async def list_interventions() -> dict[str, Any]:
    """
    List the live human-intervention flows of every container.

    Read-only and unauthenticated, like the `vnc_url` in the 428 body. Each
    entry carries the window of its flow; no cookies, storage state or page
    content is returned.
    """
    flows = await novnc_flow_registry.active()
    now = time.time()

    return {
        "active_flows": len(flows),
        "max_concurrent_flows": settings.NOVNC_MAX_CONCURRENT_FLOWS,
        "flows": [flow_shape(flow, now) for flow in flows],
    }

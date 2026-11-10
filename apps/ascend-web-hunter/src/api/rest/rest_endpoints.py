import random
import time
from typing import Any, Literal
from urllib.parse import urlparse

import tldextract
from ascend_python_common.uri_guard import UnsafeUriError, check_fetch_uri
from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field, HttpUrl

from src.api.exceptions import (
    FormatCombinationError,
    NoCookiesForDomainError,
)
from src.config.config import settings
from src.reader.browser_guard import web_hunter_fetch_policy
from src.reader.cache_purge import publish_purge
from src.reader.cloudflare.cookie_manager import (
    PRODUCED_BY_IMPORT,
    cookie_manager,
    holds_login_state,
    is_waf_cookie,
)
from src.reader.novnc.flow_registry import flow_shape, novnc_flow_registry
from src.reader.web_reader import OutputFormat, TierName, WebReader
from src.search.search_client import SearxngClient
from src.session.profile import Profile, SessionHttpUrl, check_profile
from src.session.session_manager import session_manager

rest_router = APIRouter(prefix="/api/v1/web", tags=["web_v1"])
rest_router_v2 = APIRouter(prefix="/api/v2/web", tags=["web_v2"])
rest_session_router = APIRouter(prefix="/api/v2/session", tags=["web_session"])

MAX_QUERY_LENGTH = 500

search_client = SearxngClient()
web_reader = WebReader()


class ReadRequest(BaseModel):
    url: HttpUrl
    include_links: bool = False
    link_filter: str | None = None
    heavy_mode: bool = False
    profile: Profile | None = None
    output_format: OutputFormat = Field(
        default="text",
        description=(
            "'text' returns the flat content field. 'structured' adds title, author, date and "
            "sitename alongside it. 'schema' returns JSON validated against extraction_schema. "
            "'tables' returns each HTML table as rows. 'screenshot' returns a base64 PNG. "
            "Every format but 'text' is refused together with include_links."
        ),
    )
    extraction_schema: dict[str, Any] | None = Field(
        default=None,
        description=(
            "JSON Schema the 'schema' output format extracts and validates against. "
            "Required with output_format='schema', ignored otherwise."
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
    url: SessionHttpUrl
    profile: Profile | None = None


class SessionStatusRequest(BaseModel):
    url: SessionHttpUrl
    profile: Profile | None = None


class SessionClearRequest(BaseModel):
    url: SessionHttpUrl
    profile: Profile | None = None


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
    same_site: Literal["Strict", "Lax", "None"] = Field(default="Lax", alias="sameSite")


class PlaywrightLocalStorageItem(BaseModel):
    name: str
    value: str


class PlaywrightOrigin(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    origin: str
    local_storage: list[PlaywrightLocalStorageItem] = Field(default_factory=list, alias="localStorage")


class PlaywrightStorageState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cookies: list[PlaywrightCookie] = Field(default_factory=list)
    origins: list[PlaywrightOrigin] = Field(default_factory=list)


class SessionImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: SessionHttpUrl
    profile: Profile | None = None
    storage_state: PlaywrightStorageState
    user_agent: str | None = None


def _belongs_to_domain(host: str, domain: str) -> bool:
    """True when *host* is *domain* or one of its subdomains."""
    normalised = host.lstrip(".").lower()

    return normalised == domain or normalised.endswith(f".{domain}")


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
    await check_fetch_uri(url_str, web_hunter_fetch_policy())
    if request.include_links and request.output_format != "text":
        raise FormatCombinationError(request.output_format)
    if request.output_format == "schema" and request.extraction_schema is None:
        raise ValueError("extraction_schema is required with output_format=schema")
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
            extraction_schema=request.extraction_schema,
        )

    return {"url": url_str, **result}


@rest_router_v2.post("/session/establish")
async def establish_session(request: SessionEstablishRequest) -> dict[str, Any]:
    """
    Proactively open the NoVNC login flow for a URL.

    Returns a 200 with the VNC URL, the flow's `flow_id`, `window` and
    `intervention_type`, and `joined` true when an open flow for the same site
    and profile was joined, so the caller can direct the user to the window.
    Returns 409 with code `novnc_busy` when every window slot of this
    container is in use.
    """
    url_str = str(request.url)
    await check_fetch_uri(url_str, web_hunter_fetch_policy())

    established = await session_manager.establish(url_str, request.profile)

    return {
        "status": "login_required",
        "target": url_str,
        "intervention_type": established.intervention_type,
        "vnc_url": established.vnc_url,
        "flow_id": established.flow_id,
        "joined": established.joined,
        "window": established.window,
    }


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
    await check_fetch_uri(url_str, web_hunter_fetch_policy())

    existed = await session_manager.clear(url_str, request.profile)
    domain = cookie_manager.registrable_domain(url_str)
    cleared_cache_entries = web_reader.clear_cache_for_domain(domain)
    await publish_purge(domain)

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
    cookie, or one localStorage entry the site set on its own origin, must
    belong to the domain. Drops other-domain cookies and origins, saves with
    the import provenance, and purges the domain read cache like a clear.
    """
    url_str = str(request.url)
    parsed_host = urlparse(url_str).hostname or ""
    extracted = _IMPORT_TLD_EXTRACT(parsed_host.lower())
    if not extracted.domain or not extracted.suffix:
        raise UnsafeUriError(f"URL host has no registrable domain: {parsed_host}")
    domain = f"{extracted.domain}.{extracted.suffix}"

    effective_profile = check_profile(request.profile or settings.SESSION_DEFAULT_PROFILE)

    kept = [cookie for cookie in request.storage_state.cookies if _belongs_to_domain(cookie.domain, domain)]
    dropped_cookies = len(request.storage_state.cookies) - len(kept)
    filtered_state = {
        "cookies": [cookie.model_dump(by_alias=True) for cookie in kept],
        "origins": [
            origin.model_dump(by_alias=True)
            for origin in request.storage_state.origins
            if _belongs_to_domain(urlparse(origin.origin).hostname or "", domain)
        ],
    }
    if not holds_login_state(filtered_state, domain):
        raise NoCookiesForDomainError(f"no cookie and no localStorage entry of the site belongs to {domain}")

    user_agent = request.user_agent or random.choice(web_reader.user_agents)
    await cookie_manager.save_storage_state(
        url_str,
        filtered_state,
        user_agent,
        effective_profile,
        produced_by=PRODUCED_BY_IMPORT,
        replaces_login=True,
    )
    web_reader.clear_cache_for_domain(domain)
    await publish_purge(domain)

    auth_cookies = sum(1 for cookie in kept if not is_waf_cookie(cookie.name))
    waf_cookies = sum(1 for cookie in kept if is_waf_cookie(cookie.name))

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


@rest_session_router.delete("/interventions/{flow_id}", status_code=204)
async def cancel_intervention(flow_id: str) -> Response:
    """
    Close one open human-intervention window and free its slot.

    Nothing the window holds is saved. The flow ends with the outcome
    `cancelled`, which the session status shows as its `last_window`.
    Answers 204, or 404 with code `flow_not_found` when no open window has
    this `flow_id`.
    """
    await novnc_flow_registry.cancel(flow_id)

    return Response(status_code=204)

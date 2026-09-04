from typing import Any

from fastmcp import FastMCP

from src.api.exceptions import HumanInterventionRequiredException
from src.observability.metrics import HUMAN_INTERVENTION_TOTAL
from src.reader.cloudflare.cookie_manager import cookie_manager
from src.reader.web_reader import WebReader
from src.search.search_client import SearxngClient
from src.session.session_manager import session_manager
from src.validator.url_validator import is_safe_external_url

mcp = FastMCP("AscendWebSearch")
search_client = SearxngClient()
web_reader = WebReader()

MAX_QUERY_LENGTH = 500


@mcp.tool()
async def web_search(query: str, limit: int = 5) -> list[dict[str, Any]]:
    """
    Search the web for a query using SearXNG.
    Args:
        query: The search query.
        limit: Max results (default 5).
    """
    if not query or not query.strip():
        raise ValueError("query must not be empty")
    if len(query) > MAX_QUERY_LENGTH:
        raise ValueError(f"query exceeds maximum length of {MAX_QUERY_LENGTH} characters")

    return await search_client.search(query=query, limit=limit)


@mcp.tool()
async def web_read(
    url: str,
    include_links: bool = False,
    link_filter: str | None = None,
    heavy_mode: bool = False,
    profile: str | None = None,
) -> dict[str, Any]:
    """
    Read (scrape) the content of a web page.
    IMPORTANT: If the status returned is `human_intervention_required`, display the `vnc_url` to the user
    and ask them to open it in their browser to manually solve the Captcha or log into the required account.
    Args:
        url: The URL to read.
        include_links: When True, returns annotated content with inline [N] link markers
                       and a numbered link map {1: url, 2: url, ...}.
        link_filter: Optional URL substring - when set, only links whose href contains
                     this string are included in the link map (e.g. '/job-offer/').
        heavy_mode: If True, skips lightweight strategies and jumps straight to advanced browser strategies.
        profile: Optional session profile label (e.g. 'work', 'personal') for multi-account sites.
    """
    if not is_safe_external_url(url):
        raise ValueError("URL resolves to a private, loopback, link-local, or otherwise non-routable address")

    try:
        if include_links:
            return await web_reader.read_with_links(url, link_filter, heavy_mode=heavy_mode, profile=profile)

        return await web_reader.read(url, heavy_mode=heavy_mode, profile=profile)
    except HumanInterventionRequiredException as exc:
        HUMAN_INTERVENTION_TOTAL.labels(intervention_type=exc.intervention_type).inc()

        return {
            "status": "human_intervention_required",
            "intervention_type": exc.intervention_type,
            "vnc_url": exc.vnc_url,
            "message": exc.message,
        }


@mcp.tool()
async def session_establish(url: str, profile: str | None = None) -> dict[str, Any]:
    """
    Proactively open the NoVNC login flow for a site.
    IMPORTANT: When this returns status='human_intervention_required', display the vnc_url to the user
    and ask them to complete the login in their browser. The session will be captured automatically.
    Args:
        url: The site URL to establish a session for.
        profile: Optional profile label to use (e.g. 'work', 'personal').
    """
    if not is_safe_external_url(url):
        raise ValueError("URL resolves to a private, loopback, link-local, or otherwise non-routable address")

    vnc_url = await session_manager.establish(url, profile)
    HUMAN_INTERVENTION_TOTAL.labels(intervention_type="login").inc()
    return {
        "status": "human_intervention_required",
        "intervention_type": "login",
        "vnc_url": vnc_url,
        "message": f"Login required. Please visit: {vnc_url}",
    }


@mcp.tool()
async def session_status(url: str, profile: str | None = None) -> dict[str, Any]:
    """
    Query the authentication session status for a URL.
    Args:
        url: The site URL to check the session for.
        profile: Optional profile label (e.g. 'work', 'personal').
    Returns status ('active', 'expired', 'none'), remaining auth TTL in seconds,
    and the timestamp of the last validated session.
    """
    if not is_safe_external_url(url):
        raise ValueError("URL resolves to a private, loopback, link-local, or otherwise non-routable address")

    info = await session_manager.status(url, profile)
    return {"url": url, **info.to_dict()}


@mcp.tool()
async def session_clear(url: str, profile: str | None = None) -> dict[str, Any]:
    """
    Delete the stored session for a site, including any cached read results
    for that domain. Idempotent: always succeeds, whether or not a session
    existed.
    Args:
        url: The site URL whose session should be cleared.
        profile: Optional profile label (e.g. 'work', 'personal').
    """
    if not is_safe_external_url(url):
        raise ValueError("URL resolves to a private, loopback, link-local, or otherwise non-routable address")

    existed = await session_manager.clear(url, profile)
    domain = cookie_manager._get_domain(url)  # noqa: SLF001
    cleared_cache_entries = web_reader.clear_cache_for_domain(domain)

    return {
        "status": "cleared",
        "url": url,
        "existed": existed,
        "cleared_cache_entries": cleared_cache_entries,
    }

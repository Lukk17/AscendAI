import logging
from typing import Any, NoReturn

from ascend_python_common.errors import INTERNAL, INTERNAL_FIXED_DETAIL, resolve_detail
from ascend_python_common.uri_guard import FetchPolicy, check_fetch_uri
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

from src.api.exception_handlers import error_registry
from src.api.exceptions import HumanInterventionRequiredException, NoVNCFlowBusyException
from src.config.config import settings
from src.observability.metrics import HUMAN_INTERVENTION_TOTAL, NOVNC_FLOW_BUSY_TOTAL
from src.reader.cloudflare.cookie_manager import cookie_manager
from src.reader.web_reader import OutputFormat, TierName, WebReader
from src.search.search_client import SearxngClient
from src.session.session_manager import session_manager

mcp = FastMCP("ascend-web-hunter")
search_client = SearxngClient()
web_reader = WebReader()

logger = logging.getLogger(__name__)

MAX_QUERY_LENGTH = 500


def _fetch_policy() -> FetchPolicy:
    return FetchPolicy(
        allowed_hosts=tuple(settings.ALLOWED_PRIVATE_HOSTS),
        file_root=None,
        max_redirect_hops=settings.FETCH_MAX_REDIRECT_HOPS,
    )


async def _check_url(operation: str, url: str) -> None:
    try:
        await check_fetch_uri(url, _fetch_policy())
    except Exception as exc:
        _raise_mapped_error(operation, exc)


def _raise_mapped_error(operation: str, exc: Exception) -> NoReturn:
    entry = error_registry.lookup(exc)
    if entry is not None:
        raise ToolError(f"{entry.code.code}: {resolve_detail(entry, exc)}") from exc

    logger.exception(f"MCP {operation} failed")

    raise ToolError(f"{INTERNAL.code}: {INTERNAL_FIXED_DETAIL}") from exc


@mcp.tool()
async def web_search(query: str, limit: int = 5) -> list[dict[str, Any]]:
    """
    Search the web for a query using SearXNG.
    Args:
        query: The search query.
        limit: Max results (default 5).
    """
    if not query or not query.strip():
        _raise_mapped_error("web_search", ValueError("query must not be empty"))
    if len(query) > MAX_QUERY_LENGTH:
        _raise_mapped_error(
            "web_search", ValueError(f"query exceeds maximum length of {MAX_QUERY_LENGTH} characters")
        )

    try:
        return await search_client.search(query=query, limit=limit)
    except Exception as exc:
        _raise_mapped_error("web_search", exc)


@mcp.tool()
async def web_read(
    url: str,
    include_links: bool = False,
    link_filter: str | None = None,
    heavy_mode: bool = False,
    profile: str | None = None,
    output_format: OutputFormat = "text",
    tier: TierName | None = None,
) -> dict[str, Any]:
    """
    Read (scrape) the content of a web page.
    IMPORTANT: If the status returned is `human_intervention_required`, display the `vnc_url` to the user
    and ask them to open it in their browser to manually solve the Captcha or log into the required account.
    If the status returned is `session_expired`, the stored login for that site has lapsed: call
    `session_establish` for the same url and profile, then read again.
    Args:
        url: The URL to read.
        include_links: When True, returns annotated content with inline [N] link markers
                       and a numbered link map {1: url, 2: url, ...}.
        link_filter: Optional URL substring - when set, only links whose href contains
                     this string are included in the link map (e.g. '/job-offer/').
        heavy_mode: If True, skips lightweight strategies and jumps straight to advanced browser strategies.
        profile: Optional session profile label (e.g. 'work', 'personal') for multi-account sites.
        output_format: 'text' for the flat content field, 'structured' to also get title, author,
                       date and sitename. Not available together with include_links.
        tier: Start the extraction chain at this tier ('1-beautifulsoup', '2-trafilatura',
              '3-flaresolverr', '4-playwright_stealth', '5-crawlee_adaptive', '6-novnc') instead of
              where heavy_mode and the stored session would start it. Escalation continues after it.
    """
    await _check_url("web_read", url)

    if include_links and output_format == "structured":
        _raise_mapped_error(
            "web_read",
            ValueError(
                "output_format=structured is not available with include_links: the annotated-links "
                "response carries the flat content shape plus a link map"
            ),
        )

    try:
        if include_links:
            return await web_reader.read_with_links(
                url,
                link_filter,
                heavy_mode=heavy_mode,
                profile=profile,
                output_format=output_format,
                tier=tier,
            )

        return await web_reader.read(
            url, heavy_mode=heavy_mode, profile=profile, output_format=output_format, tier=tier
        )
    except HumanInterventionRequiredException as exc:
        HUMAN_INTERVENTION_TOTAL.labels(intervention_type=exc.intervention_type).inc()

        return {
            "status": "human_intervention_required",
            "intervention_type": exc.intervention_type,
            "vnc_url": exc.vnc_url,
            "message": exc.message,
        }
    except NoVNCFlowBusyException as exc:
        NOVNC_FLOW_BUSY_TOTAL.inc()

        return {
            "status": "novnc_busy",
            "message": exc.message,
            "holder_url": exc.holder_url,
            "holder_profile": exc.holder_profile,
        }
    except Exception as exc:
        _raise_mapped_error("web_read", exc)


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
    await _check_url("session_establish", url)

    try:
        vnc_url = await session_manager.establish(url, profile)
    except NoVNCFlowBusyException as exc:
        NOVNC_FLOW_BUSY_TOTAL.inc()

        return {
            "status": "novnc_busy",
            "message": exc.message,
            "holder_url": exc.holder_url,
            "holder_profile": exc.holder_profile,
        }
    except Exception as exc:
        _raise_mapped_error("session_establish", exc)

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
    await _check_url("session_status", url)

    try:
        info = await session_manager.status(url, profile)
    except Exception as exc:
        _raise_mapped_error("session_status", exc)
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
    await _check_url("session_clear", url)

    try:
        existed = await session_manager.clear(url, profile)
    except Exception as exc:
        _raise_mapped_error("session_clear", exc)
    domain = cookie_manager.registrable_domain(url)
    cleared_cache_entries = web_reader.clear_cache_for_domain(domain)

    return {
        "status": "cleared",
        "url": url,
        "existed": existed,
        "cleared_cache_entries": cleared_cache_entries,
    }

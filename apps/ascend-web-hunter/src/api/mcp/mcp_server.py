import logging
import time
from importlib.metadata import version as package_version
from typing import Any, NoReturn

from ascend_python_common.errors import INTERNAL, INTERNAL_FIXED_DETAIL, resolve_detail
from ascend_python_common.uri_guard import FetchPolicy, check_fetch_uri
from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError

from src.api.exception_handlers import error_registry
from src.api.exceptions import (
    FormatCombinationError,
    HumanInterventionRequiredException,
    NoVNCFlowBusyException,
)
from src.config.config import settings
from src.crawl.job_service import job_service, resolve_tenant
from src.crawl.models import (
    CrawlJobList,
    CrawlJobView,
    CrawlRequest,
    CrawlSubmission,
    JobNotFoundError,
)
from src.observability.metrics import HUMAN_INTERVENTION_TOTAL, NOVNC_FLOW_BUSY_TOTAL
from src.reader.cache_purge import publish_purge
from src.reader.cloudflare.cookie_manager import cookie_manager
from src.reader.novnc.flow_registry import flow_shape, novnc_flow_registry
from src.reader.web_reader import OutputFormat, TierName, WebReader
from src.search.search_client import SearxngClient
from src.session.session_manager import session_manager

mcp = FastMCP("ascend-web-hunter", version=package_version("ascend-web-hunter"))
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
    extraction_schema: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Read (scrape) the content of a web page.
    IMPORTANT: If the status returned is `human_intervention_required`, display the `vnc_url` to the user
    and ask them to open it in their browser to manually solve the Captcha or log into the required account.
    Several windows may be open at once: surface the window's `slot` alongside the `vnc_url` so the user
    opens the window that belongs to this read.
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
                       date and sitename, 'schema' for JSON validated against extraction_schema,
                       'tables' for HTML tables as rows, 'screenshot' for a base64 PNG.
                       Every format but 'text' is refused together with include_links.
        tier: Start the extraction chain at this tier ('1-beautifulsoup', '2-trafilatura',
              '3-flaresolverr', '4-playwright_stealth', '4a-patchright', '4b-camoufox',
              '5-crawlee_adaptive', '6-novnc') instead of
              where heavy_mode and the stored session would start it. Escalation continues after it.
        extraction_schema: JSON Schema the 'schema' output format extracts and validates
                        against. Required with output_format='schema', ignored otherwise.
    """
    await _check_url("web_read", url)

    if include_links and output_format != "text":
        _raise_mapped_error("web_read", FormatCombinationError(output_format))

    if output_format == "schema" and extraction_schema is None:
        _raise_mapped_error(
            "web_read", ValueError("extraction_schema is required with output_format=schema")
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
            url,
            heavy_mode=heavy_mode,
            profile=profile,
            output_format=output_format,
            tier=tier,
            extraction_schema=extraction_schema,
        )
    except HumanInterventionRequiredException as exc:
        HUMAN_INTERVENTION_TOTAL.labels(
            intervention_type=exc.intervention_type, joined=str(exc.joined).lower()
        ).inc()

        return {
            "status": "human_intervention_required",
            "intervention_type": exc.intervention_type,
            "vnc_url": exc.vnc_url,
            "flow_id": exc.flow_id,
            "joined": exc.joined,
            "window": exc.window,
            "message": exc.message,
        }
    except NoVNCFlowBusyException as exc:
        NOVNC_FLOW_BUSY_TOTAL.inc()

        return {
            "status": "novnc_busy",
            "message": exc.message,
            "holder_url": exc.holder_url,
            "holder_profile": exc.holder_profile,
            "active_flows": exc.active_flows,
            "max_concurrent_flows": exc.max_concurrent_flows,
            "flows": exc.flows,
        }
    except Exception as exc:
        _raise_mapped_error("web_read", exc)


@mcp.tool()
async def session_establish(url: str, profile: str | None = None) -> dict[str, Any]:
    """
    Proactively open the NoVNC login flow for a site.
    IMPORTANT: When this returns status='human_intervention_required', display the vnc_url to the user
    and ask them to complete the login in their browser. Several windows may be open at once: surface
    the window's `slot` alongside the `vnc_url` so the user opens the right one. The session will be
    captured automatically.
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
            "active_flows": exc.active_flows,
            "max_concurrent_flows": exc.max_concurrent_flows,
            "flows": exc.flows,
        }
    except Exception as exc:
        _raise_mapped_error("session_establish", exc)

    HUMAN_INTERVENTION_TOTAL.labels(intervention_type="login", joined="false").inc()
    return {
        "status": "human_intervention_required",
        "intervention_type": "login",
        "vnc_url": vnc_url,
        "message": f"Login required. Please visit: {vnc_url}",
    }


@mcp.tool()
async def session_interventions() -> dict[str, Any]:
    """
    List the live human-intervention windows of every container.

    Read-only: each entry carries the window's slot alongside the vnc_url so a
    human or an agent can tell the windows apart, with the remaining lease.
    Returns no cookies, storage state or page content.
    """
    flows = await novnc_flow_registry.active()
    now = time.time()

    return {
        "active_flows": len(flows),
        "max_concurrent_flows": settings.NOVNC_MAX_CONCURRENT_FLOWS,
        "flows": [flow_shape(flow, now) for flow in flows],
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
    await publish_purge(domain)

    return {
        "status": "cleared",
        "url": url,
        "existed": existed,
        "cleared_cache_entries": cleared_cache_entries,
    }


def _mcp_tenant(ctx: Context | None) -> str:
    meta = ctx.request_context.meta if ctx is not None and ctx.request_context is not None else None
    raw = meta.get("ascend.ai/tenant_id") if isinstance(meta, dict) else None
    return resolve_tenant(raw if isinstance(raw, str) else None)


@mcp.tool()
async def crawl_submit(
    seeds: list[str],
    include_patterns: list[str] | None = None,
    exclude_patterns: list[str] | None = None,
    max_depth: int | None = None,
    page_budget: int | None = None,
    same_domain_only: bool = True,
    respect_robots: bool = True,
    output_format: OutputFormat = "text",
    extraction_schema: dict[str, Any] | None = None,
    profile: str | None = None,
    ctx: Context | None = None,
) -> dict[str, Any]:
    """
    Crawl a site as one job and poll it: submit seeds, then read the job back
    with crawl_job_status until it reaches a terminal state. Results land in
    the object store and are listed by crawl_job_status.
    Args:
        seeds: Absolute http or https URLs the crawl starts from.
        include_patterns: Glob patterns against the URL path; when set, only
                          matching links are followed.
        exclude_patterns: Glob patterns against the URL path that are never followed.
        max_depth: Link depth below the seeds. Defaults to the service setting.
        page_budget: Most pages the job reads. Defaults to the service setting.
        same_domain_only: When True, links outside the seeds' domains are dropped.
        respect_robots: When True, robots.txt and crawl-delay are honoured.
        output_format: 'text' for the flat content field, 'structured' to also get title, author,
                       date and sitename, 'schema' for JSON validated against extraction_schema,
                       'tables' for HTML tables as rows, 'screenshot' for a base64 PNG.
        extraction_schema: JSON Schema the 'schema' output format extracts and validates
                        against. Required with output_format='schema', ignored otherwise.
        profile: Optional session profile label (e.g. 'work', 'personal').
    """
    fields: dict[str, Any] = {
        "seeds": seeds,
        "include_patterns": include_patterns or [],
        "exclude_patterns": exclude_patterns or [],
        "same_domain_only": same_domain_only,
        "respect_robots": respect_robots,
        "output_format": output_format,
        "extraction_schema": extraction_schema,
        "profile": profile,
    }
    if max_depth is not None:
        fields["max_depth"] = max_depth
    if page_budget is not None:
        fields["page_budget"] = page_budget
    try:
        record = await job_service.submit_job(_mcp_tenant(ctx), CrawlRequest(**fields))
    except Exception as exc:
        _raise_mapped_error("crawl_submit", exc)
    return CrawlSubmission(
        job_id=record.job_id,
        state=record.state,
        poll_after_seconds=settings.CRAWL_POLL_AFTER_SECONDS,
    ).model_dump(mode="json")


@mcp.tool()
async def crawl_job_status(job_id: str, ctx: Context | None = None) -> dict[str, Any]:
    """
    Read the state, counts and result keys of one crawl job.
    Args:
        job_id: The job identifier a crawl_submit answered.
    """
    try:
        record = await job_service.get_job(_mcp_tenant(ctx), job_id)
    except Exception as exc:
        _raise_mapped_error("crawl_job_status", exc)
    if record is None:
        _raise_mapped_error("crawl_job_status", JobNotFoundError(job_id))
    return CrawlJobView.from_record(record).model_dump(mode="json")


@mcp.tool()
async def crawl_list_jobs(ctx: Context | None = None) -> dict[str, Any]:
    """
    List the retained crawl jobs of the caller's tenant.
    """
    try:
        records = await job_service.list_jobs(_mcp_tenant(ctx))
    except Exception as exc:
        _raise_mapped_error("crawl_list_jobs", exc)
    return CrawlJobList(
        jobs=[CrawlJobView.from_record(record) for record in records]
    ).model_dump(mode="json")


@mcp.tool()
async def crawl_cancel_job(job_id: str, ctx: Context | None = None) -> dict[str, Any]:
    """
    Cancel one crawl job. A waiting or running job moves to cancelled; a job
    in a terminal state is answered unchanged.
    Args:
        job_id: The job identifier a crawl_submit answered.
    """
    try:
        record = await job_service.cancel_job(_mcp_tenant(ctx), job_id)
    except Exception as exc:
        _raise_mapped_error("crawl_cancel_job", exc)
    if record is None:
        _raise_mapped_error("crawl_cancel_job", JobNotFoundError(job_id))
    return CrawlJobView.from_record(record).model_dump(mode="json")

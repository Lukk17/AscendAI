from typing import List, Dict, Any, Union

from fastmcp import FastMCP

from src.reader.web_reader import WebReader
from src.search.search_client import SearxngClient
from src.validator.url_validator import is_safe_external_url

mcp = FastMCP("AscendWebSearch")
search_client = SearxngClient()
web_reader = WebReader()

MAX_QUERY_LENGTH = 500


@mcp.tool()
async def web_search(query: str, limit: int = 5) -> List[Dict[str, Any]]:
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
) -> Union[Dict[str, Any], str]:
    """
    Read (scrape) the content of a web page.
    IMPORTANT: If the status returned is `human_intervention_required`, display the `vnc_url` to the user and ask them to open it in their browser to manually solve the Captcha or log into the required account.
    Args:
        url: The URL to read.
        include_links: When True, returns annotated content with inline [N] link markers
                       and a numbered link map {1: url, 2: url, ...}.
        link_filter: Optional URL substring — when set, only links whose href contains
                     this string are included in the link map (e.g. '/job-offer/').
        heavy_mode: If True, skips lightweight strategies and jumps straight to advanced browser strategies.
    """
    if not is_safe_external_url(url):
        raise ValueError(
            "URL resolves to a private, loopback, link-local, or otherwise non-routable address"
        )
    if include_links:
        return await web_reader.read_with_links(url, link_filter, heavy_mode=heavy_mode)
    return await web_reader.read(url, heavy_mode=heavy_mode)

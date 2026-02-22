from typing import List, Dict, Any, Union

from fastmcp import FastMCP

from src.reader.web_reader import WebReader
from src.search.search_client import SearxngClient

mcp = FastMCP("AscendWebSearch")
search_client = SearxngClient()
web_reader = WebReader()


@mcp.tool()
def web_search(query: str, limit: int = 5) -> List[Dict[str, Any]]:
    """
    Search the web for a query using SearXNG.
    Args:
        query: The search query.
        limit: Max results (default 5).
    """
    return search_client.search(query=query, limit=limit)


@mcp.tool()
async def web_read(
        url: str,
        include_links: bool = False,
        link_filter: str | None = None,
) -> Union[Dict[str, Any], str]:
    """
    Read (scrape) the content of a web page.
    IMPORTANT: If the status returned is `captcha_required`, display the `vnc_url` to the user and ask them to open it in their browser to manually solve the Captcha.
    Args:
        url: The URL to read.
        include_links: When True, returns annotated content with inline [N] link markers
                       and a numbered link map {1: url, 2: url, ...}.
        link_filter: Optional URL substring — when set, only links whose href contains
                     this string are included in the link map (e.g. '/job-offer/').
    """
    if include_links:
        return await web_reader.read_with_links(url, link_filter)
    return await web_reader.read(url)

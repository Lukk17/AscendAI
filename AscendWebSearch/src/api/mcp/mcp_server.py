from typing import List, Dict, Any

from fastmcp import FastMCP

from src.reader.web_reader import WebReader
from src.search.search_client import SearxngClient

# Initialize FastMCP
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
async def web_read(url: str) -> str:
    """
    Read (scrape) the content of a web page.
    Args:
        url: The URL to read.
    """
    return await web_reader.read(url)

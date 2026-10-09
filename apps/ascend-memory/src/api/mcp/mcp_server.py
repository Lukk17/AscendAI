import logging
from typing import Any, NoReturn

from ascend_python_common.errors import INTERNAL, INTERNAL_FIXED_DETAIL, resolve_detail
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

from src.api.exception_handlers import error_registry
from src.config.config import settings
from src.service.memory_client import get_memory_client, resolve_provider, wipe_user_all_collections

logger = logging.getLogger(__name__)

mcp = FastMCP("ascend-memory")


def _raise_mapped_error(operation: str, exc: Exception) -> NoReturn:
    """Re-raise a failure as a tool error whose text starts with the registry code.

    The code and detail come from the service error registry, the same mapping
    the library McpRefusalMiddleware applies to registered exceptions.
    """

    entry = error_registry.lookup(exc)
    if entry is not None:
        raise ToolError(f"{entry.code.code}: {resolve_detail(entry, exc)}") from exc

    logger.exception(f"MCP {operation} failed")

    raise ToolError(f"{INTERNAL.code}: {INTERNAL_FIXED_DETAIL}") from exc


@mcp.tool()
def memory_insert(
    text: str,
    user_id: str | None = None,
    provider: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Add a new memory for a user.
    Args:
        text: The memory content (required).
        user_id: The user ID; defaults to DEFAULT_USER_ID when omitted.
        provider: Embedding provider; defaults to MEM0_DEFAULT_PROVIDER.
        metadata: Optional metadata.
    """

    try:
        if not text or not text.strip():
            raise ValueError("text must not be empty")
        if len(text) > settings.MAX_MEMORY_TEXT_LENGTH:
            raise ValueError(f"text exceeds maximum length of {settings.MAX_MEMORY_TEXT_LENGTH} characters")

        resolved_provider = resolve_provider(provider)
        effective_user_id = user_id or settings.DEFAULT_USER_ID

        results = get_memory_client(resolved_provider).add(
            user_id=effective_user_id, text=text, metadata=metadata
        )

        return {"status": "success", "results": results}
    except Exception as exc:
        _raise_mapped_error("memory_insert", exc)


@mcp.tool()
def memory_search(
    query: str,
    user_id: str | None = None,
    limit: int = 5,
    provider: str | None = None,
) -> dict[str, Any]:
    """
    Search for memories.
    Args:
        query: Search query (required).
        user_id: The user ID; defaults to DEFAULT_USER_ID when omitted.
        limit: Max results (1-100; default 5).
        provider: Embedding provider; defaults to MEM0_DEFAULT_PROVIDER.
    """

    try:
        if not query or not query.strip():
            raise ValueError("query must not be empty")
        if len(query) > settings.MAX_QUERY_LENGTH:
            raise ValueError(f"query exceeds maximum length of {settings.MAX_QUERY_LENGTH} characters")
        if limit < 1 or limit > settings.MAX_SEARCH_LIMIT:
            raise ValueError(f"limit must be between 1 and {settings.MAX_SEARCH_LIMIT}")

        resolved_provider = resolve_provider(provider)
        effective_user_id = user_id or settings.DEFAULT_USER_ID

        results = get_memory_client(resolved_provider).search(
            query=query, user_id=effective_user_id, limit=limit
        )

        return {"status": "success", "results": results}
    except Exception as exc:
        _raise_mapped_error("memory_search", exc)


@mcp.tool()
def memory_delete(memory_id: str, provider: str | None = None) -> dict[str, Any]:
    """
    Delete a memory by ID.
    Args:
        memory_id: The ID of the memory to delete.
        provider: Embedding provider; defaults to MEM0_DEFAULT_PROVIDER.
    """

    try:
        if not memory_id or not memory_id.strip():
            raise ValueError("memory_id must not be empty")

        resolved_provider = resolve_provider(provider)
        get_memory_client(resolved_provider).delete(memory_id=memory_id)

        return {"status": "success", "message": f"Memory {memory_id} deleted."}
    except Exception as exc:
        _raise_mapped_error("memory_delete", exc)


@mcp.tool()
def memory_wipe(user_id: str | None = None, provider: str | None = None) -> dict[str, Any]:
    """
    Wipe all memories for a user.
    Args:
        user_id: The user ID; defaults to DEFAULT_USER_ID when omitted.
        provider: Embedding provider; defaults to MEM0_DEFAULT_PROVIDER.
    """

    try:
        effective_user_id = user_id or settings.DEFAULT_USER_ID

        if provider is None or not provider.strip():
            wipe_user_all_collections(user_id=effective_user_id)
        else:
            get_memory_client(resolve_provider(provider)).wipe_user(user_id=effective_user_id)

        return {"status": "success", "message": f"All memories wiped for user {effective_user_id}."}
    except Exception as exc:
        _raise_mapped_error("memory_wipe", exc)

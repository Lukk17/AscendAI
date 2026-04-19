from typing import List, Optional

from fastmcp import FastMCP

from src.config.config import settings
from src.service.memory_client import get_memory_client

mcp = FastMCP("AscendMemory")


@mcp.tool()
def memory_insert(user_id: str, text: str, provider: Optional[str] = None,
                  metadata: Optional[dict] = None) -> List[dict]:
    """
    Add a new memory for a user.
    Args:
        user_id: The user ID.
        text: The memory content.
        provider: Embedding provider to use (default: MEM0_DEFAULT_PROVIDER).
        metadata: Optional metadata.
    """
    return get_memory_client(provider or settings.MEM0_DEFAULT_PROVIDER).add(
        user_id=user_id, text=text, metadata=metadata)


@mcp.tool()
def memory_search(user_id: str = "default_user", query: str = "", limit: int = 5,
                  provider: Optional[str] = None) -> List[dict]:
    """
    Search for memories.
    Args:
        user_id: The user ID.
        query: Search query.
        limit: Max results.
        provider: Embedding provider to use (default: MEM0_DEFAULT_PROVIDER).
    """
    return get_memory_client(provider or settings.MEM0_DEFAULT_PROVIDER).search(
        user_id=user_id, query=query, limit=limit)


@mcp.tool()
def memory_delete(memory_id: str, provider: Optional[str] = None) -> str:
    """
    Delete a memory by ID.
    Args:
        memory_id: The ID of the memory to delete.
        provider: Embedding provider to use (default: MEM0_DEFAULT_PROVIDER).
    """
    get_memory_client(provider or settings.MEM0_DEFAULT_PROVIDER).delete(memory_id=memory_id)
    return f"Memory {memory_id} deleted."


@mcp.tool()
def memory_wipe(user_id: str, provider: Optional[str] = None) -> str:
    """
    Wipe all memories for a user.
    Args:
        user_id: The user ID.
        provider: Embedding provider to use (default: MEM0_DEFAULT_PROVIDER).
    """
    get_memory_client(provider or settings.MEM0_DEFAULT_PROVIDER).wipe_user(user_id=user_id)
    return f"All memories wiped for user {user_id}."
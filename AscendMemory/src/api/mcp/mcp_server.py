from typing import List, Optional

from fastmcp import FastMCP

from src.service.memory_client import AscendMemoryClient, get_memory_client

mcp = FastMCP("AscendMemory")


@mcp.tool()
def memory_insert(user_id: str, text: str, metadata: Optional[dict] = None) -> List[dict]:
    """
    Add a new memory for a user.
    Args:
        user_id: The user ID.
        text: The memory content.
        metadata: Optional metadata.
    """
    return get_client().add(user_id=user_id, text=text, metadata=metadata)


@mcp.tool()
def memory_search(user_id: str = "default_user", query: str = "", limit: int = 5) -> List[dict]:
    """
    Search for memories.
    Args:
        user_id: The user ID.
        query: Search query.
        limit: Max results.
    """
    return get_client().search(user_id=user_id, query=query, limit=limit)


@mcp.tool()
def memory_delete(memory_id: str) -> str:
    """
    Delete a memory by ID.
    Args:
        memory_id: The ID of the memory to delete.
    """
    get_client().delete(memory_id=memory_id)
    return f"Memory {memory_id} deleted."


@mcp.tool()
def memory_wipe(user_id: str) -> str:
    """
    Wipe all memories for a user.
    Args:
        user_id: The user ID.
    """
    get_client().wipe_user(user_id=user_id)
    return f"All memories wiped for user {user_id}."

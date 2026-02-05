from typing import List, Optional, Dict, Any

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

from src.service.memory_client import AscendMemoryClient, get_memory_client

rest_router = APIRouter(prefix="/api/v1/memory", tags=["memory"])


class UpsertRequest(BaseModel):
    user_id: str
    messages: Optional[List[Dict[str, str]]] = None
    text: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class SearchResponseItem(BaseModel):
    id: str
    memory: str
    score: Optional[float] = None
    metadata: Optional[Dict[str, Any]] = None
    created_at: Optional[str] = None


@rest_router.get("/search", response_model=List[Dict[str, Any]])
def search_memory(
        user_id: str,
        query: str,
        limit: int = 5,
        client: AscendMemoryClient = Depends(get_memory_client)
):
    """
    Search for memories relevant to the query.
    """
    return client.search(query=query, user_id=user_id, limit=limit)


@rest_router.post("/upsert")
def upsert_memory(
        request: UpsertRequest,
        client: AscendMemoryClient = Depends(get_memory_client)
):
    """
    Add a new memory.
    """
    try:
        return client.add(
            user_id=request.user_id,
            messages=request.messages,
            text=request.text,
            metadata=request.metadata
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@rest_router.post("/wipe")
def wipe_memory(
        user_id: str,
        client: AscendMemoryClient = Depends(get_memory_client)
):
    """
    Wipe all memories for a user.
    """
    client.wipe_user(user_id=user_id)
    return {"status": "success", "message": f"All memories wiped for user {user_id}"}


@rest_router.delete("")
def delete_memory(
        memory_id: str,
        client: AscendMemoryClient = Depends(get_memory_client)
):
    """
    Delete a specific memory by ID.
    """
    if not memory_id:
        raise HTTPException(status_code=400, detail="memory_id is required")

    client.delete(memory_id=memory_id)
    return {"status": "success", "message": f"Memory {memory_id} deleted"}

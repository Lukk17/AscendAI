import asyncio
import time
from typing import Annotated, Any

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from src.config.config import settings
from src.observability.metrics import (
    MEMORY_INSERT_DURATION_SECONDS,
    MEMORY_INSERT_TOTAL,
    MEMORY_SEARCH_DURATION_SECONDS,
    MEMORY_SEARCH_TOTAL,
)
from src.service.memory_client import get_memory_client, resolve_provider, wipe_user_all_collections

rest_router = APIRouter(prefix="/api/v1/memory", tags=["memory"])

# Single source of truth for the user_id input alphabet so the REST query
# parameter, the InsertRequest body field, and the wipe query parameter
# can't drift. Allows ASCII letters/digits/`._-@:+` up to MAX_USER_ID_LENGTH.
USER_ID_PATTERN = r"^[A-Za-z0-9._\-@:+]{1,128}$"


class SearchResponseItem(BaseModel):
    id: str
    memory: str
    user_id: str | None = None
    score: float | None = None
    metadata: dict[str, Any] | None = None
    created_at: str | None = None


# Reusable Annotated query-parameter aliases. Defaults are applied on the
# parameter declaration (`= None`, `= 5`) per the FastAPI `Annotated`
# contract; Query() itself only carries the validation constraints.
UserIdQuery = Annotated[
    str | None,
    Query(
        max_length=settings.MAX_USER_ID_LENGTH,
        pattern=USER_ID_PATTERN,
        description="Caller user_id; defaults to DEFAULT_USER_ID when omitted",
    ),
]
ProviderQuery = Annotated[str | None, Query(max_length=32)]
SearchQuery = Annotated[
    str, Query(min_length=1, max_length=settings.MAX_QUERY_LENGTH)
]
SearchLimitQuery = Annotated[int, Query(ge=1, le=settings.MAX_SEARCH_LIMIT)]
MemoryIdQuery = Annotated[str, Query(min_length=1, max_length=256)]


@rest_router.get("/search", response_model=list[SearchResponseItem])
async def search_memory(
    query: SearchQuery,
    user_id: UserIdQuery = None,
    limit: SearchLimitQuery = 5,
    provider: ProviderQuery = None,
) -> list[dict[str, Any]]:
    """Search memories relevant to the query."""

    effective_user_id = user_id or settings.DEFAULT_USER_ID
    resolved_provider = resolve_provider(provider)
    client = get_memory_client(resolved_provider)

    started = time.monotonic()
    outcome = "success"
    try:
        result = await asyncio.to_thread(
            client.search,
            query=query,
            user_id=effective_user_id,
            limit=limit,
        )
    except Exception:
        outcome = "error"
        raise
    finally:
        MEMORY_SEARCH_DURATION_SECONDS.labels(provider=resolved_provider).observe(
            time.monotonic() - started
        )
        MEMORY_SEARCH_TOTAL.labels(provider=resolved_provider, outcome=outcome).inc()
    return result


class InsertRequest(BaseModel):
    user_id: str = Field(
        min_length=1,
        max_length=settings.MAX_USER_ID_LENGTH,
        pattern=USER_ID_PATTERN,
        description="Caller user_id identifying the memory partition to write to",
    )
    text: str | None = Field(
        default=None,
        max_length=settings.MAX_MEMORY_TEXT_LENGTH,
        description="Raw memory content; ignored when `messages` is provided",
    )
    messages: list[dict[str, str]] | None = Field(
        default=None,
        max_length=64,
        description="Chat-shaped messages [{role, content}] to infer memory from",
    )
    metadata: dict[str, Any] | None = Field(default=None)
    provider: str | None = Field(default=None, max_length=32)


@rest_router.post("/insert")
async def insert_memory(request: InsertRequest) -> list[dict[str, Any]]:
    """Add a new memory."""

    if request.text is None and not request.messages:
        raise ValueError("Either 'messages' or 'text' must be provided.")

    resolved_provider = resolve_provider(request.provider)
    client = get_memory_client(resolved_provider)

    started = time.monotonic()
    outcome = "success"
    try:
        result = await asyncio.to_thread(
            client.add,
            user_id=request.user_id,
            messages=request.messages,
            text=request.text,
            metadata=request.metadata,
        )
    except Exception:
        outcome = "error"
        raise
    finally:
        MEMORY_INSERT_DURATION_SECONDS.labels(provider=resolved_provider).observe(
            time.monotonic() - started
        )
        MEMORY_INSERT_TOTAL.labels(provider=resolved_provider, outcome=outcome).inc()
    return result


@rest_router.post("/wipe")
async def wipe_memory(
    user_id: UserIdQuery = None,
    provider: ProviderQuery = None,
) -> dict[str, str]:
    """Wipe a user's memories. With no provider, clears every provider collection."""

    effective_user_id = user_id or settings.DEFAULT_USER_ID

    if provider is None or not provider.strip():
        await asyncio.to_thread(wipe_user_all_collections, user_id=effective_user_id)
    else:
        client = get_memory_client(resolve_provider(provider))

        await asyncio.to_thread(client.wipe_user, user_id=effective_user_id)

    return {"status": "success", "message": f"All memories wiped for user {effective_user_id}"}


@rest_router.delete("")
async def delete_memory(
    memory_id: MemoryIdQuery,
    provider: ProviderQuery = None,
) -> dict[str, str]:
    """Delete a specific memory by ID."""

    resolved_provider = resolve_provider(provider)
    client = get_memory_client(resolved_provider)

    await asyncio.to_thread(client.delete, memory_id=memory_id)

    return {"status": "success", "message": f"Memory {memory_id} deleted"}

from unittest.mock import patch

import pytest
from httpx import AsyncClient

from src.observability.metrics import MEMORY_SEARCH_TOTAL


@pytest.mark.asyncio
async def test_insert_memory_success(client: AsyncClient, override_dependencies):
    mock_service = override_dependencies
    mock_service.add.return_value = [{"id": "m1"}]

    response = await client.post(
        "/api/v1/memory/insert",
        json={"user_id": "u1", "text": "test memory"},
    )

    assert response.status_code == 200
    assert response.json() == [{"id": "m1"}]
    mock_service.add.assert_called_once()


@pytest.mark.asyncio
async def test_insert_memory_with_provider(client: AsyncClient, override_dependencies):
    mock_service = override_dependencies
    mock_service.add.return_value = []

    response = await client.post(
        "/api/v1/memory/insert",
        json={"user_id": "u1", "text": "x", "provider": "openai"},
    )

    assert response.status_code == 200
    mock_service.add.assert_called_once()


@pytest.mark.asyncio
async def test_insert_memory_rejects_missing_user_id(
    client: AsyncClient, override_dependencies
):
    response = await client.post("/api/v1/memory/insert", json={"text": "x"})

    assert response.status_code == 422
    body = response.json()
    assert any(
        "user_id" in str(e.get("loc", [])) for e in body.get("detail", [])
    )


@pytest.mark.asyncio
async def test_insert_memory_rejects_missing_text_and_messages(
    client: AsyncClient, override_dependencies
):
    response = await client.post(
        "/api/v1/memory/insert",
        json={"user_id": "u1"},
    )

    assert response.status_code == 400
    body = response.json()
    assert body["status"] == 400
    assert "messages" in body["detail"] or "text" in body["detail"]


@pytest.mark.asyncio
async def test_search_memory_success(client: AsyncClient, override_dependencies):
    mock_service = override_dependencies
    mock_service.search.return_value = [
        {"id": "m1", "memory": "fact one", "score": 0.8}
    ]

    response = await client.get(
        "/api/v1/memory/search",
        params={"user_id": "u1", "query": "test"},
    )

    assert response.status_code == 200
    assert response.json()[0]["id"] == "m1"
    mock_service.search.assert_called_once()


@pytest.mark.asyncio
async def test_search_memory_response_includes_user_id(
    client: AsyncClient, override_dependencies
):
    mock_service = override_dependencies
    mock_service.search.return_value = [
        {"id": "m1", "memory": "fact one", "score": 0.9, "user_id": "u1"}
    ]

    response = await client.get(
        "/api/v1/memory/search",
        params={"user_id": "u1", "query": "test"},
    )

    assert response.status_code == 200
    item = response.json()[0]
    assert item["user_id"] == "u1"


@pytest.mark.asyncio
async def test_search_memory_rejects_too_long_query(
    client: AsyncClient, override_dependencies
):
    long_q = "x" * 5000

    response = await client.get(
        "/api/v1/memory/search",
        params={"user_id": "u1", "query": long_q},
    )

    assert response.status_code == 422  # pydantic validation


@pytest.mark.asyncio
async def test_search_memory_rejects_user_id_with_unsafe_chars(
    client: AsyncClient, override_dependencies
):
    response = await client.get(
        "/api/v1/memory/search",
        params={"user_id": "../etc/passwd", "query": "q"},
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_search_memory_upstream_failure_maps_to_500_and_records_error_outcome(
    client: AsyncClient, override_dependencies
):
    """When the memory client's search call fails (e.g. Qdrant is down or
    the embedder times out), the caller must see a 500 rather than a
    silently empty result, and the search outcome metric must record
    "error" so the failure is visible in Grafana instead of being lumped
    in with successful searches."""

    mock_service = override_dependencies
    mock_service.search.side_effect = RuntimeError("qdrant connection refused")

    before = MEMORY_SEARCH_TOTAL.labels(provider="lmstudio", outcome="error")._value.get()

    response = await client.get(
        "/api/v1/memory/search",
        params={"user_id": "u1", "query": "test"},
    )

    assert response.status_code == 500
    body = response.json()
    assert body["status"] == 500
    assert body["type"].endswith("/internal")

    after = MEMORY_SEARCH_TOTAL.labels(provider="lmstudio", outcome="error")._value.get()
    assert after == before + 1


@pytest.mark.asyncio
async def test_delete_memory_success(client: AsyncClient, override_dependencies):
    mock_service = override_dependencies

    response = await client.delete("/api/v1/memory", params={"memory_id": "m1"})

    assert response.status_code == 200
    assert response.json()["status"] == "success"
    mock_service.delete.assert_called_once_with(memory_id="m1")


@pytest.mark.asyncio
async def test_wipe_memory_success(client: AsyncClient, override_dependencies):
    with patch("src.api.rest.rest_endpoints.wipe_user_all_collections") as mock_wipe_all:
        response = await client.post("/api/v1/memory/wipe", params={"user_id": "u1"})

    assert response.status_code == 200
    assert response.json()["status"] == "success"
    mock_wipe_all.assert_called_once_with(user_id="u1")


@pytest.mark.asyncio
async def test_wipe_memory_with_explicit_provider_wipes_only_that_provider(
    client: AsyncClient, override_dependencies
):
    """A caller who names a provider (e.g. resetting a single user's
    LM Studio-embedded memories without touching their OpenAI-embedded
    ones) must only wipe that provider's collection, not every provider
    collection the user has data in."""

    mock_service = override_dependencies

    with patch("src.api.rest.rest_endpoints.wipe_user_all_collections") as mock_wipe_all:
        response = await client.post(
            "/api/v1/memory/wipe",
            params={"user_id": "u1", "provider": "openai"},
        )

    assert response.status_code == 200
    assert response.json()["status"] == "success"
    mock_service.wipe_user.assert_called_once_with(user_id="u1")
    mock_wipe_all.assert_not_called()


@pytest.mark.asyncio
async def test_value_error_maps_to_rfc7807_400(
    client: AsyncClient, override_dependencies
):
    mock_service = override_dependencies
    mock_service.add.side_effect = ValueError("nope")

    response = await client.post(
        "/api/v1/memory/insert",
        json={"user_id": "u1", "text": "x"},
    )

    assert response.status_code == 400
    body = response.json()
    assert body["type"].endswith("/validation")
    assert body["detail"] == "nope"
    assert body["status"] == 400


@pytest.mark.asyncio
async def test_unexpected_exception_maps_to_rfc7807_500(
    client: AsyncClient, override_dependencies
):
    mock_service = override_dependencies
    sentinel_leak = "UPSTREAM_LEAK_MARKER_99"
    mock_service.add.side_effect = RuntimeError(f"upstream BLEW UP with {sentinel_leak}")

    response = await client.post(
        "/api/v1/memory/insert",
        json={"user_id": "u1", "text": "x"},
    )

    assert response.status_code == 500
    body = response.json()
    assert body["status"] == 500
    # Internal error must not leak the upstream exception message.
    assert sentinel_leak not in str(body)
    assert body["type"].endswith("/internal")


@pytest.mark.asyncio
async def test_request_id_header_echoed_back(client: AsyncClient, override_dependencies):
    response = await client.get("/health", headers={"X-Request-ID": "trace-123"})

    assert response.headers["X-Request-ID"] == "trace-123"


@pytest.mark.asyncio
async def test_request_id_malformed_replaced_with_uuid(
    client: AsyncClient, override_dependencies
):
    response = await client.get(
        "/health",
        headers={"X-Request-ID": "bad\r\nheader-injection"},
    )

    rid = response.headers["X-Request-ID"]
    assert "\r" not in rid
    assert "\n" not in rid
    assert len(rid) >= 16  # UUID4

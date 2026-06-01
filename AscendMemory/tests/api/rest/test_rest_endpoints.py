import pytest
from httpx import AsyncClient


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
async def test_insert_memory_defaults_user_id_when_omitted(
    client: AsyncClient, override_dependencies
):
    mock_service = override_dependencies
    mock_service.add.return_value = []

    response = await client.post("/api/v1/memory/insert", json={"text": "x"})

    assert response.status_code == 200
    assert mock_service.add.call_args.kwargs["user_id"] == "default_user"


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
async def test_delete_memory_success(client: AsyncClient, override_dependencies):
    mock_service = override_dependencies

    response = await client.delete("/api/v1/memory", params={"memory_id": "m1"})

    assert response.status_code == 200
    assert response.json()["status"] == "success"
    mock_service.delete.assert_called_once_with(memory_id="m1")


@pytest.mark.asyncio
async def test_wipe_memory_success(client: AsyncClient, override_dependencies):
    mock_service = override_dependencies

    response = await client.post("/api/v1/memory/wipe", params={"user_id": "u1"})

    assert response.status_code == 200
    assert response.json()["status"] == "success"
    mock_service.wipe_user.assert_called_once_with(user_id="u1")


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

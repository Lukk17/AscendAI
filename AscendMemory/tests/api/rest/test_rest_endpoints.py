import pytest
from httpx import AsyncClient
from unittest.mock import MagicMock


@pytest.mark.asyncio
async def test_upsert_memory_success(client: AsyncClient, override_dependencies):
    # given
    mock_service = override_dependencies
    mock_service.add.return_value = [{"id": "mem_1"}]
    payload = {
        "user_id": "u1",
        "text": "test memory"
    }

    # when
    response = await client.post("/api/v1/memory/upsert", json=payload)

    # then
    assert response.status_code == 200
    assert response.json() == [{"id": "mem_1"}]
    mock_service.add.assert_called_once()


@pytest.mark.asyncio
async def test_search_memory_success(client: AsyncClient, override_dependencies):
    # given
    mock_service = override_dependencies
    mock_service.search.return_value = [{"id": "mem_1", "score": 0.8}]

    # when
    response = await client.get("/api/v1/memory/search", params={"user_id": "u1", "query": "test"})

    # then
    assert response.status_code == 200
    assert response.json() == [{"id": "mem_1", "score": 0.8}]
    mock_service.search.assert_called_once()


@pytest.mark.asyncio
async def test_delete_memory_success(client: AsyncClient, override_dependencies):
    # given
    mock_service = override_dependencies

    # when
    response = await client.delete("/api/v1/memory", params={"memory_id": "mem_1"})

    # then
    assert response.status_code == 200
    assert response.json()["status"] == "success"
    mock_service.delete.assert_called_once_with(memory_id="mem_1")


@pytest.mark.asyncio
async def test_wipe_memory_success(client: AsyncClient, override_dependencies):
    # given
    mock_service = override_dependencies

    # when
    response = await client.post("/api/v1/memory/wipe", params={"user_id": "u1"})

    # then
    assert response.status_code == 200
    mock_service.wipe_user.assert_called_once_with(user_id="u1")


@pytest.mark.asyncio
async def test_insert_error_handling(client: AsyncClient, override_dependencies):
    # given
    mock_service = override_dependencies
    mock_service.add.side_effect = ValueError("Invalid input")
    payload = {"user_id": "u1", "text": "bad"}

    # when
    response = await client.post("/api/v1/memory/insert", json=payload)

    # then
    assert response.status_code == 400
    assert "Invalid input" in response.json()["detail"]

from unittest.mock import MagicMock, patch

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_insert_success_pins_today_body(client: AsyncClient, override_dependencies: MagicMock) -> None:
    # given
    mock_service = override_dependencies
    mock_service.add.return_value = [{"id": "m1"}]
    # when
    response = await client.post(
        "/api/v1/memory/insert",
        json={"user_id": "u1", "text": "test memory"},
    )
    # then
    assert response.status_code == 200
    assert response.json() == [{"id": "m1"}]


@pytest.mark.asyncio
async def test_search_success_pins_today_body(client: AsyncClient, override_dependencies: MagicMock) -> None:
    # given
    mock_service = override_dependencies
    mock_service.search.return_value = [{"id": "m1", "memory": "fact one", "score": 0.8}]
    # when
    response = await client.get(
        "/api/v1/memory/search",
        params={"user_id": "u1", "query": "test"},
    )
    # then
    assert response.status_code == 200
    assert response.json()[0]["id"] == "m1"


@pytest.mark.asyncio
async def test_delete_success_pins_today_body(client: AsyncClient, override_dependencies: MagicMock) -> None:
    # given
    mock_service = override_dependencies
    # when
    response = await client.delete("/api/v1/memory", params={"memory_id": "m1"})
    # then
    assert response.status_code == 200
    assert response.json()["status"] == "success"
    assert mock_service.delete.call_count == 1


@pytest.mark.asyncio
async def test_wipe_success_pins_today_body(client: AsyncClient, override_dependencies: MagicMock) -> None:
    # given
    with patch("src.api.rest.rest_endpoints.wipe_user_all_collections") as mock_wipe_all:
        # when
        response = await client.post("/api/v1/memory/wipe", params={"user_id": "u1"})
        # then
        assert response.status_code == 200
        assert response.json()["status"] == "success"
        assert mock_wipe_all.call_count == 1

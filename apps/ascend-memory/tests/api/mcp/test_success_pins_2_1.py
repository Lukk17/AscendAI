from unittest.mock import MagicMock, patch

from src.api.mcp.mcp_server import memory_delete, memory_insert, memory_search, memory_wipe


@patch("src.api.mcp.mcp_server.get_memory_client")
def test_mcp_insert_success_pins_today_envelope(mock_get_client: MagicMock) -> None:
    # given
    mock_service = MagicMock()
    mock_service.add.return_value = [{"id": "m1"}]
    mock_get_client.return_value = mock_service
    # when
    result = memory_insert(user_id="u1", text="hello")
    # then
    assert result == {"status": "success", "results": [{"id": "m1"}]}


@patch("src.api.mcp.mcp_server.get_memory_client")
def test_mcp_search_success_pins_today_envelope(mock_get_client: MagicMock) -> None:
    # given
    mock_service = MagicMock()
    mock_service.search.return_value = [{"id": "m1", "score": 0.8}]
    mock_get_client.return_value = mock_service
    # when
    result = memory_search(query="find me")
    # then
    assert result == {"status": "success", "results": [{"id": "m1", "score": 0.8}]}


@patch("src.api.mcp.mcp_server.get_memory_client")
def test_mcp_delete_success_pins_today_envelope(mock_get_client: MagicMock) -> None:
    # given
    mock_service = MagicMock()
    mock_get_client.return_value = mock_service
    # when
    result = memory_delete(memory_id="m1")
    # then
    assert result["status"] == "success"
    assert mock_service.delete.call_count == 1


@patch("src.api.mcp.mcp_server.wipe_user_all_collections")
def test_mcp_wipe_success_pins_today_envelope(mock_wipe_all: MagicMock) -> None:
    # given
    user = "u1"
    # when
    result = memory_wipe(user_id=user)
    # then
    assert result["status"] == "success"
    assert mock_wipe_all.call_count == 1

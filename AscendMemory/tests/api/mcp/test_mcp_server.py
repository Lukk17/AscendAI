from unittest.mock import patch, MagicMock
from src.api.mcp.mcp_server import memory_insert, memory_search, memory_delete, memory_wipe


@patch("src.api.mcp.mcp_server.get_memory_client")
def test_mcp_memory_insert(mock_get_client):
    # given
    mock_service = MagicMock()
    mock_get_client.return_value = mock_service
    mock_service.add.return_value = [{"id": "1"}]

    # when
    result = memory_insert(user_id="u1", text="test")

    # then
    assert result == [{"id": "1"}]
    mock_service.add.assert_called_once_with(user_id="u1", text="test", metadata=None)


@patch("src.api.mcp.mcp_server.get_memory_client")
def test_mcp_memory_search(mock_get_client):
    # given
    mock_service = MagicMock()
    mock_get_client.return_value = mock_service
    mock_service.search.return_value = [{"id": "1"}]

    # when
    result = memory_search(user_id="u1", query="test")

    # then
    assert result == [{"id": "1"}]
    mock_service.search.assert_called_once_with(user_id="u1", query="test", limit=5)


@patch("src.api.mcp.mcp_server.get_memory_client")
def test_mcp_memory_wipe(mock_get_client):
    # given
    mock_service = MagicMock()
    mock_get_client.return_value = mock_service

    # when
    result = memory_wipe(user_id="u1")

    # then
    assert "wiped" in result
    mock_service.wipe_user.assert_called_once_with(user_id="u1")

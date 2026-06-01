from unittest.mock import MagicMock, patch

from src.api.mcp.mcp_server import (
    memory_delete,
    memory_insert,
    memory_search,
    memory_wipe,
)


@patch("src.api.mcp.mcp_server.get_memory_client")
def test_memory_insert_returns_success_envelope(mock_get_client):
    mock_service = MagicMock()
    mock_service.add.return_value = [{"id": "m1"}]
    mock_get_client.return_value = mock_service

    result = memory_insert(user_id="u1", text="hello")

    assert result == {"status": "success", "results": [{"id": "m1"}]}
    mock_service.add.assert_called_once_with(user_id="u1", text="hello", metadata=None)


@patch("src.api.mcp.mcp_server.get_memory_client")
def test_memory_insert_uses_default_user_id_when_omitted(mock_get_client):
    mock_service = MagicMock()
    mock_service.add.return_value = []
    mock_get_client.return_value = mock_service

    memory_insert(text="hello")

    assert mock_service.add.call_args.kwargs["user_id"] == "default_user"


def test_memory_insert_rejects_empty_text():
    result = memory_insert(text="")
    assert result["status"] == "error"
    assert result["code"] == "validation_error"
    assert "empty" in result["message"]


def test_memory_insert_rejects_text_above_cap():
    from src.config.config import settings

    result = memory_insert(text="x" * (settings.MAX_MEMORY_TEXT_LENGTH + 1))
    assert result["code"] == "validation_error"
    assert "maximum length" in result["message"]


@patch("src.api.mcp.mcp_server.get_memory_client")
def test_memory_insert_maps_unexpected_failure_to_internal_error(mock_get_client):
    mock_get_client.side_effect = RuntimeError("upstream burst into flames")

    result = memory_insert(text="hi")

    assert result["status"] == "error"
    assert result["code"] == "internal_error"
    assert "An internal error" in result["message"]


@patch("src.api.mcp.mcp_server.get_memory_client")
def test_memory_search_returns_success_envelope(mock_get_client):
    mock_service = MagicMock()
    mock_service.search.return_value = [{"id": "m1", "score": 0.8}]
    mock_get_client.return_value = mock_service

    result = memory_search(query="find me")

    assert result == {"status": "success", "results": [{"id": "m1", "score": 0.8}]}
    mock_service.search.assert_called_once_with(query="find me", user_id="default_user", limit=5)


def test_memory_search_rejects_empty_query():
    result = memory_search(query="   ")
    assert result["code"] == "validation_error"


def test_memory_search_rejects_query_above_cap():
    from src.config.config import settings

    result = memory_search(query="x" * (settings.MAX_QUERY_LENGTH + 1))
    assert result["code"] == "validation_error"


def test_memory_search_rejects_limit_out_of_range():
    assert memory_search(query="q", limit=0)["code"] == "validation_error"
    from src.config.config import settings
    assert (
        memory_search(query="q", limit=settings.MAX_SEARCH_LIMIT + 1)["code"]
        == "validation_error"
    )


@patch("src.api.mcp.mcp_server.get_memory_client")
def test_memory_delete_returns_success(mock_get_client):
    mock_service = MagicMock()
    mock_get_client.return_value = mock_service

    result = memory_delete(memory_id="m1")

    assert result["status"] == "success"
    assert "m1" in result["message"]
    mock_service.delete.assert_called_once_with(memory_id="m1")


def test_memory_delete_rejects_empty_id():
    assert memory_delete(memory_id="")["code"] == "validation_error"


@patch("src.api.mcp.mcp_server.get_memory_client")
def test_memory_wipe_returns_success(mock_get_client):
    mock_service = MagicMock()
    mock_get_client.return_value = mock_service

    result = memory_wipe(user_id="u1")

    assert result["status"] == "success"
    assert "u1" in result["message"]
    mock_service.wipe_user.assert_called_once_with(user_id="u1")


@patch("src.api.mcp.mcp_server.get_memory_client")
def test_memory_wipe_uses_default_user_id(mock_get_client):
    mock_service = MagicMock()
    mock_get_client.return_value = mock_service

    memory_wipe()

    mock_service.wipe_user.assert_called_once_with(user_id="default_user")


@patch("src.api.mcp.mcp_server.get_memory_client")
def test_memory_wipe_unknown_provider_returns_validation_error(mock_get_client):
    result = memory_wipe(provider="not-real")
    assert result["code"] == "validation_error"
    mock_get_client.assert_not_called()

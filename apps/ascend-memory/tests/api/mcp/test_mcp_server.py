from unittest.mock import MagicMock, patch

import pytest

from src.api.mcp.mcp_server import (
    memory_delete,
    memory_insert,
    memory_search,
    memory_wipe,
)


@patch("src.api.mcp.mcp_server.get_memory_client")
def test_memory_insert_returns_success_envelope(mock_get_client: MagicMock) -> None:
    # given
    mock_service = MagicMock()
    mock_service.add.return_value = [{"id": "m1"}]
    mock_get_client.return_value = mock_service

    # when
    result = memory_insert(user_id="u1", text="hello")

    # then
    assert result == {"status": "success", "results": [{"id": "m1"}]}
    mock_service.add.assert_called_once_with(user_id="u1", text="hello", metadata=None)


@patch("src.api.mcp.mcp_server.get_memory_client")
def test_memory_insert_uses_default_user_id_when_omitted(mock_get_client: MagicMock) -> None:
    # given
    mock_service = MagicMock()
    mock_service.add.return_value = []
    mock_get_client.return_value = mock_service

    # when
    memory_insert(text="hello")

    # then
    assert mock_service.add.call_args.kwargs["user_id"] == "default_user"


def test_memory_insert_rejects_empty_text() -> None:
    # given
    bad_text = ""
    # when
    with pytest.raises(Exception, match=r"^validation: ") as exc_info:
        memory_insert(text=bad_text)
    # then
    assert "empty" in str(exc_info.value)


def test_memory_insert_rejects_text_above_cap() -> None:
    # given
    from src.config.config import settings

    oversized = "x" * (settings.MAX_MEMORY_TEXT_LENGTH + 1)
    # when
    with pytest.raises(Exception, match=r"^validation: ") as exc_info:
        memory_insert(text=oversized)
    # then
    assert "maximum length" in str(exc_info.value)


@patch("src.api.mcp.mcp_server.get_memory_client")
def test_memory_insert_maps_unexpected_failure_to_internal_error(mock_get_client: MagicMock) -> None:
    # given
    mock_get_client.side_effect = RuntimeError("upstream burst into flames")
    # when
    with pytest.raises(Exception, match=r"^internal: ") as exc_info:
        memory_insert(text="hi")
    # then
    assert "An unexpected error occurred" in str(exc_info.value)


@patch("src.api.mcp.mcp_server.get_memory_client")
def test_memory_search_returns_success_envelope(mock_get_client: MagicMock) -> None:
    # given
    mock_service = MagicMock()
    mock_service.search.return_value = [{"id": "m1", "score": 0.8}]
    mock_get_client.return_value = mock_service

    # when
    result = memory_search(query="find me")

    # then
    assert result == {"status": "success", "results": [{"id": "m1", "score": 0.8}]}
    mock_service.search.assert_called_once_with(query="find me", user_id="default_user", limit=5)


def test_memory_search_rejects_empty_query() -> None:
    # given
    bad_query = "   "
    # when
    with pytest.raises(Exception, match=r"^validation: ") as exc_info:
        memory_search(query=bad_query)
    # then
    assert "empty" in str(exc_info.value)


def test_memory_search_rejects_query_above_cap() -> None:
    # given
    from src.config.config import settings

    oversized = "x" * (settings.MAX_QUERY_LENGTH + 1)
    # when
    with pytest.raises(Exception, match=r"^validation: ") as exc_info:
        memory_search(query=oversized)
    # then
    assert "maximum length" in str(exc_info.value)


def test_memory_search_rejects_limit_out_of_range() -> None:
    # given
    from src.config.config import settings

    # when / then
    with pytest.raises(Exception, match=r"^validation: "):
        memory_search(query="q", limit=0)
    with pytest.raises(Exception, match=r"^validation: ") as exc_info:
        memory_search(query="q", limit=settings.MAX_SEARCH_LIMIT + 1)
    assert "limit must be between" in str(exc_info.value)


@patch("src.api.mcp.mcp_server.get_memory_client")
def test_memory_delete_returns_success(mock_get_client: MagicMock) -> None:
    # given
    mock_service = MagicMock()
    mock_get_client.return_value = mock_service

    # when
    result = memory_delete(memory_id="m1")

    # then
    assert result["status"] == "success"
    assert "m1" in result["message"]
    mock_service.delete.assert_called_once_with(memory_id="m1")


def test_memory_delete_rejects_empty_id() -> None:
    # given
    bad_id = ""
    # when
    with pytest.raises(Exception, match=r"^validation: ") as exc_info:
        memory_delete(memory_id=bad_id)
    # then
    assert "empty" in str(exc_info.value)


@patch("src.api.mcp.mcp_server.wipe_user_all_collections")
def test_memory_wipe_without_provider_wipes_all_collections(mock_wipe_all: MagicMock) -> None:
    # when
    result = memory_wipe(user_id="u1")

    # then
    assert result["status"] == "success"
    assert "u1" in result["message"]
    mock_wipe_all.assert_called_once_with(user_id="u1")


@patch("src.api.mcp.mcp_server.wipe_user_all_collections")
def test_memory_wipe_uses_default_user_id(mock_wipe_all: MagicMock) -> None:
    # when
    memory_wipe()

    # then
    mock_wipe_all.assert_called_once_with(user_id="default_user")


@patch("src.api.mcp.mcp_server.get_memory_client")
def test_memory_wipe_with_explicit_provider_wipes_that_provider_only(mock_get_client: MagicMock) -> None:
    # given
    mock_service = MagicMock()
    mock_get_client.return_value = mock_service

    # when
    result = memory_wipe(user_id="u1", provider="openai")

    # then
    assert result["status"] == "success"
    mock_service.wipe_user.assert_called_once_with(user_id="u1")


@patch("src.api.mcp.mcp_server.get_memory_client")
def test_memory_wipe_unknown_provider_raises_validation_error(mock_get_client: MagicMock) -> None:
    # given
    bad_provider = "not-real"
    # when
    with pytest.raises(Exception, match=r"^validation: ") as exc_info:
        memory_wipe(provider=bad_provider)
    # then
    assert str(exc_info.value).startswith("validation: ")
    mock_get_client.assert_not_called()

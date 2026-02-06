import pytest
from unittest.mock import MagicMock, patch
from src.service.memory_client import AscendMemoryClient, get_memory_client
import src.service.memory_client as client_module


@pytest.fixture(autouse=True)
def reset_singleton():
    """Reset the singleton instance before and after each test."""
    client_module._client_instance = None
    yield
    client_module._client_instance = None


def test_get_memory_client_singleton():
    # given
    # when
    client1 = get_memory_client()
    client2 = get_memory_client()

    # then
    assert client1 is client2
    assert isinstance(client1, AscendMemoryClient)


def test_add_memory_success(mock_memory_service):
    # given
    client = get_memory_client()
    mock_memory_service.add.return_value = {"results": [{"id": "mem_1"}]}
    user_id = "user_1"
    text = "remember this"

    # when
    result = client.add(user_id=user_id, text=text)

    # then
    assert result == [{"id": "mem_1"}]
    mock_memory_service.add.assert_called_once()
    # Check call kwargs
    call_kwargs = mock_memory_service.add.call_args.kwargs
    assert call_kwargs["user_id"] == user_id
    assert call_kwargs["messages"] == [{"role": "user", "content": text}]


def test_add_memory_missing_args():
    # given
    client = get_memory_client()

    # when / then
    with pytest.raises(ValueError):
        client.add(user_id="u1")  # No text or messages


def test_search_memory_success(mock_memory_service):
    # given
    client = get_memory_client()
    mock_memory_service.search.return_value = {"results": [{"id": "mem_1", "score": 0.9}]}

    # when
    results = client.search(user_id="u1", query="find me")

    # then
    assert len(results) == 1
    assert results[0]["id"] == "mem_1"
    mock_memory_service.search.assert_called_once_with(query="find me", user_id="u1", limit=5)


def test_delete_memory_success(mock_memory_service):
    # given
    client = get_memory_client()

    # when
    client.delete(memory_id="mem_1")

    # then
    mock_memory_service.delete.assert_called_once_with(memory_id="mem_1")


def test_wipe_user_success(mock_memory_service):
    # given
    client = get_memory_client()
    # Mock listing memories
    mock_memory_service.get_all.return_value = {
        "results": [{"id": "id_1"}, {"id": "id_2"}]
    }

    # when
    client.wipe_user(user_id="u1")

    # then
    mock_memory_service.get_all.assert_called_once_with(user_id="u1")
    # Verify calls to delete for each ID
    assert mock_memory_service.delete.call_count == 2
    mock_memory_service.delete.assert_any_call(memory_id="id_1")
    mock_memory_service.delete.assert_any_call(memory_id="id_2")


def test_add_memory_error(mock_memory_service):
    # given
    client = get_memory_client()
    mock_memory_service.add.side_effect = Exception("DB Error")

    # when / then
    with pytest.raises(Exception):
        client.add(user_id="u1", text="test")


def test_search_memory_error(mock_memory_service):
    # given
    client = get_memory_client()
    mock_memory_service.search.side_effect = Exception("Search Error")

    # when
    results = client.search(user_id="u1", query="test")

    # then
    assert results == []  # Should match the safe default


def test_delete_memory_error(mock_memory_service):
    # given
    client = get_memory_client()
    mock_memory_service.delete.side_effect = Exception("Del Error")

    # when / then
    with pytest.raises(Exception):
        client.delete(memory_id="mem_1")


def test_wipe_user_error_listing(mock_memory_service):
    # given
    client = get_memory_client()
    mock_memory_service.get_all.side_effect = Exception("List Error")

    # when / then
    with pytest.raises(Exception):
        client.wipe_user(user_id="u1")


def test_wipe_user_error_deleting_one(mock_memory_service):
    # given
    client = get_memory_client()
    mock_memory_service.get_all.return_value = {"results": [{"id": "1"}]}
    mock_memory_service.delete.side_effect = Exception("Del 1 Error")

    # when
    # Should catch exception inside loop and log it, not raise
    client.wipe_user(user_id="u1")

    # then
    mock_memory_service.delete.assert_called_once()

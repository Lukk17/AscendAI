from collections.abc import Iterator
from types import TracebackType
from typing import Any, cast
from unittest.mock import MagicMock

import pytest

import src.service.memory_client as client_module
from src.service.memory_client import (
    AscendMemoryClient,
    _hash_user_id,
    get_default_memory_client,
    get_memory_client,
    resolve_provider,
)


@pytest.fixture(autouse=True)
def reset_singleton() -> Iterator[None]:
    client_module._client_instances.clear()
    yield
    client_module._client_instances.clear()


def test_resolve_provider_falls_back_to_default_when_none() -> None:
    assert resolve_provider(None) == "lmstudio"


def test_resolve_provider_falls_back_to_default_when_blank() -> None:
    assert resolve_provider("   ") == "lmstudio"


def test_resolve_provider_normalises_case() -> None:
    assert resolve_provider("LMSTUDIO") == "lmstudio"


def test_resolve_provider_rejects_unknown_provider() -> None:
    with pytest.raises(ValueError, match="Unknown provider"):
        resolve_provider("not-a-provider")


def test_get_memory_client_returns_cached_instance_on_second_call(
    mock_memory_service: Any,
) -> None:
    del mock_memory_service  # patches mem0.Memory.from_config via conftest
    first = get_memory_client("lmstudio")
    second = get_memory_client("lmstudio")
    assert first is second


def test_get_memory_client_re_checks_cache_after_acquiring_lock(
    monkeypatch: pytest.MonkeyPatch, mock_memory_service: Any
) -> None:
    """Simulates the lost-race path: another thread populates the cache
    between the outer get() and the lock acquisition. The thread inside the
    lock must return the cached value instead of constructing a duplicate."""

    del mock_memory_service
    # cast: MagicMock(spec=AscendMemoryClient) satisfies the dict's value type
    # at runtime; the cast tells static analysers we accept the substitution.
    sentinel = cast("AscendMemoryClient", MagicMock(spec=AscendMemoryClient))

    real_lock = client_module._client_lock

    class _SneakyLock:
        def __enter__(self) -> bool:
            client_module._client_instances["lmstudio"] = sentinel
            return real_lock.__enter__()

        def __exit__(
            self,
            exc_type: type[BaseException] | None,
            exc: BaseException | None,
            tb: TracebackType | None,
        ) -> None:
            real_lock.__exit__(exc_type, exc, tb)

    monkeypatch.setattr(client_module, "_client_lock", _SneakyLock())

    result = client_module.get_memory_client("lmstudio")
    assert result is sentinel


def test_get_memory_client_returns_different_instances_per_provider(
    mock_memory_service: Any,
) -> None:
    del mock_memory_service
    a = get_memory_client("lmstudio")
    b = get_memory_client("openai")
    assert a is not b


def test_get_default_memory_client_returns_default_provider_instance(
    mock_memory_service: Any,
) -> None:
    del mock_memory_service
    client = get_default_memory_client()
    assert isinstance(client, AscendMemoryClient)
    assert client.provider == "lmstudio"


def test_init_raises_when_api_key_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.config import config as cfg

    monkeypatch.setattr(cfg.settings, "LMSTUDIO_API_KEY", "", raising=False)
    with pytest.raises(ValueError, match="LMSTUDIO_API_KEY"):
        AscendMemoryClient("lmstudio")


def test_init_routes_lmstudio_through_lmstudio_llm_backend(
    monkeypatch: pytest.MonkeyPatch, mock_memory_service: Any
) -> None:
    captured: dict[str, Any] = {}

    def fake_from_config(config: dict[str, Any]) -> Any:
        captured["config"] = config
        return mock_memory_service

    monkeypatch.setattr(client_module.Memory, "from_config", fake_from_config)

    AscendMemoryClient("lmstudio")
    assert captured["config"]["llm"]["provider"] == "lmstudio"
    assert "lmstudio_base_url" in captured["config"]["llm"]["config"]


def test_init_routes_openai_through_openai_llm_backend(
    monkeypatch: pytest.MonkeyPatch, mock_memory_service: Any
) -> None:
    captured: dict[str, Any] = {}

    def fake_from_config(config: dict[str, Any]) -> Any:
        captured["config"] = config
        return mock_memory_service

    monkeypatch.setattr(client_module.Memory, "from_config", fake_from_config)
    from src.config import config as cfg
    monkeypatch.setattr(cfg.settings, "OPENAI_API_KEY", "sk-test", raising=False)

    AscendMemoryClient("openai")
    assert captured["config"]["llm"]["provider"] == "openai"
    assert "openai_base_url" in captured["config"]["llm"]["config"]


def test_add_with_text_wraps_into_user_message(mock_memory_service: Any) -> None:
    mock_memory_service.add.return_value = {"results": [{"id": "m1"}]}
    client = get_memory_client("lmstudio")

    result = client.add(user_id="u1", text="hello")

    assert result == [{"id": "m1"}]
    call_kwargs = mock_memory_service.add.call_args.kwargs
    assert call_kwargs["messages"] == [{"role": "user", "content": "hello"}]
    assert call_kwargs["user_id"] == "u1"


def test_add_with_messages_passes_through(mock_memory_service: Any) -> None:
    mock_memory_service.add.return_value = {"results": [{"id": "m2"}]}
    client = get_memory_client("lmstudio")
    messages = [{"role": "user", "content": "x"}, {"role": "assistant", "content": "y"}]

    result = client.add(user_id="u1", messages=messages)

    assert result == [{"id": "m2"}]
    assert mock_memory_service.add.call_args.kwargs["messages"] == messages


def test_add_without_messages_or_text_raises(mock_memory_service: Any) -> None:
    del mock_memory_service
    client = get_memory_client("lmstudio")
    with pytest.raises(ValueError, match=r"messages.*or.*text"):
        client.add(user_id="u1")


def test_add_re_raises_on_upstream_failure(mock_memory_service: Any) -> None:
    mock_memory_service.add.side_effect = RuntimeError("boom")
    client = get_memory_client("lmstudio")
    with pytest.raises(RuntimeError, match="boom"):
        client.add(user_id="u1", text="x")


def test_search_uses_mem0_2x_signature(mock_memory_service: Any) -> None:
    mock_memory_service.search.return_value = {"results": [{"id": "m1", "score": 0.9}]}
    client = get_memory_client("lmstudio")

    result = client.search(query="q", user_id="u1", limit=7)

    assert result == [{"id": "m1", "score": 0.9}]
    mock_memory_service.search.assert_called_once_with(
        query="q",
        top_k=7,
        filters={"user_id": "u1"},
    )


def test_search_returns_empty_list_when_mem0_returns_falsy(mock_memory_service: Any) -> None:
    mock_memory_service.search.return_value = None
    client = get_memory_client("lmstudio")
    assert client.search(query="q", user_id="u1") == []


def test_search_re_raises_on_upstream_failure(mock_memory_service: Any) -> None:
    mock_memory_service.search.side_effect = RuntimeError("qdrant down")
    client = get_memory_client("lmstudio")
    with pytest.raises(RuntimeError, match="qdrant down"):
        client.search(query="q", user_id="u1")


def test_delete_calls_through(mock_memory_service: Any) -> None:
    client = get_memory_client("lmstudio")
    client.delete(memory_id="m1")
    mock_memory_service.delete.assert_called_once_with(memory_id="m1")


def test_delete_re_raises_on_upstream_failure(mock_memory_service: Any) -> None:
    mock_memory_service.delete.side_effect = RuntimeError("nope")
    client = get_memory_client("lmstudio")
    with pytest.raises(RuntimeError):
        client.delete(memory_id="m1")


def test_wipe_user_calls_delete_all_once(mock_memory_service: Any) -> None:
    client = get_memory_client("lmstudio")
    client.wipe_user(user_id="u1")
    mock_memory_service.delete_all.assert_called_once_with(user_id="u1")


def test_wipe_user_re_raises_on_upstream_failure(mock_memory_service: Any) -> None:
    mock_memory_service.delete_all.side_effect = RuntimeError("qdrant 500")
    client = get_memory_client("lmstudio")
    with pytest.raises(RuntimeError):
        client.wipe_user(user_id="u1")


def test_hash_user_id_is_stable_and_short() -> None:
    a = _hash_user_id("alice@example.com")
    b = _hash_user_id("alice@example.com")
    c = _hash_user_id("bob@example.com")
    assert a == b
    assert a != c
    assert len(a) == 12

from types import TracebackType
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from src.api import readiness as readiness_module
from src.main import app


class _FakeResponse:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code


class _FakeAsyncClient:
    def __init__(
        self,
        response: _FakeResponse | None = None,
        raise_exc: Exception | None = None,
    ) -> None:
        self._response = response
        self._raise_exc = raise_exc

    async def __aenter__(self) -> "_FakeAsyncClient":
        return self

    async def __aexit__(
        self,
        _exc_type: type[BaseException] | None,
        _exc: BaseException | None,
        _tb: TracebackType | None,
    ) -> None:
        # Fake async context manager — nothing to release.
        return

    async def get(self, *_args: object, **_kwargs: object) -> _FakeResponse:
        if self._raise_exc:
            raise self._raise_exc
        assert self._response is not None
        return self._response


@pytest.mark.asyncio
async def test_probe_qdrant_returns_ok_on_200(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        readiness_module.httpx,
        "AsyncClient",
        lambda **_kw: _FakeAsyncClient(response=_FakeResponse(200)),
    )
    assert await readiness_module._probe_qdrant() == {"status": "ok"}


@pytest.mark.asyncio
async def test_probe_qdrant_returns_error_on_non_200(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        readiness_module.httpx,
        "AsyncClient",
        lambda **_kw: _FakeAsyncClient(response=_FakeResponse(500)),
    )
    assert await readiness_module._probe_qdrant() == {"status": "error"}


@pytest.mark.asyncio
async def test_probe_qdrant_returns_error_on_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        readiness_module.httpx,
        "AsyncClient",
        lambda **_kw: _FakeAsyncClient(raise_exc=RuntimeError("timeout")),
    )
    assert await readiness_module._probe_qdrant() == {"status": "error"}


@pytest.mark.asyncio
async def test_probe_embedding_api_returns_ok_when_under_500(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        readiness_module.httpx,
        "AsyncClient",
        lambda **_kw: _FakeAsyncClient(response=_FakeResponse(200)),
    )
    assert await readiness_module._probe_embedding_api() == {"status": "ok"}


@pytest.mark.asyncio
async def test_probe_embedding_api_returns_error_on_5xx(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        readiness_module.httpx,
        "AsyncClient",
        lambda **_kw: _FakeAsyncClient(response=_FakeResponse(503)),
    )
    assert await readiness_module._probe_embedding_api() == {"status": "error"}


@pytest.mark.asyncio
async def test_probe_embedding_api_returns_error_when_unknown_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(readiness_module.settings, "MEM0_DEFAULT_PROVIDER", "fake")
    assert await readiness_module._probe_embedding_api() == {"status": "error"}


@pytest.mark.asyncio
async def test_probe_embedding_api_returns_error_when_base_url_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(readiness_module.settings, "LMSTUDIO_BASE_URL", "")
    assert await readiness_module._probe_embedding_api() == {"status": "error"}


@pytest.mark.asyncio
async def test_probe_embedding_api_returns_error_on_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        readiness_module.httpx,
        "AsyncClient",
        lambda **_kw: _FakeAsyncClient(raise_exc=RuntimeError("boom")),
    )
    assert await readiness_module._probe_embedding_api() == {"status": "error"}


def test_probe_mem0_client_returns_ok_when_construction_succeeds() -> None:
    with patch.object(readiness_module, "get_memory_client", return_value=MagicMock()):
        assert readiness_module._probe_mem0_client() == {"status": "ok"}


def test_probe_mem0_client_returns_error_when_construction_fails() -> None:
    with patch.object(
        readiness_module, "get_memory_client", side_effect=RuntimeError("no key")
    ):
        assert readiness_module._probe_mem0_client() == {"status": "error"}


@pytest.mark.asyncio
async def test_ready_endpoint_returns_200_when_all_checks_ok(override_dependencies: Any) -> None:
    del override_dependencies  # injected to ensure no real upstream calls; not asserted here
    with patch.object(
        readiness_module,
        "_probe_qdrant",
        new=AsyncMock(return_value={"status": "ok"}),
    ), patch.object(
        readiness_module,
        "_probe_embedding_api",
        new=AsyncMock(return_value={"status": "ok"}),
    ), patch.object(
        readiness_module,
        "_probe_mem0_client",
        return_value={"status": "ok"},
    ), patch("src.main.warmup_client", new_callable=AsyncMock):
        with TestClient(app) as test_client:
            response = test_client.get("/ready")
            assert response.status_code == 200
            assert response.json()["status"] == "ready"


@pytest.mark.asyncio
async def test_ready_endpoint_returns_503_on_degraded_dependency(override_dependencies: Any) -> None:
    del override_dependencies
    with patch.object(
        readiness_module,
        "_probe_qdrant",
        new=AsyncMock(return_value={"status": "error"}),
    ), patch.object(
        readiness_module,
        "_probe_embedding_api",
        new=AsyncMock(return_value={"status": "ok"}),
    ), patch.object(
        readiness_module,
        "_probe_mem0_client",
        return_value={"status": "ok"},
    ), patch("src.main.warmup_client", new_callable=AsyncMock):
        with TestClient(app) as test_client:
            response = test_client.get("/ready")
            assert response.status_code == 503
            assert response.json()["status"] == "degraded"

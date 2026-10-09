import http.server
import threading
import time
from types import TracebackType
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient

from src.api import readiness as readiness_module
from src.config.config import settings
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
        return

    async def get(self, *_args: object, **_kwargs: object) -> _FakeResponse:
        if self._raise_exc:
            raise self._raise_exc
        assert self._response is not None
        return self._response


@pytest.mark.asyncio
async def test_probe_qdrant_returns_ok_on_200(monkeypatch: pytest.MonkeyPatch) -> None:
    # given
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **_kw: _FakeAsyncClient(response=_FakeResponse(200)),
    )
    # when
    result = await readiness_module.probe_qdrant()
    # then
    assert result.status == "ok"


@pytest.mark.asyncio
async def test_probe_qdrant_returns_error_on_non_200(monkeypatch: pytest.MonkeyPatch) -> None:
    # given
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **_kw: _FakeAsyncClient(response=_FakeResponse(500)),
    )
    # when
    result = await readiness_module.probe_qdrant()
    # then
    assert result.status == "error"


@pytest.mark.asyncio
async def test_probe_qdrant_returns_error_on_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    # given
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **_kw: _FakeAsyncClient(raise_exc=RuntimeError("timeout")),
    )
    # when
    result = await readiness_module.probe_qdrant()
    # then
    assert result.status == "error"


@pytest.mark.asyncio
async def test_probe_embedding_api_returns_ok_when_under_500(monkeypatch: pytest.MonkeyPatch) -> None:
    # given
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **_kw: _FakeAsyncClient(response=_FakeResponse(200)),
    )
    # when
    result = await readiness_module.probe_embedding_api()
    # then
    assert result.status == "ok"


@pytest.mark.asyncio
async def test_probe_embedding_api_returns_error_on_5xx(monkeypatch: pytest.MonkeyPatch) -> None:
    # given
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **_kw: _FakeAsyncClient(response=_FakeResponse(503)),
    )
    # when
    result = await readiness_module.probe_embedding_api()
    # then
    assert result.status == "error"


@pytest.mark.asyncio
async def test_probe_embedding_api_returns_error_when_unknown_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # given
    monkeypatch.setattr(settings, "MEM0_DEFAULT_PROVIDER", "fake")
    # when
    result = await readiness_module.probe_embedding_api()
    # then
    assert result.status == "error"


@pytest.mark.asyncio
async def test_probe_embedding_api_returns_error_when_base_url_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # given
    monkeypatch.setattr(settings, "LMSTUDIO_BASE_URL", "")
    # when
    result = await readiness_module.probe_embedding_api()
    # then
    assert result.status == "error"


@pytest.mark.asyncio
async def test_probe_embedding_api_returns_error_on_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # given
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **_kw: _FakeAsyncClient(raise_exc=RuntimeError("boom")),
    )
    # when
    result = await readiness_module.probe_embedding_api()
    # then
    assert result.status == "error"


def test_probe_mem0_client_returns_ok_when_construction_succeeds() -> None:
    # given
    with patch.object(readiness_module, "get_memory_client", return_value=MagicMock()):
        # when
        result = readiness_module.probe_mem0_client()
        # then
        assert result.status == "ok"


def test_probe_mem0_client_returns_error_when_construction_fails() -> None:
    # given
    with patch.object(readiness_module, "get_memory_client", side_effect=RuntimeError("no key")):
        # when
        result = readiness_module.probe_mem0_client()
        # then
        assert result.status == "error"


@pytest.mark.asyncio
async def test_probe_qdrant_uses_configured_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    # given
    monkeypatch.setattr(settings, "READINESS_PROBE_TIMEOUT_SECONDS", 0.1)
    seen: dict[str, object] = {}

    def fake_client(**kwargs: object) -> _FakeAsyncClient:
        seen["timeout"] = kwargs.get("timeout")
        return _FakeAsyncClient(response=_FakeResponse(200))

    monkeypatch.setattr(httpx, "AsyncClient", fake_client)
    # when
    result = await readiness_module.probe_qdrant()
    # then
    assert result.status == "ok"
    assert seen["timeout"] == 0.1


@pytest.mark.asyncio
async def test_probe_embedding_api_uses_configured_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # given
    monkeypatch.setattr(settings, "READINESS_PROBE_TIMEOUT_SECONDS", 0.1)
    seen: dict[str, object] = {}

    def fake_client(**kwargs: object) -> _FakeAsyncClient:
        seen["timeout"] = kwargs.get("timeout")
        return _FakeAsyncClient(response=_FakeResponse(200))

    monkeypatch.setattr(httpx, "AsyncClient", fake_client)
    # when
    result = await readiness_module.probe_embedding_api()
    # then
    assert result.status == "ok"
    assert seen["timeout"] == 0.1


class _SlowHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        # Never answers in time: the probe's timeout fires first and the
        # handler returns without writing, so no aborted socket is left open.
        time.sleep(0.3)

    def log_message(self, *_args: object) -> None:
        return None


@pytest.mark.asyncio
async def test_slow_probe_reports_error_and_ready_answers_503(
    monkeypatch: pytest.MonkeyPatch, override_dependencies: Any
) -> None:
    # given
    del override_dependencies
    from ascend_python_common.readiness import ProbeResult

    server = http.server.HTTPServer(("127.0.0.1", 0), _SlowHandler)
    port = int(server.server_address[1])
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setattr(settings, "READINESS_PROBE_TIMEOUT_SECONDS", 0.1)
    monkeypatch.setattr(settings, "QDRANT_HOST", "127.0.0.1")
    monkeypatch.setattr(settings, "QDRANT_PORT", port)
    try:
        # when
        result = await readiness_module.probe_qdrant()
        # then
        assert result.status == "error"
        with (
            patch.object(
                readiness_module,
                "probe_embedding_api",
                new=AsyncMock(return_value=ProbeResult(status="ok")),
            ),
            patch.object(
                readiness_module,
                "probe_mem0_client",
                return_value=ProbeResult(status="ok"),
            ),
        ):
            with TestClient(app) as test_client:
                response = test_client.get("/ready")
        assert response.status_code == 503
        assert response.json()["status"] == "not-ready"
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


@pytest.mark.asyncio
async def test_ready_endpoint_returns_200_when_all_checks_ok(override_dependencies: Any) -> None:
    # given
    del override_dependencies
    from ascend_python_common.readiness import ProbeResult

    with (
        patch.object(
            readiness_module,
            "probe_qdrant",
            new=AsyncMock(return_value=ProbeResult(status="ok")),
        ),
        patch.object(
            readiness_module,
            "probe_embedding_api",
            new=AsyncMock(return_value=ProbeResult(status="ok")),
        ),
        patch.object(
            readiness_module,
            "probe_mem0_client",
            return_value=ProbeResult(status="ok"),
        ),
    ):
        with TestClient(app) as test_client:
            # when
            response = test_client.get("/ready")
            # then
            assert response.status_code == 200
            assert response.json()["status"] == "ready"


@pytest.mark.asyncio
async def test_ready_endpoint_returns_503_on_degraded_dependency(override_dependencies: Any) -> None:
    # given
    del override_dependencies
    from ascend_python_common.readiness import ProbeResult

    with (
        patch.object(
            readiness_module,
            "probe_qdrant",
            new=AsyncMock(return_value=ProbeResult(status="error")),
        ),
        patch.object(
            readiness_module,
            "probe_embedding_api",
            new=AsyncMock(return_value=ProbeResult(status="ok")),
        ),
        patch.object(
            readiness_module,
            "probe_mem0_client",
            return_value=ProbeResult(status="ok"),
        ),
    ):
        with TestClient(app) as test_client:
            # when
            response = test_client.get("/ready")
            # then
            assert response.status_code == 503
            assert response.json()["status"] == "not-ready"

import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient


def _otel_sys_modules() -> dict[str, MagicMock]:
    m = MagicMock()
    return {
        "opentelemetry": m,
        "opentelemetry.sdk": m,
        "opentelemetry.sdk.trace": m,
        "opentelemetry.sdk.trace.export": m,
        "opentelemetry.sdk.resources": m,
        "opentelemetry.exporter": m,
        "opentelemetry.exporter.otlp": m,
        "opentelemetry.exporter.otlp.proto": m,
        "opentelemetry.exporter.otlp.proto.grpc": m,
        "opentelemetry.exporter.otlp.proto.grpc.trace_exporter": m,
        "opentelemetry.instrumentation": m,
        "opentelemetry.instrumentation.fastapi": m,
    }


def test_configure_otel_noop_when_env_var_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.main import _configure_otel

    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    _configure_otel()


def test_configure_otel_activates_when_endpoint_set(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.main import _configure_otel

    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://otel:4317")
    with patch.dict(sys.modules, _otel_sys_modules()):
        _configure_otel()


@pytest.mark.asyncio
async def test_health_check(client: AsyncClient):
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_metrics_endpoint_serves_prometheus(client: AsyncClient):
    resp = await client.get("/metrics")
    assert resp.status_code == 200
    assert "text/plain" in resp.headers["content-type"]
    body = resp.text
    assert "process_" in body or "python_" in body
    assert "ascendwebsearch_search_results_total" in body


@pytest.mark.asyncio
async def test_request_id_middleware_echoes_inbound_header(client: AsyncClient):
    resp = await client.get("/health", headers={"X-Request-ID": "fixed-id-123"})
    assert resp.headers.get("X-Request-ID") == "fixed-id-123"


@pytest.mark.asyncio
async def test_request_id_middleware_generates_when_missing(client: AsyncClient):
    resp = await client.get("/health")
    assert resp.headers.get("X-Request-ID")
    assert resp.headers["X-Request-ID"] != "fixed-id-123"


@pytest.mark.asyncio
async def test_search_endpoint(client: AsyncClient):
    from src.api.rest.rest_endpoints import search_client

    mock_results = [{"title": "Res", "url": "u", "content": "c"}]
    with patch.object(search_client, "search", new_callable=AsyncMock) as mock_search:
        mock_search.return_value = mock_results
        resp = await client.get("/api/v1/web/search", params={"query": "test", "limit": 1})
        assert resp.status_code == 200
        assert resp.json()[0]["title"] == "Res"


@pytest.mark.asyncio
async def test_read_endpoint(client: AsyncClient):
    from src.api.rest.rest_endpoints import web_reader

    mock_res = {"status": "success", "content": "Read Content", "mode": "1-beautifulsoup"}
    with (
        patch.object(web_reader, "read", new_callable=AsyncMock) as mock_read,
        patch("src.api.rest.rest_endpoints.is_safe_external_url", return_value=True),
    ):
        mock_read.return_value = mock_res
        resp = await client.post("/api/v2/web/read", json={"url": "http://example.com"})
        assert resp.status_code == 200
        assert resp.json()["content"] == "Read Content"

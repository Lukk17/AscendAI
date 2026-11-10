import logging
from logging.handlers import BufferingHandler
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health_check(client: AsyncClient) -> None:
    # when
    resp = await client.get("/health")

    # then
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_metrics_endpoint_serves_prometheus(client: AsyncClient) -> None:
    # given
    from src.observability import metrics as service_metrics

    service_metrics.SEARCH_RESULTS_RETURNED.labels(engine="searxng", outcome="ok").observe(2)
    service_metrics.STRATEGY_ATTEMPTS_TOTAL.labels(
        strategy="1-beautifulsoup", outcome="success", domain="example.com"
    ).inc()

    # when
    resp = await client.get("/metrics")

    # then
    assert resp.status_code == 200
    assert "text/plain" in resp.headers["content-type"]
    body = resp.text
    assert "process_" in body or "python_" in body
    assert "search_results_returned" in body
    assert "strategy_attempts_total" in body
    assert "ascendwebhunter_search_results_total" not in body


@pytest.mark.asyncio
async def test_request_id_middleware_echoes_inbound_header(client: AsyncClient) -> None:
    # when
    resp = await client.get("/health", headers={"X-Request-ID": "fixed-id-123"})

    # then
    assert resp.headers.get("X-Request-ID") == "fixed-id-123"


@pytest.mark.asyncio
async def test_request_id_middleware_generates_when_missing(client: AsyncClient) -> None:
    # when
    resp = await client.get("/health")

    # then
    assert resp.headers.get("X-Request-ID")
    assert resp.headers["X-Request-ID"] != "fixed-id-123"


@pytest.mark.asyncio
async def test_search_endpoint(client: AsyncClient) -> None:
    # given
    from src.api.rest.rest_endpoints import search_client

    mock_results = [{"title": "Res", "url": "u", "content": "c"}]
    with patch.object(search_client, "search", new_callable=AsyncMock) as mock_search:
        mock_search.return_value = mock_results

        # when
        resp = await client.get("/api/v1/web/search", params={"query": "test", "limit": 1})

        # then
        assert resp.status_code == 200
        assert resp.json()[0]["title"] == "Res"


@pytest.mark.asyncio
async def test_read_endpoint(client: AsyncClient) -> None:
    # given
    from src.api.rest.rest_endpoints import web_reader

    mock_res = {"status": "success", "content": "Read Content", "mode": "1-beautifulsoup"}
    with (
        patch.object(web_reader, "read", new_callable=AsyncMock) as mock_read,
        patch("src.api.rest.rest_endpoints.check_fetch_uri", return_value=True),
    ):
        mock_read.return_value = mock_res

        # when
        resp = await client.post("/api/v2/web/read", json={"url": "http://example.com"})

        # then
        assert resp.status_code == 200
        assert resp.json()["content"] == "Read Content"


@pytest.mark.parametrize(
    ("message", "args", "kept"),
    [
        ("discarding data: %s", (None,), False),
        ("recall retry failed: %s %s", ("error", "address"), True),
        ("justext candidate failed: %s %s", ("error", "address"), True),
        ("blacklisted URL: %s", ("address",), True),
    ],
)
def test_only_the_trafilatura_no_text_warning_is_dropped_after_the_app_is_built(
    message: str, args: tuple[object, ...], kept: bool
) -> None:
    # given
    from src import main

    main.create_app()
    quieted = logging.getLogger("trafilatura.core")
    captured = BufferingHandler(capacity=2)
    quieted.addHandler(captured)

    # when
    try:
        quieted.warning(message, *args)
    finally:
        quieted.removeHandler(captured)

    # then
    assert [record.msg for record in captured.buffer] == ([message] if kept else [])

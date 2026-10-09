import re
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from ascend_python_common.readiness import ProbeResult
from httpx import AsyncClient

from src.api.exceptions import HumanInterventionRequiredException, NoVNCFlowBusyException
from src.api.mcp.mcp_server import web_read, web_search
from src.session.session_manager import SessionManager


@pytest.mark.asyncio
async def test_request_validation_failure_answers_400_with_sorted_errors(
    client: AsyncClient,
) -> None:
    # given
    payload: dict[str, Any] = {}
    # when
    response = await client.post("/api/v2/web/read", json=payload)
    # then
    assert response.status_code == 400
    body = response.json()
    assert body["code"] == "validation"
    assert isinstance(body["errors"], list)
    fields = [entry["field"] for entry in body["errors"]]
    assert fields == sorted(fields)
    assert all("message" in entry for entry in body["errors"])


@pytest.mark.asyncio
async def test_unknown_path_answers_problem_404_with_trace_id(client: AsyncClient) -> None:
    # given
    path = "/does-not-exist"
    # when
    response = await client.get(path)
    # then
    assert response.status_code == 404
    assert "application/problem+json" in response.headers["content-type"]
    body = response.json()
    assert body["code"] == "not_found"
    assert re.fullmatch(r"[0-9a-f]{32}", body["traceId"]) is not None


@pytest.mark.asyncio
async def test_wrong_method_answers_problem_405_with_allow(client: AsyncClient) -> None:
    # given
    path = "/health"
    # when
    response = await client.delete(path)
    # then
    assert response.status_code == 405
    body = response.json()
    assert body["code"] == "method_not_allowed"
    assert "allow" in {key.lower() for key in response.headers}


@pytest.mark.asyncio
async def test_unexpected_failure_body_carries_code_and_trace_id_without_leak(
    client: AsyncClient,
) -> None:
    # given
    sentinel = "UPSTREAM_LEAK_MARKER_99"
    # when
    with (
        patch("src.api.rest.rest_endpoints.check_fetch_uri", return_value=True),
        patch(
            "src.api.rest.rest_endpoints.web_reader.read",
            new_callable=AsyncMock,
            side_effect=RuntimeError(f"upstream blew up with {sentinel}"),
        ),
    ):
        response = await client.post("/api/v2/web/read", json={"url": "http://unit.com/"})
    # then
    assert response.status_code == 500
    body = response.json()
    assert body["code"] == "internal"
    assert re.fullmatch(r"[0-9a-f]{32}", body["traceId"]) is not None
    assert sentinel not in response.text


@pytest.mark.asyncio
async def test_human_intervention_answers_428_problem_body(client: AsyncClient) -> None:
    # given
    vnc_url = "https://abc123.ngrok.io/vnc.html?autoconnect=true"
    exc = HumanInterventionRequiredException(vnc_url=vnc_url, intervention_type="captcha")
    # when
    with (
        patch("src.api.rest.rest_endpoints.check_fetch_uri", return_value=True),
        patch(
            "src.api.rest.rest_endpoints.web_reader.read",
            new_callable=AsyncMock,
            side_effect=exc,
        ),
    ):
        response = await client.post("/api/v2/web/read", json={"url": "http://example.com/"})
    # then
    assert response.status_code == 428
    assert "application/problem+json" in response.headers["content-type"]
    body = response.json()
    assert body["code"] == "human_intervention_required"
    assert body["type"] == "https://ascend.ai/errors/human-intervention-required"
    assert body["title"] == "Precondition Required"
    assert body["status"] == 428
    assert body["detail"] == exc.message
    assert body["instance"] == "/api/v2/web/read"
    assert re.fullmatch(r"[0-9a-f]{32}", body["traceId"]) is not None
    assert body["intervention_type"] == "captcha"
    assert body["vnc_url"] == vnc_url


@pytest.mark.asyncio
async def test_novnc_busy_answers_409_problem_body_with_retry_after(
    client: AsyncClient,
) -> None:
    # given
    exc = NoVNCFlowBusyException("http://in-flight.example", "default")
    # when
    with (
        patch("src.api.rest.rest_endpoints.check_fetch_uri", return_value=True),
        patch.object(SessionManager, "establish", new=AsyncMock(side_effect=exc)),
    ):
        response = await client.post(
            "/api/v2/web/session/establish",
            json={"url": "http://example.com/"},
        )
    # then
    assert response.status_code == 409
    assert "application/problem+json" in response.headers["content-type"]
    assert "retry-after" in {key.lower() for key in response.headers}
    body = response.json()
    assert body["code"] == "novnc_busy"
    assert body["type"] == "https://ascend.ai/errors/novnc-busy"
    assert body["status"] == 409
    assert body["holder_url"] == "http://in-flight.example"
    assert body["holder_profile"] == "default"
    assert re.fullmatch(r"[0-9a-f]{32}", body["traceId"]) is not None


@pytest.mark.asyncio
async def test_mcp_search_empty_query_raises_validation_tool_error() -> None:
    # given
    bad_query = ""
    # when
    with pytest.raises(Exception, match=r"^validation: ") as exc_info:
        await web_search(bad_query)
    # then
    assert str(exc_info.value).startswith("validation: ")


@pytest.mark.asyncio
async def test_mcp_search_too_long_query_raises_validation_tool_error() -> None:
    # given
    bad_query = "x" * 501
    # when
    with pytest.raises(Exception, match=r"^validation: ") as exc_info:
        await web_search(bad_query)
    # then
    assert str(exc_info.value).startswith("validation: ")


@pytest.mark.asyncio
async def test_mcp_read_bad_combination_raises_validation_tool_error() -> None:
    # given
    url = "http://example.com/"
    # when
    with patch("src.api.mcp.mcp_server.check_fetch_uri", return_value=True):
        with pytest.raises(Exception, match=r"^validation: ") as exc_info:
            await web_read(url, include_links=True, output_format="structured")
    # then
    assert str(exc_info.value).startswith("validation: ")


@pytest.mark.asyncio
async def test_ready_not_ready_body_on_503(client: AsyncClient) -> None:
    # given
    probes_down = (
        patch(
            "src.api.readiness.probe_searxng",
            new=AsyncMock(return_value=ProbeResult(status="error")),
        ),
        patch(
            "src.api.readiness.probe_flaresolverr",
            new=AsyncMock(return_value=ProbeResult(status="ok")),
        ),
        patch(
            "src.api.readiness.probe_redis",
            new=AsyncMock(return_value=ProbeResult(status="skipped")),
        ),
        patch(
            "src.api.readiness.probe_searxng_breaker",
            return_value=ProbeResult(status="ok"),
        ),
        patch(
            "src.api.readiness.probe_flaresolverr_breaker",
            return_value=ProbeResult(status="ok"),
        ),
    )
    # when
    with probes_down[0], probes_down[1], probes_down[2], probes_down[3], probes_down[4]:
        response = await client.get("/ready")
    # then
    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "not-ready"
    assert body["service"] == "ascend-web-hunter"
    assert isinstance(body["version"], str)
    assert len(body["version"]) > 0


@pytest.mark.asyncio
async def test_health_includes_service_and_version(client: AsyncClient) -> None:
    # given
    path = "/health"
    # when
    response = await client.get(path)
    # then
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "ascend-web-hunter"
    assert isinstance(body["version"], str)
    assert len(body["version"]) > 0

import re
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from ascend_python_common.readiness import ProbeResult
from httpx import AsyncClient

from src.api import readiness as readiness_module
from src.api.mcp.mcp_server import memory_delete, memory_insert, memory_search, memory_wipe


@pytest.mark.asyncio
async def test_refusal_problem_body_carries_code_and_trace_id(
    client: AsyncClient, override_dependencies: MagicMock
) -> None:
    # given
    mock_service = override_dependencies
    mock_service.add.side_effect = ValueError("nope")
    # when
    response = await client.post(
        "/api/v1/memory/insert",
        json={"user_id": "u1", "text": "x"},
    )
    # then
    assert response.status_code == 400
    body = response.json()
    assert body["code"] == "validation"
    assert re.fullmatch(r"[0-9a-f]{32}", body["traceId"]) is not None


@pytest.mark.asyncio
async def test_request_validation_failure_answers_400_with_sorted_errors(
    client: AsyncClient, override_dependencies: MagicMock
) -> None:
    # given
    payload: dict[str, Any] = {"text": "x"}
    # when
    response = await client.post("/api/v1/memory/insert", json=payload)
    # then
    assert response.status_code == 400
    body = response.json()
    assert body["code"] == "validation"
    assert isinstance(body["errors"], list)
    fields = [entry["field"] for entry in body["errors"]]
    assert fields == sorted(fields)
    assert all("message" in entry for entry in body["errors"])


@pytest.mark.asyncio
async def test_unknown_path_answers_problem_404_with_trace_id(
    client: AsyncClient, override_dependencies: MagicMock
) -> None:
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
async def test_wrong_method_answers_problem_405_with_allow(
    client: AsyncClient, override_dependencies: MagicMock
) -> None:
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
    client: AsyncClient, override_dependencies: MagicMock
) -> None:
    # given
    mock_service = override_dependencies
    sentinel = "UPSTREAM_LEAK_MARKER_99"
    mock_service.add.side_effect = RuntimeError(f"upstream blew up with {sentinel}")
    # when
    response = await client.post(
        "/api/v1/memory/insert",
        json={"user_id": "u1", "text": "x"},
    )
    # then
    assert response.status_code == 500
    body = response.json()
    assert body["code"] == "internal"
    assert re.fullmatch(r"[0-9a-f]{32}", body["traceId"]) is not None
    assert sentinel not in response.text


def test_mcp_insert_validation_raises_tool_error() -> None:
    # given
    bad_text = ""
    # when
    with pytest.raises(Exception, match=r"^validation: ") as exc_info:
        memory_insert(text=bad_text)
    # then
    assert str(exc_info.value).startswith("validation: ")


def test_mcp_search_validation_raises_tool_error() -> None:
    # given
    bad_query = "   "
    # when
    with pytest.raises(Exception, match=r"^validation: ") as exc_info:
        memory_search(query=bad_query)
    # then
    assert str(exc_info.value).startswith("validation: ")


def test_mcp_delete_validation_raises_tool_error() -> None:
    # given
    bad_id = ""
    # when
    with pytest.raises(Exception, match=r"^validation: ") as exc_info:
        memory_delete(memory_id=bad_id)
    # then
    assert str(exc_info.value).startswith("validation: ")


def test_mcp_wipe_unknown_provider_raises_tool_error() -> None:
    # given
    bad_provider = "not-real"
    # when
    with pytest.raises(Exception, match=r"^validation: ") as exc_info:
        memory_wipe(provider=bad_provider)
    # then
    assert str(exc_info.value).startswith("validation: ")


@pytest.mark.asyncio
async def test_ready_not_ready_body_on_503(client: AsyncClient, override_dependencies: MagicMock) -> None:
    # given
    with (
        patch.object(
            readiness_module, "probe_qdrant", new=AsyncMock(return_value=ProbeResult(status="error"))
        ),
        patch.object(
            readiness_module, "probe_embedding_api", new=AsyncMock(return_value=ProbeResult(status="ok"))
        ),
        patch.object(readiness_module, "probe_mem0_client", return_value=ProbeResult(status="ok")),
    ):
        # when
        response = await client.get("/ready")
        # then
        assert response.status_code == 503
        body = response.json()
        assert body["status"] == "not-ready"
        assert body["service"] == "ascend-memory"
        assert isinstance(body["version"], str)
    assert len(body["version"]) > 0


@pytest.mark.asyncio
async def test_health_includes_service_and_version(
    client: AsyncClient, override_dependencies: MagicMock
) -> None:
    # given
    path = "/health"
    # when
    response = await client.get(path)
    # then
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "ascend-memory"
    assert isinstance(body["version"], str)
    assert len(body["version"]) > 0

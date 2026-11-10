import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from asgi_lifespan import LifespanManager
from fastmcp import Client
from fastmcp.exceptions import ToolError
from httpx import ASGITransport, AsyncClient

import src.api.mcp.mcp_server as mcp_module
from src.api.mcp.mcp_server import mcp
from src.main import create_app
from src.service.job_runner import JobRunner
from src.service.job_service import JobService
from src.service.job_store import JobStore
from tests.conftest import VALID_PNG_BYTES, FakeResultStore

EXPECTED_TOOL_NAMES = {
    "ocr_submit",
    "ocr_job_status",
    "ocr_list_jobs",
    "ocr_cancel_job",
}


@pytest.fixture
def pin_store(jobs_dir: Path, results: FakeResultStore) -> JobStore:
    _ = jobs_dir

    return JobStore(results)


@pytest.fixture
def pin_runner(pin_store: JobStore, results: FakeResultStore) -> JobRunner:
    return JobRunner(pin_store, results)


@pytest.fixture(autouse=True)
def pin_service(
    pin_store: JobStore, results: FakeResultStore, pin_runner: JobRunner, monkeypatch: pytest.MonkeyPatch
) -> JobService:
    built = JobService(pin_store, results, pin_runner)
    monkeypatch.setattr(mcp_module, "job_service", built)
    monkeypatch.setattr(mcp_module, "_fetch_file", AsyncMock(return_value=(VALID_PNG_BYTES, "scan.png")))

    return built


async def test_tools_list_advertises_the_four_ocr_tools() -> None:
    tools = await mcp.list_tools()

    assert {tool.name for tool in tools} == EXPECTED_TOOL_NAMES


async def test_tools_list_input_schemas_pin_required_fields() -> None:
    tools = {tool.name: tool for tool in await mcp.list_tools()}

    submit_params = tools["ocr_submit"].parameters
    assert submit_params["required"] == ["file_uri"]
    assert set(submit_params["properties"]) == {"file_uri", "lang", "quality", "straighten"}

    status_params = tools["ocr_job_status"].parameters
    assert status_params["required"] == ["job_id"]
    assert set(status_params["properties"]) == {"job_id"}

    list_params = tools["ocr_list_jobs"].parameters
    assert list_params.get("required", []) in (None, [])
    assert list_params.get("properties", {}) == {}

    cancel_params = tools["ocr_cancel_job"].parameters
    assert cancel_params["required"] == ["job_id"]
    assert set(cancel_params["properties"]) == {"job_id"}


def _text_of(result: Any) -> str:
    return str(result.content[0].text)


async def test_call_ocr_submit_pins_content_and_structured() -> None:
    async with Client(mcp) as client:
        result = await client.call_tool("ocr_submit", {"file_uri": "https://files.example/scan.png"})

    assert result.is_error is False
    body = json.loads(_text_of(result))
    assert body["state"] == "waiting"
    assert isinstance(body["job_id"], str)
    assert len(body["job_id"]) > 0
    assert result.structured_content == body
    assert result.data == body


async def test_call_ocr_job_status_pins_content_and_structured() -> None:
    async with Client(mcp) as client:
        submitted = await client.call_tool("ocr_submit", {"file_uri": "https://files.example/a.png"})
        job_id = str(json.loads(_text_of(submitted))["job_id"])
        result = await client.call_tool("ocr_job_status", {"job_id": job_id})

    assert result.is_error is False
    body = json.loads(_text_of(result))
    assert body["job_id"] == job_id
    assert body["state"] == "waiting"
    assert result.structured_content == body
    assert result.data == body


async def test_call_ocr_list_jobs_pins_content_and_structured() -> None:
    async with Client(mcp) as client:
        first = await client.call_tool("ocr_submit", {"file_uri": "https://files.example/first.png"})
        second = await client.call_tool("ocr_submit", {"file_uri": "https://files.example/second.png"})
        first_id = str(json.loads(_text_of(first))["job_id"])
        second_id = str(json.loads(_text_of(second))["job_id"])
        result = await client.call_tool("ocr_list_jobs", {})

    assert result.is_error is False
    body = json.loads(_text_of(result))
    assert [job["job_id"] for job in body["jobs"]] == [first_id, second_id]
    assert result.structured_content == body
    assert result.data == body


async def test_call_ocr_cancel_job_pins_content_and_structured() -> None:
    async with Client(mcp) as client:
        submitted = await client.call_tool("ocr_submit", {"file_uri": "https://files.example/drop.png"})
        job_id = str(json.loads(_text_of(submitted))["job_id"])
        result = await client.call_tool("ocr_cancel_job", {"job_id": job_id})

    expected = {"job_id": job_id, "cancelled": True}
    assert result.is_error is False
    assert json.loads(_text_of(result)) == expected
    assert result.structured_content == expected
    assert result.data == expected


async def test_call_unknown_job_pins_job_not_found_tool_error() -> None:
    with pytest.raises(ToolError, match=r"^JOB_NOT_FOUND: ") as exc_info:
        async with Client(mcp) as client:
            await client.call_tool("ocr_job_status", {"job_id": "00000000-0000-4000-8000-000000000000"})

    assert str(exc_info.value).startswith("JOB_NOT_FOUND: ")


async def _post_mcp(client: AsyncClient, payload: dict[str, Any], session_id: str | None) -> Any:
    headers = {"Accept": "application/json, text/event-stream"}
    if session_id is not None:
        headers["mcp-session-id"] = session_id
    return await client.post("/mcp", json=payload, headers=headers)


async def test_2025_11_25_session_lists_tools_and_lists_jobs(jobs_dir: Path) -> None:
    _ = jobs_dir
    init_payload: dict[str, Any] = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-11-25",
            "capabilities": {},
            "clientInfo": {"name": "platform-test", "version": "0.1.0"},
        },
    }
    app = create_app()
    with (
        patch("src.main.start_worker_pool"),
        patch("src.main.stop_worker_pool"),
        patch("src.main.result_store.ensure_bucket", return_value=True),
    ):
        async with LifespanManager(app):
            transport = ASGITransport(app=app, raise_app_exceptions=False)
            async with AsyncClient(transport=transport, base_url="http://testserver") as client:
                init_response = await _post_mcp(client, init_payload, None)
                assert init_response.status_code == 200
                assert "2025-11-25" in init_response.text
                assert "ascend-ocr" in init_response.text
                session_id = init_response.headers.get("mcp-session-id")

                notified = await _post_mcp(
                    client, {"jsonrpc": "2.0", "method": "notifications/initialized"}, session_id
                )
                assert notified.status_code in (200, 202)

                listed = await _post_mcp(
                    client, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, session_id
                )
                assert listed.status_code == 200
                for name in EXPECTED_TOOL_NAMES:
                    assert name in listed.text

                called = await _post_mcp(
                    client,
                    {
                        "jsonrpc": "2.0",
                        "id": 3,
                        "method": "tools/call",
                        "params": {"name": "ocr_list_jobs", "arguments": {}},
                    },
                    session_id,
                )
                assert called.status_code == 200
                assert "jobs" in called.text


async def test_client_without_explicit_era_documents_fastmcp3_default() -> None:
    async with Client(mcp) as client:
        tools = await client.list_tools()

    assert {tool.name for tool in tools} == EXPECTED_TOOL_NAMES

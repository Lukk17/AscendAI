import json
from typing import Any
from unittest.mock import MagicMock, patch

from asgi_lifespan import LifespanManager
from fastmcp import Client
from httpx import ASGITransport, AsyncClient

from src.api.mcp.mcp_server import mcp
from src.main import app

EXPECTED_TOOL_NAMES = {"memory_insert", "memory_search", "memory_delete", "memory_wipe"}


async def test_tools_list_advertises_the_four_memory_tools() -> None:
    tools = await mcp.list_tools()

    assert {tool.name for tool in tools} == EXPECTED_TOOL_NAMES


async def test_tools_list_input_schemas_pin_required_fields() -> None:
    tools = {tool.name: tool for tool in await mcp.list_tools()}

    insert_params = tools["memory_insert"].parameters
    assert insert_params["required"] == ["text"]
    assert set(insert_params["properties"]) == {"text", "user_id", "provider", "metadata"}
    assert insert_params["properties"]["text"] == {"type": "string"}

    search_params = tools["memory_search"].parameters
    assert search_params["required"] == ["query"]
    assert set(search_params["properties"]) == {"query", "user_id", "limit", "provider"}
    assert search_params["properties"]["limit"]["default"] == 5

    delete_params = tools["memory_delete"].parameters
    assert delete_params["required"] == ["memory_id"]
    assert set(delete_params["properties"]) == {"memory_id", "provider"}

    wipe_params = tools["memory_wipe"].parameters
    assert set(wipe_params["properties"]) == {"user_id", "provider"}
    assert wipe_params.get("required", []) == []


def _text_of(result: Any) -> str:
    return str(result.content[0].text)


@patch("src.api.mcp.mcp_server.get_memory_client")
async def test_call_memory_insert_pins_content_and_structured(
    mock_get_client: MagicMock,
) -> None:
    mock_service = MagicMock()
    mock_service.add.return_value = [{"id": "m1"}]
    mock_get_client.return_value = mock_service

    async with Client(mcp) as client:
        result = await client.call_tool("memory_insert", {"text": "hello", "user_id": "u1"})

    assert result.is_error is False
    assert json.loads(_text_of(result)) == {"status": "success", "results": [{"id": "m1"}]}
    assert result.structured_content == {"status": "success", "results": [{"id": "m1"}]}
    assert result.data == {"status": "success", "results": [{"id": "m1"}]}


@patch("src.api.mcp.mcp_server.get_memory_client")
async def test_call_memory_search_pins_content_and_structured(
    mock_get_client: MagicMock,
) -> None:
    mock_service = MagicMock()
    mock_service.search.return_value = [{"id": "m1", "score": 0.8}]
    mock_get_client.return_value = mock_service

    async with Client(mcp) as client:
        result = await client.call_tool("memory_search", {"query": "find me"})

    expected = {"status": "success", "results": [{"id": "m1", "score": 0.8}]}
    assert result.is_error is False
    assert json.loads(_text_of(result)) == expected
    assert result.structured_content == expected
    assert result.data == expected


@patch("src.api.mcp.mcp_server.get_memory_client")
async def test_call_memory_delete_pins_content_and_structured(
    mock_get_client: MagicMock,
) -> None:
    mock_service = MagicMock()
    mock_get_client.return_value = mock_service

    async with Client(mcp) as client:
        result = await client.call_tool("memory_delete", {"memory_id": "m1"})

    expected = {"status": "success", "message": "Memory m1 deleted."}
    assert result.is_error is False
    assert json.loads(_text_of(result)) == expected
    assert result.structured_content == expected
    assert result.data == expected


@patch("src.api.mcp.mcp_server.wipe_user_all_collections")
async def test_call_memory_wipe_pins_content_and_structured(mock_wipe_all: MagicMock) -> None:
    async with Client(mcp) as client:
        result = await client.call_tool("memory_wipe", {"user_id": "u1"})

    expected = {"status": "success", "message": "All memories wiped for user u1."}
    assert result.is_error is False
    assert json.loads(_text_of(result)) == expected
    assert result.structured_content == expected
    assert result.data == expected
    assert mock_wipe_all.call_count == 1


async def _post_mcp(client: AsyncClient, payload: dict[str, Any], session_id: str | None) -> Any:
    headers = {"Accept": "application/json, text/event-stream"}
    if session_id is not None:
        headers["mcp-session-id"] = session_id
    return await client.post("/mcp", json=payload, headers=headers)


async def test_2025_11_25_session_lists_tools_and_calls_search() -> None:
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
    with patch("src.api.mcp.mcp_server.get_memory_client") as mock_get_client:
        mock_service = MagicMock()
        mock_service.search.return_value = [{"id": "m1", "score": 0.8}]
        mock_get_client.return_value = mock_service
        async with LifespanManager(app):
            transport = ASGITransport(app=app, raise_app_exceptions=False)
            async with AsyncClient(transport=transport, base_url="http://testserver") as client:
                init_response = await _post_mcp(client, init_payload, None)
                assert init_response.status_code == 200
                assert "2025-11-25" in init_response.text
                assert "ascend-memory" in init_response.text
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
                        "params": {
                            "name": "memory_search",
                            "arguments": {"query": "find me"},
                        },
                    },
                    session_id,
                )
                assert called.status_code == 200
                assert "m1" in called.text
                assert "success" in called.text


async def test_client_without_explicit_era_documents_fastmcp3_default() -> None:
    async with Client(mcp) as client:
        tools = await client.list_tools()

    assert {tool.name for tool in tools} == EXPECTED_TOOL_NAMES

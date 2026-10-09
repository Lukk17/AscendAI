import json
from unittest.mock import MagicMock

import pytest
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient

from src.main import app


@pytest.mark.asyncio
async def test_mcp_initialize_reports_server_name_ascend_memory(
    override_dependencies: MagicMock,
) -> None:
    # given
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "platform-test", "version": "0.1.0"},
        },
    }
    # when
    async with LifespanManager(app):
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.post(
                "/mcp",
                json=payload,
                headers={"Accept": "application/json, text/event-stream"},
            )
    # then
    assert response.status_code == 200
    data_lines = [line[len("data: ") :] for line in response.text.splitlines() if line.startswith("data: ")]
    assert data_lines
    bodies = [json.loads(line) for line in data_lines]
    results = [body["result"] for body in bodies if "result" in body]
    assert results
    assert results[0]["serverInfo"]["name"] == "ascend-memory"

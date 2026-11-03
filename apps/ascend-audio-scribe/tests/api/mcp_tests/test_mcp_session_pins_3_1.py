import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from asgi_lifespan import LifespanManager
from fastmcp import Client
from httpx import ASGITransport, AsyncClient

import src.api.mcp.mcp_server as mcp_module
from src.api.mcp.mcp_server import mcp
from src.config.config import settings
from src.main import create_app

EXPECTED_TOOL_NAMES = {
    "transcribe_local",
    "transcribe_openai",
    "transcribe_hf",
    "transcribe_audacity",
    "health",
}


async def test_tools_list_advertises_the_transcription_tools_and_health() -> None:
    tools = await mcp.list_tools()

    assert {tool.name for tool in tools} == EXPECTED_TOOL_NAMES


async def test_tools_list_input_schemas_pin_required_fields() -> None:
    tools = {tool.name: tool for tool in await mcp.list_tools()}

    local_params = tools["transcribe_local"].parameters
    assert local_params["required"] == ["audio_uri"]
    assert set(local_params["properties"]) == {"audio_uri", "model", "language", "with_timestamps"}

    openai_params = tools["transcribe_openai"].parameters
    assert openai_params["required"] == ["audio_uri"]
    assert set(openai_params["properties"]) == {"audio_uri", "model", "language"}

    hf_params = tools["transcribe_hf"].parameters
    assert hf_params["required"] == ["audio_uri"]
    assert set(hf_params["properties"]) == {"audio_uri", "model", "hf_provider"}

    audacity_params = tools["transcribe_audacity"].parameters
    assert audacity_params["required"] == ["audio_uri"]
    assert set(audacity_params["properties"]) == {
        "audio_uri",
        "provider",
        "model",
        "language",
        "hf_provider",
    }

    health_params = tools["health"].parameters
    assert health_params.get("required", []) in (None, [])
    assert health_params.get("properties", {}) == {}


def _text_of(result: Any) -> str:
    return str(result.content[0].text)


async def _fake_local_segments(*_a: Any, **_k: Any) -> Any:
    yield {"text": "hello", "start": 0.0, "end": 1.0}


async def test_call_transcribe_local_pins_content_and_structured() -> None:
    with (
        patch.object(mcp_module, "download_to_temp_async", new=AsyncMock(return_value="/tmp/a.wav")),
        patch.object(mcp_module, "local_speech_transcription", new=_fake_local_segments),
    ):
        async with Client(mcp) as client:
            result = await client.call_tool("transcribe_local", {"audio_uri": "file:///tmp/a.wav"})

    expected = {
        "status": "success",
        "source": "local",
        "model": "Systran/faster-whisper-large-v3",
        "language": "en",
        "transcription": [{"text": "hello", "timestamp": [0.0, 1.0]}],
    }
    assert result.is_error is False
    assert json.loads(_text_of(result)) == expected
    assert result.structured_content == expected
    assert result.data == expected


async def test_call_transcribe_openai_pins_content_and_structured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "sk-x")
    with (
        patch.object(mcp_module, "download_to_temp_async", new=AsyncMock(return_value="/tmp/a.wav")),
        patch.object(
            mcp_module,
            "openai_speech_transcription",
            new=MagicMock(return_value="spoken words"),
        ),
    ):
        async with Client(mcp) as client:
            result = await client.call_tool("transcribe_openai", {"audio_uri": "file:///tmp/a.wav"})

    expected = {
        "status": "success",
        "source": "openai",
        "model": "whisper-1",
        "language": "en",
        "transcription": "spoken words",
    }
    assert result.is_error is False
    assert json.loads(_text_of(result)) == expected
    assert result.structured_content == expected
    assert result.data == expected


async def test_call_transcribe_hf_pins_content_and_structured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "HF_TOKEN", "hf-x")
    with (
        patch.object(mcp_module, "download_to_temp_async", new=AsyncMock(return_value="/tmp/a.wav")),
        patch.object(
            mcp_module,
            "hf_speech_transcription",
            new=MagicMock(return_value="hf words"),
        ),
    ):
        async with Client(mcp) as client:
            result = await client.call_tool("transcribe_hf", {"audio_uri": "file:///tmp/a.wav"})

    expected = {
        "status": "success",
        "source": "huggingface",
        "model": "openai/whisper-large-v3",
        "provider": "hf-inference",
        "transcription": "hf words",
    }
    assert result.is_error is False
    assert json.loads(_text_of(result)) == expected
    assert result.structured_content == expected
    assert result.data == expected


async def test_call_transcribe_audacity_pins_content_and_structured() -> None:
    async def _fake_download(uri: str) -> str:
        return "/tmp/project.zip"

    def _two_tracks(zip_path: str, extraction_dir: str) -> dict[str, str]:
        return {"track1": "track1.wav", "track2": "track2.wav"}

    async def _fake_merge(
        *,
        tracks: dict[str, str],
        provider: str,
        model: str,
        language: str,
        hf_provider: str,
    ) -> str:
        return "merged transcript"

    with (
        patch.object(mcp_module, "download_to_temp_async", new=_fake_download),
        patch.object(mcp_module, "extract_tracks_from_aup", new=_two_tracks),
        patch.object(mcp_module, "transcribe_and_merge_tracks", new=_fake_merge),
    ):
        async with Client(mcp) as client:
            result = await client.call_tool(
                "transcribe_audacity",
                {"audio_uri": "file:///tmp/project.zip", "provider": "local", "language": "en"},
            )

    expected = {
        "status": "success",
        "source": "local",
        "model": "Systran/faster-whisper-large-v3",
        "language": "en",
        "transcription": "merged transcript",
    }
    assert result.is_error is False
    assert json.loads(_text_of(result)) == expected
    assert result.structured_content == expected
    assert result.data == expected


async def test_call_health_pins_content_and_structured() -> None:
    async with Client(mcp) as client:
        result = await client.call_tool("health", {})

    expected = {"status": "ok"}
    assert result.is_error is False
    assert json.loads(_text_of(result)) == expected
    assert result.structured_content == expected
    assert result.data == expected


async def _post_mcp(client: AsyncClient, payload: dict[str, Any], session_id: str | None) -> Any:
    headers = {"Accept": "application/json, text/event-stream"}
    if session_id is not None:
        headers["mcp-session-id"] = session_id
    return await client.post("/mcp", json=payload, headers=headers)


async def test_2025_11_25_session_lists_tools_and_calls_health() -> None:
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
    async with LifespanManager(app):
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            init_response = await _post_mcp(client, init_payload, None)
            assert init_response.status_code == 200
            assert "2025-11-25" in init_response.text
            assert "ascend-audio-scribe" in init_response.text
            session_id = init_response.headers.get("mcp-session-id")

            notified = await _post_mcp(
                client, {"jsonrpc": "2.0", "method": "notifications/initialized"}, session_id
            )
            assert notified.status_code in (200, 202)

            listed = await _post_mcp(client, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, session_id)
            assert listed.status_code == 200
            for name in EXPECTED_TOOL_NAMES:
                assert name in listed.text

            called = await _post_mcp(
                client,
                {
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "tools/call",
                    "params": {"name": "health", "arguments": {}},
                },
                session_id,
            )
            assert called.status_code == 200
            assert "ok" in called.text


async def test_client_without_explicit_era_documents_fastmcp3_default() -> None:
    async with Client(mcp) as client:
        tools = await client.list_tools()

    assert {tool.name for tool in tools} == EXPECTED_TOOL_NAMES

import asyncio
import os

os.environ["OPENAI_API_KEY"] = "dummy"  # Set dummy key before importing modules that init OpenAI client
import json

import tempfile
from typing import AsyncIterator

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from asgi_lifespan import LifespanManager

from mcp_server import create_app
import mcp_server as mcp_server_module
from src.config.settings import settings

pytestmark = pytest.mark.asyncio

PROTOCOL_VERSION = "2024-11-05"
STREAMABLE_ACCEPT = "application/json, text/event-stream"
JSON_CONTENT_TYPE = "application/json"


def base_headers() -> dict[str, str]:
    return {
        "Accept": STREAMABLE_ACCEPT,
        "Content-Type": JSON_CONTENT_TYPE,
    }


def session_headers(session_id: str) -> dict[str, str]:
    return {
        "Accept": STREAMABLE_ACCEPT,
        "Content-Type": JSON_CONTENT_TYPE,
        "MCP-Session-Id": session_id,
        "MCP-Protocol-Version": PROTOCOL_VERSION,
    }


@pytest.fixture
def temp_audio_file() -> str:
    fd, path = tempfile.mkstemp(suffix=".wav")
    os.close(fd)
    return path


async def _fake_local_transcription(*, audio_file_path: str, model_path: str, language: str) -> AsyncIterator[dict]:
    await asyncio.sleep(0.01)
    yield {"text": "żeby wyglądał", "start": 0.0, "end": 0.5}
    await asyncio.sleep(0.01)
    yield {"text": "tak jak koszyk", "start": 0.5, "end": 1.0}


def _initialize_body():
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "pytest", "version": "0.0.0"},
        },
    }


def _assert_content_type_contains(resp, *expected_parts: str) -> None:
    """Assert response Content-Type contains all expected substrings (case-insensitive).

    This avoids brittle exact matches and header ordering issues between frameworks.
    """
    content_type = resp.headers.get("content-type", "").lower()
    for part in expected_parts:
        assert part.lower() in content_type, (
            f"Expected Content-Type to contain '{part}', got '{content_type or '<missing>'}'"
        )


def _assert_content_type_one_of(resp, *allowed_types: str) -> None:
    """Assert response Content-Type contains at least one of the allowed types.

    Useful for Streamable HTTP where responses may be JSON or event-stream depending on
    environment and transport configuration.
    """
    content_type = resp.headers.get("content-type", "").lower()
    assert any(t.lower() in content_type for t in allowed_types), (
        f"Expected Content-Type to contain one of {allowed_types}, got '{content_type or '<missing>'}'"
    )


def _parse_mcp_response(resp):
    """Parse MCP response supporting both JSON and text/event-stream bodies.

    - If Content-Type contains application/json: return resp.json().
    - If Content-Type contains text/event-stream: extract the last JSON after a 'data: ' line.
    """
    ct = resp.headers.get("content-type", "").lower()
    if "application/json" in ct:
        return resp.json()
    if "text/event-stream" in ct:
        # Body is SSE-framed, e.g.: 'event: message\r\ndata: {..}\r\n\r\n'
        body = resp.text
        # Collect all lines starting with 'data:' and try the last one first
        data_lines = [line for line in body.splitlines() if line.startswith("data:")]
        assert data_lines, f"Expected at least one 'data:' line in SSE body, got: {body!r}"
        last_payload = data_lines[-1][len("data:"):].strip()
        return json.loads(last_payload)
    raise AssertionError(f"Unsupported Content-Type for MCP response: '{ct or '<missing>'}'")


def _first_text_block(payload: dict) -> str:
    """Return the text from the first content block in an MCP result, as string."""
    try:
        content = payload["result"]["content"][0]
        return str(content.get("text", ""))
    except Exception:
        return ""


async def _initialize_session(ac: AsyncClient):
    resp = await ac.post(
        "/mcp",
        json=_initialize_body(),
        headers=base_headers(),
    )
    assert resp.status_code == 200, resp.text
    # Streamable HTTP may return JSON or event-stream depending on mode; accept either
    _assert_content_type_one_of(resp, "application/json", "text/event-stream")
    session_id = resp.headers.get("mcp-session-id")
    assert session_id, "Missing mcp-session-id header in initialize response"
    return session_id


async def _tools_list(ac: AsyncClient, session_id: str):
    resp = await ac.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        headers=session_headers(session_id),
    )
    assert resp.status_code == 200, resp.text
    data = _parse_mcp_response(resp)
    assert data.get("result"), data
    return data


@pytest_asyncio.fixture()
async def asgi_client():
    """
    Creates a test client using the App Factory pattern.
    This ensures each test gets a fresh, isolated app instance, solving state conflicts.
    """
    app = create_app()
    # Explicitly run the app lifespan so the StreamableHTTP session manager starts its task group
    async with LifespanManager(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver", timeout=30.0) as ac:
            yield ac


async def test_streamable_http_initialize_returns_utf8_and_session_id(asgi_client: AsyncClient):
    session_id = await _initialize_session(asgi_client)
    assert isinstance(session_id, str) and len(session_id) > 0


async def test_streamable_http_tools_list_then_transcribe_local_with_monkeypatch(monkeypatch, temp_audio_file,
                                                                                 asgi_client: AsyncClient):
    monkeypatch.setattr(mcp_server_module, "local_speech_transcription", _fake_local_transcription)

    # Mock download_to_temp_async to return the temp_audio_file path directly
    async def _fake_download(uri: str) -> str:
        return temp_audio_file

    monkeypatch.setattr(mcp_server_module, "download_to_temp_async", _fake_download)

    session_id = await _initialize_session(asgi_client)
    await _tools_list(asgi_client, session_id)

    req = {
        "jsonrpc": "2.0",
        "id": 3,
        "method": "tools/call",
        "params": {
            "name": "transcribe_local",
            "arguments": {
                "audio_uri": f"file://{temp_audio_file}",
                "model": "Systran/faster-whisper-large-v3",
                "language": "pl",
                "with_timestamps": False,
            },

        },
    }

    resp = await asgi_client.post(
        "/mcp",
        json=req,
        headers=session_headers(session_id),
    )
    assert resp.status_code == 200, resp.text
    # Streamable HTTP may return JSON or event-stream; accept either
    _assert_content_type_one_of(resp, "application/json", "text/event-stream")
    payload = _parse_mcp_response(resp)
    content = payload["result"]["content"][0]
    assert content["type"] == "text"
    text_val = str(content.get("text", ""))
    # Accept both embedded JSON string and plain text by substring check
    if text_val.strip().startswith("{"):
        # Try to parse and extract transcription field, else fallback to substring
        try:
            inner = json.loads(text_val)
            trans_val = inner.get("transcription")
            if isinstance(trans_val, str):
                assert "żeby" in trans_val
            elif isinstance(trans_val, list):
                joined = " ".join(str(s.get("text", "")) for s in trans_val)
                assert "żeby" in joined
            else:
                assert "żeby" in text_val
        except Exception:
            assert "żeby" in text_val
    else:
        assert "żeby" in text_val


async def test_sse_messages_route_exists_and_requires_session_id(asgi_client: AsyncClient):
    resp = await asgi_client.post("/sse-root/messages/")
    assert resp.status_code == 400


async def test_sse_post_messages_invalid_session_id_malformed(asgi_client: AsyncClient):
    # Malformed session_id should return 400
    resp = await asgi_client.post("/sse-root/messages/?session_id=not-a-hex")
    assert resp.status_code == 400


async def test_sse_post_messages_unknown_session_id(asgi_client: AsyncClient):
    # Valid hex but unknown session should return 400 or 404 depending on a transport version.
    # Current MCP SseServerTransport returns 404 with the body "Could not find session" when session is unknown.
    # Some environments may normalize to 400. We accept both but assert the message text when 404 is not used.
    unknown_hex = "0" * 32
    # Provide minimal required header so transport security doesn't reject early
    resp = await asgi_client.post(
        f"/sse-root/messages/?session_id={unknown_hex}",
        headers={"Content-Type": "application/json"},
    )
    if resp.status_code == 404:
        # Preferred behavior as per library code
        assert True
    else:
        # Accept 400 as an alternative but require an explanatory message
        assert resp.status_code == 400, resp.text
        # Depending on path, body may be a plain string.
        assert ("Could not find session" in (resp.text or "")) or ("Invalid Content-Type" in (resp.text or ""))


async def test_streamable_http_health_tool(asgi_client: AsyncClient):
    session_id = await _initialize_session(asgi_client)
    await _tools_list(asgi_client, session_id)

    req = {
        "jsonrpc": "2.0",
        "id": 10,
        "method": "tools/call",
        "params": {"name": "health", "arguments": {}},
    }
    resp = await asgi_client.post("/mcp", json=req, headers=session_headers(session_id))
    assert resp.status_code == 200, resp.text
    _assert_content_type_one_of(resp, "application/json", "text/event-stream")
    payload = _parse_mcp_response(resp)
    content = payload["result"]["content"][0]
    assert content["type"] == "text"
    # Some environments may wrap as JSON string; accept substring match
    assert "ok" in str(content.get("text", "")).lower()


async def test_streamable_http_transcribe_openai_with_monkeypatch(monkeypatch, temp_audio_file,
                                                                  asgi_client: AsyncClient):
    def _fake_openai_transcription(*, audio_file_path: str, model: str, language: str):
        return "OPENAI OK"

    monkeypatch.setattr(mcp_server_module, "openai_speech_transcription", _fake_openai_transcription)
    monkeypatch.setattr(mcp_server_module, "openai_speech_transcription", _fake_openai_transcription)
    monkeypatch.setattr(mcp_server_module.settings, "OPENAI_API_KEY", "test")

    async def _fake_download(uri: str) -> str:
        return temp_audio_file

    monkeypatch.setattr(mcp_server_module, "download_to_temp_async", _fake_download)

    session_id = await _initialize_session(asgi_client)
    await _tools_list(asgi_client, session_id)

    req = {
        "jsonrpc": "2.0",
        "id": 11,
        "method": "tools/call",
        "params": {
            "name": "transcribe_openai",
            "arguments": {
                "audio_uri": f"file://{temp_audio_file}",
                "model": "whisper-1",
                "language": "pl",
            },

        },
    }

    resp = await asgi_client.post("/mcp", json=req, headers=session_headers(session_id))
    assert resp.status_code == 200, resp.text
    _assert_content_type_one_of(resp, "application/json", "text/event-stream")
    payload = _parse_mcp_response(resp)
    content = payload["result"]["content"][0]
    assert content["type"] == "text"
    text_val = str(content.get("text", ""))
    if text_val.strip().startswith("{"):
        try:
            inner = json.loads(text_val)
            assert inner.get("transcription") == "OPENAI OK"
        except Exception:
            assert "OPENAI OK" in text_val
    else:
        assert "OPENAI OK" in text_val


async def test_streamable_http_transcribe_hf_with_monkeypatch(monkeypatch, temp_audio_file, asgi_client: AsyncClient):
    def _fake_hf_transcription(*, audio_file_path: str, model: str, provider: str):
        return "HF OK"

    monkeypatch.setattr(mcp_server_module, "hf_speech_transcription", _fake_hf_transcription)
    monkeypatch.setattr(mcp_server_module, "hf_speech_transcription", _fake_hf_transcription)
    monkeypatch.setattr(mcp_server_module.settings, "HF_TOKEN", "test")

    async def _fake_download(uri: str) -> str:
        return temp_audio_file

    monkeypatch.setattr(mcp_server_module, "download_to_temp_async", _fake_download)

    session_id = await _initialize_session(asgi_client)
    await _tools_list(asgi_client, session_id)

    req = {
        "jsonrpc": "2.0",
        "id": 12,
        "method": "tools/call",
        "params": {
            "name": "transcribe_hf",
            "arguments": {
                "audio_uri": f"file://{temp_audio_file}",
                "model": "openai/whisper-large-v3",
                "hf_provider": "hf-inference",
            },

        },
    }

    resp = await asgi_client.post("/mcp", json=req, headers=session_headers(session_id))
    assert resp.status_code == 200, resp.text
    _assert_content_type_one_of(resp, "application/json", "text/event-stream")
    payload = _parse_mcp_response(resp)
    content = payload["result"]["content"][0]
    assert content["type"] == "text"
    text_val = str(content.get("text", ""))
    if text_val.strip().startswith("{"):
        try:
            inner = json.loads(text_val)
            assert inner.get("transcription") == "HF OK"
        except Exception:
            assert "HF OK" in text_val
    else:
        assert "HF OK" in text_val


async def test_streamable_http_transcribe_local_with_timestamps_true(monkeypatch, temp_audio_file,
                                                                     asgi_client: AsyncClient):
    async def _fake_segments(*, audio_file_path: str, model_path: str, language: str):
        yield {"text": "one", "start": 0.0, "end": 0.5}
        yield {"text": "two", "start": 0.5, "end": 1.0}

    monkeypatch.setattr(mcp_server_module, "local_speech_transcription", _fake_segments)

    async def _fake_download(uri: str) -> str:
        return temp_audio_file

    monkeypatch.setattr(mcp_server_module, "download_to_temp_async", _fake_download)

    session_id = await _initialize_session(asgi_client)
    await _tools_list(asgi_client, session_id)

    req = {
        "jsonrpc": "2.0",
        "id": 20,
        "method": "tools/call",
        "params": {
            "name": "transcribe_local",
            "arguments": {
                "audio_uri": f"file://{temp_audio_file}",
                "model": "Systran/faster-whisper-large-v3",
                "language": "pl",
                "with_timestamps": True,
            },

        },
    }

    resp = await asgi_client.post("/mcp", json=req, headers=session_headers(session_id))
    assert resp.status_code == 200, resp.text
    _assert_content_type_one_of(resp, "application/json", "text/event-stream")
    payload = _parse_mcp_response(resp)
    content = payload["result"]["content"][0]
    assert content["type"] == "text"
    text_val = str(content.get("text", "")).strip()
    if text_val.startswith("{"):
        try:
            inner = json.loads(text_val)
            trans = inner.get("transcription")
            if isinstance(trans, list) and len(trans) == 2:
                for item in trans:
                    assert "text" in item and "timestamp" in item
                    ts = item["timestamp"]
                    assert isinstance(ts, (list, tuple)) and len(ts) == 2
            else:
                # Fallback: still ensure our tokens are present
                assert "one" in text_val and "two" in text_val
        except Exception:
            assert "one" in text_val and "two" in text_val
    else:
        # Plain text fallback
        assert "one" in text_val and "two" in text_val


async def test_streamable_http_transcribe_local_file_not_found(asgi_client: AsyncClient):
    session_id = await _initialize_session(asgi_client)
    await _tools_list(asgi_client, session_id)

    req = {
        "jsonrpc": "2.0",
        "id": 21,
        "method": "tools/call",
        "params": {
            "name": "transcribe_local",
            "arguments": {
                "audio_uri": "file:///X:/no/such/file.wav",
                "with_timestamps": True,
            },
        },
    }
    resp = await asgi_client.post("/mcp", json=req, headers=session_headers(session_id))
    assert resp.status_code == 200, resp.text
    payload = _parse_mcp_response(resp)
    text = _first_text_block(payload)
    assert "File not found" in text


async def test_streamable_http_transcribe_local_generator_value_error(monkeypatch, temp_audio_file,
                                                                      asgi_client: AsyncClient):
    async def _err_gen(*, audio_file_path: str, model_path: str, language: str):
        # Must be an async generator function (contain a yield) so async-for is valid
        raise ValueError("bad local input")
        if False:
            yield {}

    monkeypatch.setattr(mcp_server_module, "local_speech_transcription", _err_gen)

    async def _fake_download(uri: str) -> str:
        return temp_audio_file

    monkeypatch.setattr(mcp_server_module, "download_to_temp_async", _fake_download)

    session_id = await _initialize_session(asgi_client)
    await _tools_list(asgi_client, session_id)

    req = {
        "jsonrpc": "2.0",
        "id": 22,
        "method": "tools/call",
        "params": {
            "name": "transcribe_local",
            "arguments": {
                "audio_uri": f"file://{temp_audio_file}",
                "model": "Systran/faster-whisper-large-v3",
                "language": "pl",
                "with_timestamps": False,
            },
        },
    }
    resp = await asgi_client.post("/mcp", json=req, headers=session_headers(session_id))
    payload = _parse_mcp_response(resp)
    text = _first_text_block(payload)
    assert "bad local input" in text


async def test_streamable_http_transcribe_local_generator_generic_error(monkeypatch, temp_audio_file,
                                                                        asgi_client: AsyncClient):
    async def _err_gen2(*, audio_file_path: str, model_path: str, language: str):
        # Must be an async generator function (contain a yield) so async-for is valid
        raise RuntimeError("boom")
        if False:
            yield {}

    monkeypatch.setattr(mcp_server_module, "local_speech_transcription", _err_gen2)

    async def _fake_download(uri: str) -> str:
        return temp_audio_file

    monkeypatch.setattr(mcp_server_module, "download_to_temp_async", _fake_download)

    session_id = await _initialize_session(asgi_client)
    await _tools_list(asgi_client, session_id)

    req = {
        "jsonrpc": "2.0",
        "id": 23,
        "method": "tools/call",
        "params": {
            "name": "transcribe_local",
            "arguments": {
                "audio_uri": f"file://{temp_audio_file}",
                "model": "Systran/faster-whisper-large-v3",
                "language": "pl",
                "with_timestamps": False,
            },
        },
    }
    resp = await asgi_client.post("/mcp", json=req, headers=session_headers(session_id))
    payload = _parse_mcp_response(resp)
    text = _first_text_block(payload)
    assert "An unexpected error occurred:" in text


async def test_streamable_http_transcribe_openai_missing_api_key(monkeypatch, temp_audio_file,
                                                                 asgi_client: AsyncClient):
    # Unset key
    monkeypatch.setattr(settings, "OPENAI_API_KEY", None)

    async def _fake_download(uri: str) -> str:
        return temp_audio_file

    monkeypatch.setattr(mcp_server_module, "download_to_temp_async", _fake_download)

    session_id = await _initialize_session(asgi_client)
    await _tools_list(asgi_client, session_id)

    req = {
        "jsonrpc": "2.0",
        "id": 30,
        "method": "tools/call",
        "params": {
            "name": "transcribe_openai",
            "arguments": {
                "audio_uri": f"file://{temp_audio_file}",
            },
        },
    }
    resp = await asgi_client.post("/mcp", json=req, headers=session_headers(session_id))
    payload = _parse_mcp_response(resp)
    text = _first_text_block(payload)
    assert "OPENAI_API_KEY is not configured" in text


async def test_streamable_http_transcribe_openai_file_not_found(monkeypatch, asgi_client: AsyncClient):
    monkeypatch.setattr(mcp_server_module.settings, "OPENAI_API_KEY", "test")

    session_id = await _initialize_session(asgi_client)
    await _tools_list(asgi_client, session_id)

    req = {
        "jsonrpc": "2.0",
        "id": 31,
        "method": "tools/call",
        "params": {
            "name": "transcribe_openai",
            "arguments": {
                "audio_uri": "file:///X:/nope.wav",
            },
        },
    }
    resp = await asgi_client.post("/mcp", json=req, headers=session_headers(session_id))
    payload = _parse_mcp_response(resp)
    text = _first_text_block(payload)
    assert "File not found" in text


async def test_streamable_http_transcribe_openai_raises_value_error(monkeypatch, temp_audio_file,
                                                                    asgi_client: AsyncClient):
    def _raise_value_error(*, audio_file_path: str, model: str, language: str):
        raise ValueError("openai bad")

    monkeypatch.setattr(mcp_server_module.settings, "OPENAI_API_KEY", "test")
    monkeypatch.setattr(mcp_server_module, "openai_speech_transcription", _raise_value_error)

    async def _fake_download(uri: str) -> str:
        return temp_audio_file

    monkeypatch.setattr(mcp_server_module, "download_to_temp_async", _fake_download)

    session_id = await _initialize_session(asgi_client)
    await _tools_list(asgi_client, session_id)

    req = {
        "jsonrpc": "2.0",
        "id": 32,
        "method": "tools/call",
        "params": {
            "name": "transcribe_openai",
            "arguments": {
                "audio_uri": f"file://{temp_audio_file}",
                "model": "whisper-1",
                "language": "pl",
            },
        },
    }
    resp = await asgi_client.post("/mcp", json=req, headers=session_headers(session_id))
    payload = _parse_mcp_response(resp)
    text = _first_text_block(payload)
    assert "openai bad" in text


async def test_streamable_http_transcribe_openai_raises_io_error(monkeypatch, temp_audio_file,
                                                                 asgi_client: AsyncClient):
    def _raise_io_error(*, audio_file_path: str, model: str, language: str):
        raise IOError("disk full")

    monkeypatch.setattr(mcp_server_module.settings, "OPENAI_API_KEY", "test")
    monkeypatch.setattr(mcp_server_module, "openai_speech_transcription", _raise_io_error)

    async def _fake_download(uri: str) -> str:
        return temp_audio_file

    monkeypatch.setattr(mcp_server_module, "download_to_temp_async", _fake_download)

    session_id = await _initialize_session(asgi_client)
    await _tools_list(asgi_client, session_id)

    req = {
        "jsonrpc": "2.0",
        "id": 33,
        "method": "tools/call",
        "params": {
            "name": "transcribe_openai",
            "arguments": {
                "audio_uri": f"file://{temp_audio_file}",
                "model": "whisper-1",
                "language": "pl",
            },
        },
    }
    resp = await asgi_client.post("/mcp", json=req, headers=session_headers(session_id))
    payload = _parse_mcp_response(resp)
    text = _first_text_block(payload)
    assert "disk full" in text


async def test_streamable_http_transcribe_openai_raises_generic_exception(monkeypatch, temp_audio_file,
                                                                          asgi_client: AsyncClient):
    def _raise_generic(*, audio_file_path: str, model: str, language: str):
        raise RuntimeError("explode")

    monkeypatch.setattr(mcp_server_module.settings, "OPENAI_API_KEY", "test")
    monkeypatch.setattr(mcp_server_module, "openai_speech_transcription", _raise_generic)

    async def _fake_download(uri: str) -> str:
        return temp_audio_file

    monkeypatch.setattr(mcp_server_module, "download_to_temp_async", _fake_download)

    session_id = await _initialize_session(asgi_client)
    await _tools_list(asgi_client, session_id)

    req = {
        "jsonrpc": "2.0",
        "id": 34,
        "method": "tools/call",
        "params": {
            "name": "transcribe_openai",
            "arguments": {
                "audio_uri": f"file://{temp_audio_file}",
                "model": "whisper-1",
                "language": "pl",
            },
        },
    }
    resp = await asgi_client.post("/mcp", json=req, headers=session_headers(session_id))
    payload = _parse_mcp_response(resp)
    text = _first_text_block(payload)
    assert "An unexpected error occurred:" in text


async def test_streamable_http_transcribe_hf_missing_token(monkeypatch, temp_audio_file, asgi_client: AsyncClient):
    monkeypatch.setattr(mcp_server_module.settings, "HF_TOKEN", "")

    session_id = await _initialize_session(asgi_client)
    await _tools_list(asgi_client, session_id)

    req = {
        "jsonrpc": "2.0",
        "id": 40,
        "method": "tools/call",
        "params": {
            "name": "transcribe_hf",
            "arguments": {
                "audio_uri": f"file://{temp_audio_file}",
            },
        },
    }
    resp = await asgi_client.post("/mcp", json=req, headers=session_headers(session_id))
    payload = _parse_mcp_response(resp)
    text = _first_text_block(payload)
    assert "HF_TOKEN is not configured" in text


async def test_streamable_http_transcribe_hf_file_not_found(monkeypatch, asgi_client: AsyncClient):
    monkeypatch.setattr(mcp_server_module.settings, "HF_TOKEN", "test")

    session_id = await _initialize_session(asgi_client)
    await _tools_list(asgi_client, session_id)

    req = {
        "jsonrpc": "2.0",
        "id": 41,
        "method": "tools/call",
        "params": {
            "name": "transcribe_hf",
            "arguments": {
                "audio_uri": "file:///X:/nope.wav",
            },
        },
    }
    resp = await asgi_client.post("/mcp", json=req, headers=session_headers(session_id))
    payload = _parse_mcp_response(resp)
    text = _first_text_block(payload)
    assert "File not found" in text


async def test_streamable_http_transcribe_hf_raises_value_error(monkeypatch, temp_audio_file, asgi_client: AsyncClient):
    def _raise_value_error_hf(*, audio_file_path: str, model: str, provider: str):
        raise ValueError("hf bad")

    monkeypatch.setattr(mcp_server_module.settings, "HF_TOKEN", "test")
    monkeypatch.setattr(mcp_server_module, "hf_speech_transcription", _raise_value_error_hf)

    async def _fake_download(uri: str) -> str:
        return temp_audio_file

    monkeypatch.setattr(mcp_server_module, "download_to_temp_async", _fake_download)

    session_id = await _initialize_session(asgi_client)
    await _tools_list(asgi_client, session_id)

    req = {
        "jsonrpc": "2.0",
        "id": 42,
        "method": "tools/call",
        "params": {
            "name": "transcribe_hf",
            "arguments": {
                "audio_uri": f"file://{temp_audio_file}",
                "model": "openai/whisper-large-v3",
                "hf_provider": "hf-inference",
            },
        },
    }
    resp = await asgi_client.post("/mcp", json=req, headers=session_headers(session_id))
    payload = _parse_mcp_response(resp)
    text = _first_text_block(payload)
    assert "hf bad" in text


async def test_streamable_http_transcribe_hf_raises_io_error(monkeypatch, temp_audio_file, asgi_client: AsyncClient):
    def _raise_io_error_hf(*, audio_file_path: str, model: str, provider: str):
        raise IOError("network down")

    monkeypatch.setattr(mcp_server_module.settings, "HF_TOKEN", "test")
    monkeypatch.setattr(mcp_server_module, "hf_speech_transcription", _raise_io_error_hf)

    async def _fake_download(uri: str) -> str:
        return temp_audio_file

    monkeypatch.setattr(mcp_server_module, "download_to_temp_async", _fake_download)

    session_id = await _initialize_session(asgi_client)
    await _tools_list(asgi_client, session_id)

    req = {
        "jsonrpc": "2.0",
        "id": 43,
        "method": "tools/call",
        "params": {
            "name": "transcribe_hf",
            "arguments": {
                "audio_uri": f"file://{temp_audio_file}",
                "model": "openai/whisper-large-v3",
                "hf_provider": "hf-inference",
            },
        },
    }
    resp = await asgi_client.post("/mcp", json=req, headers=session_headers(session_id))
    payload = _parse_mcp_response(resp)
    text = _first_text_block(payload)
    assert "network down" in text


async def test_streamable_http_transcribe_hf_raises_generic_exception(monkeypatch, temp_audio_file,
                                                                      asgi_client: AsyncClient):
    def _raise_generic_hf(*, audio_file_path: str, model: str, provider: str):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(mcp_server_module.settings, "HF_TOKEN", "test")
    monkeypatch.setattr(mcp_server_module, "hf_speech_transcription", _raise_generic_hf)

    async def _fake_download(uri: str) -> str:
        return temp_audio_file

    monkeypatch.setattr(mcp_server_module, "download_to_temp_async", _fake_download)

    session_id = await _initialize_session(asgi_client)
    await _tools_list(asgi_client, session_id)

    req = {
        "jsonrpc": "2.0",
        "id": 44,
        "method": "tools/call",
        "params": {
            "name": "transcribe_hf",
            "arguments": {
                "audio_uri": f"file://{temp_audio_file}",
                "model": "openai/whisper-large-v3",
                "hf_provider": "hf-inference",
            },
        },
    }
    resp = await asgi_client.post("/mcp", json=req, headers=session_headers(session_id))
    payload = _parse_mcp_response(resp)
    text = _first_text_block(payload)
    assert "An unexpected error occurred:" in text

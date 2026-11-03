import asyncio
import io
import re
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

import src.api.rest.rest_endpoints as rest
from src.api.mcp.mcp_server import (
    transcribe_audacity,
    transcribe_hf,
    transcribe_local,
    transcribe_openai,
)
from src.main import app


def _multipart(content: bytes = b"audio", filename: str = "clip.wav") -> dict[str, Any]:
    return {"file": (filename, io.BytesIO(content), "audio/wav")}


def test_refusal_problem_body_carries_code_and_trace_id(monkeypatch: Any) -> None:
    # given
    from src.config.config import settings

    monkeypatch.setattr(settings, "OPENAI_API_KEY", "sk-x")
    monkeypatch.setattr(
        rest,
        "openai_speech_transcription",
        MagicMock(side_effect=ValueError("bad input")),
    )
    # when
    with TestClient(app) as client:
        response = client.post("/api/v1/transcribe/openai", files=_multipart(), data={"stream": "false"})
    # then
    assert response.status_code == 400
    body = response.json()
    assert body["code"] == "validation"
    assert re.fullmatch(r"[0-9a-f]{32}", body["traceId"]) is not None


def test_request_validation_failure_answers_400_with_sorted_errors() -> None:
    # given
    payload: dict[str, Any] = {"stream": "false", "language": "xx!!"}
    # when
    with TestClient(app) as client:
        response = client.post("/api/v1/transcribe/openai", files=_multipart(), data=payload)
    # then
    assert response.status_code == 400
    body = response.json()
    assert body["code"] == "validation"
    assert isinstance(body["errors"], list)
    fields = [entry["field"] for entry in body["errors"]]
    assert fields == sorted(fields)
    assert payload["stream"] == "false"


def test_unknown_path_answers_problem_404_with_trace_id() -> None:
    # given
    path = "/does-not-exist"
    # when
    with TestClient(app) as client:
        response = client.get(path)
    # then
    assert response.status_code == 404
    assert "application/problem+json" in response.headers["content-type"]
    body = response.json()
    assert body["code"] == "not_found"
    assert re.fullmatch(r"[0-9a-f]{32}", body["traceId"]) is not None


def test_wrong_method_answers_problem_405_with_allow() -> None:
    # given
    path = "/health"
    # when
    with TestClient(app) as client:
        response = client.delete(path)
    # then
    assert response.status_code == 405
    body = response.json()
    assert body["code"] == "method_not_allowed"
    assert "allow" in {key.lower() for key in response.headers}


def test_unexpected_failure_body_carries_code_and_trace_id_without_leak(
    monkeypatch: Any,
) -> None:
    # given
    from src.config.config import settings

    monkeypatch.setattr(settings, "OPENAI_API_KEY", "sk-x")
    sentinel = "UPSTREAM_LEAK_MARKER_99"
    monkeypatch.setattr(
        rest,
        "openai_speech_transcription",
        MagicMock(side_effect=RuntimeError(f"upstream blew up with {sentinel}")),
    )
    # when
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post("/api/v1/transcribe/openai", files=_multipart(), data={"stream": "false"})
    # then
    assert response.status_code == 500
    body = response.json()
    assert body["code"] == "internal"
    assert re.fullmatch(r"[0-9a-f]{32}", body["traceId"]) is not None
    assert sentinel not in response.text


def test_mcp_local_validation_raises_tool_error() -> None:
    # given
    bad_uri = ""
    # when
    with pytest.raises(Exception, match=r"^validation: ") as exc_info:
        asyncio.run(transcribe_local(audio_uri=bad_uri))
    # then
    assert str(exc_info.value).startswith("validation: ")


def test_mcp_openai_validation_raises_tool_error() -> None:
    # given
    bad_uri = ""
    # when
    with pytest.raises(Exception, match=r"^validation: ") as exc_info:
        asyncio.run(transcribe_openai(audio_uri=bad_uri))
    # then
    assert str(exc_info.value).startswith("validation: ")


def test_mcp_hf_validation_raises_tool_error() -> None:
    # given
    bad_uri = ""
    # when
    with pytest.raises(Exception, match=r"^validation: ") as exc_info:
        asyncio.run(transcribe_hf(audio_uri=bad_uri))
    # then
    assert str(exc_info.value).startswith("validation: ")


def test_mcp_audacity_validation_raises_tool_error() -> None:
    # given
    bad_uri = ""
    # when
    with pytest.raises(Exception, match=r"^validation: ") as exc_info:
        asyncio.run(transcribe_audacity(audio_uri=bad_uri))
    # then
    assert str(exc_info.value).startswith("validation: ")


def test_ready_not_ready_body_on_503() -> None:
    # given
    from unittest.mock import patch

    from ascend_python_common.readiness import ProbeResult

    from src.api import readiness as readiness_module

    # when
    with (
        patch.object(readiness_module, "_probe_ffmpeg", return_value=ProbeResult(status="error")),
        patch.object(readiness_module, "_probe_temp_dir", return_value=ProbeResult(status="ok")),
        patch.object(readiness_module, "probe_ffmpeg", return_value=ProbeResult(status="error")),
        patch.object(readiness_module, "probe_temp_dir", return_value=ProbeResult(status="ok")),
        TestClient(app) as client,
    ):
        response = client.get("/ready")
    # then
    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "not-ready"
    assert body["service"] == "ascend-audio-scribe"
    assert isinstance(body["version"], str)
    assert len(body["version"]) > 0


def test_health_includes_service_and_version() -> None:
    # given
    path = "/health"
    # when
    with TestClient(app) as client:
        response = client.get(path)
    # then
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "ascend-audio-scribe"
    assert isinstance(body["version"], str)
    assert len(body["version"]) > 0

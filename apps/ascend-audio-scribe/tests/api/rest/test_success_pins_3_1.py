from __future__ import annotations

import io
from typing import Any
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

import src.api.rest.rest_endpoints as rest
from src.main import app


def _multipart(content: bytes = b"audio", filename: str = "clip.wav") -> dict[str, Any]:
    return {"file": (filename, io.BytesIO(content), "audio/wav")}


class _AsyncIterOver:
    def __init__(self, items: list[Any]) -> None:
        self._iter = iter(items)

    def __call__(self, *_args: Any, **_kwargs: Any) -> _AsyncIterOver:
        return self

    def __aiter__(self) -> _AsyncIterOver:
        return self

    async def __anext__(self) -> Any:
        try:
            return next(self._iter)
        except StopIteration as exc:
            raise StopAsyncIteration from exc


def test_local_file_download_pins_today_body(monkeypatch: Any) -> None:
    # given
    monkeypatch.setattr(
        rest,
        "local_speech_transcription",
        _AsyncIterOver([{"text": "hi", "start": 0.0, "end": 1.0}]),
    )
    # when
    with TestClient(app) as client:
        response = client.post("/api/v1/transcribe/local", files=_multipart(), data={"stream": "false"})
    # then
    assert response.status_code == 200
    assert "hi" in response.text


def test_openai_sse_pins_today_stream(monkeypatch: Any) -> None:
    # given
    from src.config.config import settings

    monkeypatch.setattr(settings, "OPENAI_API_KEY", "sk-x")

    def call_with_callback(*_a: Any, **kw: Any) -> str:
        cb = kw.get("progress_callback")
        if cb:
            cb({"type": "progress", "message": "hi"})
        return "done"

    monkeypatch.setattr(rest, "openai_speech_transcription", MagicMock(side_effect=call_with_callback))
    # when
    with TestClient(app) as client:
        with client.stream(
            "POST",
            "/api/v1/transcribe/openai",
            files=_multipart(),
            data={"stream": "true"},
        ) as response:
            body = response.read().decode()
    # then
    assert "data:" in body
    assert "complete" in body


def test_audacity_file_download_pins_today_body(monkeypatch: Any) -> None:
    # given
    async def fake_merge(*_a: Any, **_k: Any) -> str:
        return "merged text"

    monkeypatch.setattr(rest, "extract_tracks_from_aup", MagicMock(return_value={"s1": "/tmp/x.wav"}))
    monkeypatch.setattr(rest, "transcribe_and_merge_tracks", fake_merge)
    # when
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/transcribe/audacity",
            files=_multipart(filename="project.zip"),
            data={"stream": "false", "provider": "local"},
        )
    # then
    assert response.status_code == 200
    assert "merged text" in response.text


def test_download_route_pins_today_file() -> None:
    # given
    from src.adapters.download_file_manager import store_transcript

    file_id, _ = store_transcript("pin-body", "pin_check.md")
    # when
    with TestClient(app) as client:
        response = client.get(f"/api/v1/transcribe/download/{file_id}")
    # then
    assert response.status_code == 200
    assert "pin-body" in response.text

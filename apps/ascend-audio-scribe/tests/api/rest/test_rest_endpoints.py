"""REST endpoint integration tests via FastAPI TestClient.

We patch out every heavy upstream (scribe.* functions, audacity_parser,
conversation_merger) and the transcript registry so the full HTTP pipeline
(middleware, RFC 7807 handlers, SSE generators, file-response wiring) runs
end-to-end with predictable bodies.

Async generators that should raise on first `__anext__` are built as
classes implementing the async-iterator protocol — that lets the test
express "yields nothing, raises immediately" without a stylistically
unreachable `yield` after `raise`.
"""

from __future__ import annotations

import io
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from src.main import app

if TYPE_CHECKING:
    from pathlib import Path


def _multipart(content: bytes = b"audio", filename: str = "clip.wav") -> dict[str, Any]:
    return {"file": (filename, io.BytesIO(content), "audio/wav")}


@pytest.fixture
def client() -> TestClient:
    return TestClient(app, raise_server_exceptions=False)


class _AsyncIterOver:
    """Async iterator yielding from a pre-built list. Used in place of a
    `async def gen(): for x in items: yield x` helper to avoid the
    async-without-await stylistic complaint on the wrapper."""

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


class _AsyncIterRaises:
    """Async iterator that raises on the first `__anext__`. The RFC 7807
    handler / SSE error path treats this as a fatal stream error. Using a
    class-based iterator avoids `async def fn(): raise; yield` (where the
    `yield` is statically unreachable)."""

    def __init__(self, exc: Exception) -> None:
        self._exc = exc

    def __call__(self, *_args: Any, **_kwargs: Any) -> _AsyncIterRaises:
        return self

    def __aiter__(self) -> _AsyncIterRaises:
        return self

    async def __anext__(self) -> Any:
        raise self._exc


# --- /local ---------------------------------------------------------------


def test_resolve_language_helper_returns_provided_value() -> None:
    import src.api.rest.rest_endpoints as rest

    assert rest._resolve_language("pl") == "pl"


def test_resolve_language_helper_falls_back_on_none() -> None:
    import src.api.rest.rest_endpoints as rest

    assert rest._resolve_language(None) == rest.settings.TRANSCRIPTION_LANGUAGE


def test_resolve_language_helper_falls_back_on_empty() -> None:
    import src.api.rest.rest_endpoints as rest

    assert rest._resolve_language("") == rest.settings.TRANSCRIPTION_LANGUAGE


def test_local_endpoint_success(monkeypatch: pytest.MonkeyPatch, client: TestClient) -> None:
    import src.api.rest.rest_endpoints as rest

    monkeypatch.setattr(
        rest,
        "local_speech_transcription",
        _AsyncIterOver([{"text": "hi", "start": 0.0, "end": 1.0}]),
    )
    response = client.post("/api/v1/transcribe/local", files=_multipart(), data={"stream": "false"})
    assert response.status_code == 200
    assert "hi" in response.text


def test_local_endpoint_with_timestamps(monkeypatch: pytest.MonkeyPatch, client: TestClient) -> None:
    import src.api.rest.rest_endpoints as rest

    monkeypatch.setattr(
        rest,
        "local_speech_transcription",
        _AsyncIterOver([{"text": "ts", "start": 0.0, "end": 0.5}]),
    )
    response = client.post(
        "/api/v1/transcribe/local",
        files=_multipart(),
        data={"stream": "false", "with_timestamps": "true"},
    )
    assert response.status_code == 200
    assert "[0.00 - 0.50]" in response.text


def test_local_endpoint_stream(monkeypatch: pytest.MonkeyPatch, client: TestClient) -> None:
    import src.api.rest.rest_endpoints as rest

    monkeypatch.setattr(
        rest,
        "local_speech_transcription",
        _AsyncIterOver([{"text": "x", "start": 0.0, "end": 1.0}]),
    )
    with client.stream(
        "POST", "/api/v1/transcribe/local", files=_multipart(), data={"stream": "true"}
    ) as response:
        body = response.read().decode()
    assert "data:" in body
    assert "complete" in body


def test_local_endpoint_stream_error(monkeypatch: pytest.MonkeyPatch, client: TestClient) -> None:
    import src.api.rest.rest_endpoints as rest

    monkeypatch.setattr(rest, "local_speech_transcription", _AsyncIterRaises(RuntimeError("boom")))
    with client.stream(
        "POST", "/api/v1/transcribe/local", files=_multipart(), data={"stream": "true"}
    ) as response:
        body = response.read().decode()
    assert "error" in body


def test_local_endpoint_error_path(monkeypatch: pytest.MonkeyPatch, client: TestClient) -> None:
    import src.api.rest.rest_endpoints as rest

    monkeypatch.setattr(rest, "local_speech_transcription", _AsyncIterRaises(RuntimeError("boom")))
    response = client.post("/api/v1/transcribe/local", files=_multipart(), data={"stream": "false"})
    assert response.status_code == 500
    body = response.json()
    assert body["type"].endswith("/internal")


# --- /openai --------------------------------------------------------------


def test_openai_endpoint_missing_key(monkeypatch: pytest.MonkeyPatch, client: TestClient) -> None:
    import src.api.rest.rest_endpoints as rest

    monkeypatch.setattr(rest.settings, "OPENAI_API_KEY", None)
    response = client.post("/api/v1/transcribe/openai", files=_multipart(), data={"stream": "false"})
    assert response.status_code == 400
    assert response.json()["type"].endswith("/validation")


def test_openai_endpoint_success(monkeypatch: pytest.MonkeyPatch, client: TestClient) -> None:
    import src.api.rest.rest_endpoints as rest

    monkeypatch.setattr(rest.settings, "OPENAI_API_KEY", "sk-x")
    monkeypatch.setattr(rest, "openai_speech_transcription", MagicMock(return_value="transcript text"))
    response = client.post("/api/v1/transcribe/openai", files=_multipart(), data={"stream": "false"})
    assert response.status_code == 200
    assert "transcript text" in response.text


def test_openai_endpoint_dict_response(monkeypatch: pytest.MonkeyPatch, client: TestClient) -> None:
    import src.api.rest.rest_endpoints as rest

    monkeypatch.setattr(rest.settings, "OPENAI_API_KEY", "sk-x")
    monkeypatch.setattr(
        rest,
        "openai_speech_transcription",
        MagicMock(return_value=[{"text": "x", "start": 0.0, "end": 1.0}]),
    )
    response = client.post("/api/v1/transcribe/openai", files=_multipart(), data={"stream": "false"})
    assert response.status_code == 200


def test_openai_endpoint_stream(monkeypatch: pytest.MonkeyPatch, client: TestClient) -> None:
    import src.api.rest.rest_endpoints as rest

    monkeypatch.setattr(rest.settings, "OPENAI_API_KEY", "sk-x")

    def call_with_callback(*_a: Any, **kw: Any) -> str:
        cb = kw.get("progress_callback")
        if cb:
            cb({"type": "progress", "message": "hi"})
        return "done"

    monkeypatch.setattr(rest, "openai_speech_transcription", MagicMock(side_effect=call_with_callback))
    with client.stream(
        "POST", "/api/v1/transcribe/openai", files=_multipart(), data={"stream": "true"}
    ) as response:
        body = response.read().decode()
    assert "complete" in body


def test_openai_endpoint_stream_error(monkeypatch: pytest.MonkeyPatch, client: TestClient) -> None:
    import src.api.rest.rest_endpoints as rest

    monkeypatch.setattr(rest.settings, "OPENAI_API_KEY", "sk-x")
    monkeypatch.setattr(rest, "openai_speech_transcription", MagicMock(side_effect=RuntimeError("boom")))
    with client.stream(
        "POST", "/api/v1/transcribe/openai", files=_multipart(), data={"stream": "true"}
    ) as response:
        body = response.read().decode()
    assert "error" in body


def test_openai_endpoint_error_path(monkeypatch: pytest.MonkeyPatch, client: TestClient) -> None:
    import src.api.rest.rest_endpoints as rest

    monkeypatch.setattr(rest.settings, "OPENAI_API_KEY", "sk-x")
    monkeypatch.setattr(
        rest, "openai_speech_transcription", MagicMock(side_effect=ValueError("bad input"))
    )
    response = client.post("/api/v1/transcribe/openai", files=_multipart(), data={"stream": "false"})
    assert response.status_code == 400


# --- /hf -----------------------------------------------------------------


def test_hf_endpoint_missing_token(monkeypatch: pytest.MonkeyPatch, client: TestClient) -> None:
    import src.api.rest.rest_endpoints as rest

    monkeypatch.setattr(rest.settings, "HF_TOKEN", None)
    response = client.post("/api/v1/transcribe/hf", files=_multipart(), data={"stream": "false"})
    assert response.status_code == 400


def test_hf_endpoint_success(monkeypatch: pytest.MonkeyPatch, client: TestClient) -> None:
    import src.api.rest.rest_endpoints as rest

    monkeypatch.setattr(rest.settings, "HF_TOKEN", "tok")
    monkeypatch.setattr(rest, "hf_speech_transcription", MagicMock(return_value="hf-result"))
    response = client.post("/api/v1/transcribe/hf", files=_multipart(), data={"stream": "false"})
    assert response.status_code == 200


def test_hf_endpoint_dict_response(monkeypatch: pytest.MonkeyPatch, client: TestClient) -> None:
    import src.api.rest.rest_endpoints as rest

    monkeypatch.setattr(rest.settings, "HF_TOKEN", "tok")
    monkeypatch.setattr(rest, "hf_speech_transcription", MagicMock(return_value=[{"text": "x"}]))
    response = client.post("/api/v1/transcribe/hf", files=_multipart(), data={"stream": "false"})
    assert response.status_code == 200


def test_hf_endpoint_stream(monkeypatch: pytest.MonkeyPatch, client: TestClient) -> None:
    import src.api.rest.rest_endpoints as rest

    monkeypatch.setattr(rest.settings, "HF_TOKEN", "tok")

    def cb_call(*_a: Any, **kw: Any) -> str:
        cb = kw.get("progress_callback")
        if cb:
            cb({"type": "progress", "message": "ok"})
        return "done"

    monkeypatch.setattr(rest, "hf_speech_transcription", MagicMock(side_effect=cb_call))
    with client.stream(
        "POST", "/api/v1/transcribe/hf", files=_multipart(), data={"stream": "true"}
    ) as response:
        body = response.read().decode()
    assert "complete" in body


def test_hf_endpoint_stream_error(monkeypatch: pytest.MonkeyPatch, client: TestClient) -> None:
    import src.api.rest.rest_endpoints as rest

    monkeypatch.setattr(rest.settings, "HF_TOKEN", "tok")
    monkeypatch.setattr(rest, "hf_speech_transcription", MagicMock(side_effect=RuntimeError("boom")))
    with client.stream(
        "POST", "/api/v1/transcribe/hf", files=_multipart(), data={"stream": "true"}
    ) as response:
        body = response.read().decode()
    assert "error" in body


def test_hf_endpoint_error_path(monkeypatch: pytest.MonkeyPatch, client: TestClient) -> None:
    import src.api.rest.rest_endpoints as rest

    monkeypatch.setattr(rest.settings, "HF_TOKEN", "tok")
    monkeypatch.setattr(rest, "hf_speech_transcription", MagicMock(side_effect=RuntimeError("boom")))
    response = client.post("/api/v1/transcribe/hf", files=_multipart(), data={"stream": "false"})
    assert response.status_code == 500


# --- /audacity -----------------------------------------------------------


def test_audacity_rejects_non_zip(client: TestClient) -> None:
    response = client.post(
        "/api/v1/transcribe/audacity",
        files=_multipart(filename="x.wav"),
        data={"stream": "false"},
    )
    assert response.status_code == 400


async def _ok_merge(**_kw: Any) -> str:
    import asyncio as _aio
    await _aio.sleep(0)
    return "[00:00:00] [speaker] hi"


def test_audacity_success(monkeypatch: pytest.MonkeyPatch, client: TestClient) -> None:
    import src.api.rest.rest_endpoints as rest

    monkeypatch.setattr(rest, "extract_tracks_from_aup", MagicMock(return_value={"speaker": "/tmp/x.wav"}))
    monkeypatch.setattr(rest, "transcribe_and_merge_tracks", _ok_merge)
    response = client.post(
        "/api/v1/transcribe/audacity",
        files=_multipart(filename="proj.zip"),
        data={"stream": "false", "provider": "local"},
    )
    assert response.status_code == 200


def test_audacity_no_tracks(monkeypatch: pytest.MonkeyPatch, client: TestClient) -> None:
    import src.api.rest.rest_endpoints as rest

    monkeypatch.setattr(rest, "extract_tracks_from_aup", MagicMock(return_value={}))
    response = client.post(
        "/api/v1/transcribe/audacity",
        files=_multipart(filename="proj.zip"),
        data={"stream": "false", "provider": "local"},
    )
    assert response.status_code == 400


async def _progress_then_done(**kw: Any) -> str:
    import asyncio as _aio
    cb = kw.get("progress_callback")
    if cb:
        cb({"type": "progress", "message": "ok"})
    await _aio.sleep(0)
    return "out"


def test_audacity_stream(monkeypatch: pytest.MonkeyPatch, client: TestClient) -> None:
    import src.api.rest.rest_endpoints as rest

    monkeypatch.setattr(rest, "extract_tracks_from_aup", MagicMock(return_value={"sp": "/tmp/x.wav"}))
    monkeypatch.setattr(rest, "transcribe_and_merge_tracks", _progress_then_done)
    with client.stream(
        "POST",
        "/api/v1/transcribe/audacity",
        files=_multipart(filename="proj.zip"),
        data={"stream": "true", "provider": "local"},
    ) as response:
        body = response.read().decode()
    assert "complete" in body


def test_audacity_stream_no_tracks(monkeypatch: pytest.MonkeyPatch, client: TestClient) -> None:
    import src.api.rest.rest_endpoints as rest

    monkeypatch.setattr(rest, "extract_tracks_from_aup", MagicMock(return_value={}))
    with client.stream(
        "POST",
        "/api/v1/transcribe/audacity",
        files=_multipart(filename="proj.zip"),
        data={"stream": "true", "provider": "local"},
    ) as response:
        body = response.read().decode()
    assert "error" in body


def test_audacity_stream_error(monkeypatch: pytest.MonkeyPatch, client: TestClient) -> None:
    import src.api.rest.rest_endpoints as rest

    monkeypatch.setattr(rest, "extract_tracks_from_aup", MagicMock(side_effect=RuntimeError("boom")))
    with client.stream(
        "POST",
        "/api/v1/transcribe/audacity",
        files=_multipart(filename="proj.zip"),
        data={"stream": "true", "provider": "local"},
    ) as response:
        body = response.read().decode()
    assert "error" in body


def test_audacity_endpoint_error_path(monkeypatch: pytest.MonkeyPatch, client: TestClient) -> None:
    import src.api.rest.rest_endpoints as rest

    monkeypatch.setattr(rest, "extract_tracks_from_aup", MagicMock(side_effect=RuntimeError("boom")))
    response = client.post(
        "/api/v1/transcribe/audacity",
        files=_multipart(filename="proj.zip"),
        data={"stream": "false", "provider": "local"},
    )
    assert response.status_code == 500


# --- /download/{file_id} -------------------------------------------------


def test_download_transcript_404(client: TestClient) -> None:
    response = client.get("/api/v1/transcribe/download/missing")
    assert response.status_code == 404


def test_download_transcript_success(
    monkeypatch: pytest.MonkeyPatch, client: TestClient, tmp_path: Path
) -> None:
    import src.api.rest.rest_endpoints as rest

    transcript_file = tmp_path / "out.md"
    transcript_file.write_text("body", encoding="utf-8")
    monkeypatch.setattr(rest, "get_transcript_path", MagicMock(return_value=str(transcript_file)))
    monkeypatch.setattr(rest, "cleanup_expired", MagicMock())
    response = client.get("/api/v1/transcribe/download/abc")
    assert response.status_code == 200
    assert response.text == "body"


# Tail-drain branches in each SSE stream: progress arrives between the
# wait_for timeout and the `task.done()` check; the post-loop drain must
# flush it.


def test_openai_stream_drains_queue_tail(monkeypatch: pytest.MonkeyPatch, client: TestClient) -> None:
    import src.api.rest.rest_endpoints as rest

    monkeypatch.setattr(rest.settings, "OPENAI_API_KEY", "sk-x")

    def call_with_late_event(*_a: Any, **kw: Any) -> str:
        cb = kw.get("progress_callback")
        if cb:
            cb({"type": "progress", "message": "first"})
            cb({"type": "progress", "message": "tail"})
        return "done"

    monkeypatch.setattr(rest, "openai_speech_transcription", MagicMock(side_effect=call_with_late_event))
    with client.stream(
        "POST", "/api/v1/transcribe/openai", files=_multipart(), data={"stream": "true"}
    ) as response:
        body = response.read().decode()
    assert "tail" in body


def test_hf_stream_drains_queue_tail(monkeypatch: pytest.MonkeyPatch, client: TestClient) -> None:
    import src.api.rest.rest_endpoints as rest

    monkeypatch.setattr(rest.settings, "HF_TOKEN", "tok")

    def call_with_late(*_a: Any, **kw: Any) -> str:
        cb = kw.get("progress_callback")
        if cb:
            cb({"type": "progress", "message": "first"})
            cb({"type": "progress", "message": "tail"})
        return "done"

    monkeypatch.setattr(rest, "hf_speech_transcription", MagicMock(side_effect=call_with_late))
    with client.stream(
        "POST", "/api/v1/transcribe/hf", files=_multipart(), data={"stream": "true"}
    ) as response:
        body = response.read().decode()
    assert "tail" in body


async def _two_progress_then_done(**kw: Any) -> str:
    import asyncio as _aio
    cb = kw.get("progress_callback")
    if cb:
        cb({"type": "progress", "message": "first"})
        cb({"type": "progress", "message": "tail"})
    await _aio.sleep(0)
    return "out"


def test_audacity_stream_drains_queue_tail(monkeypatch: pytest.MonkeyPatch, client: TestClient) -> None:
    import src.api.rest.rest_endpoints as rest

    monkeypatch.setattr(rest, "extract_tracks_from_aup", MagicMock(return_value={"sp": "/tmp/x.wav"}))
    monkeypatch.setattr(rest, "transcribe_and_merge_tracks", _two_progress_then_done)
    with client.stream(
        "POST",
        "/api/v1/transcribe/audacity",
        files=_multipart(filename="proj.zip"),
        data={"stream": "true", "provider": "local"},
    ) as response:
        body = response.read().decode()
    assert "tail" in body


async def _slow_merge(**_kw: Any) -> str:
    import asyncio as aio

    # >0.5s SSE poll timeout — exercises the wait_for TimeoutError continue.
    await aio.sleep(0.7)
    return "out"


def test_audacity_stream_timeout_branch(monkeypatch: pytest.MonkeyPatch, client: TestClient) -> None:
    """When the merge task takes time and the progress queue is empty, the
    wait_for path raises TimeoutError and the `continue` branch fires."""

    import src.api.rest.rest_endpoints as rest

    monkeypatch.setattr(rest, "extract_tracks_from_aup", MagicMock(return_value={"sp": "/tmp/x.wav"}))
    monkeypatch.setattr(rest, "transcribe_and_merge_tracks", _slow_merge)
    with client.stream(
        "POST",
        "/api/v1/transcribe/audacity",
        files=_multipart(filename="proj.zip"),
        data={"stream": "true", "provider": "local"},
    ) as response:
        body = response.read().decode()
    assert "complete" in body


# --- CancelledError handling on SSE streams ------------------------------
#
# Direct-call the generators to exercise the CancelledError branch on the
# SSE poll loop. asyncio.Queue.get raises CancelledError when its task is
# cancelled; we simulate that by patching asyncio.wait_for and asserting
# the generator re-raises after cancelling its background task.


def _assert_generator_propagates_cancel(generator) -> bool:
    """Drive an async generator until CancelledError surfaces from the
    poll loop. Each backend yields a slightly different number of preamble
    SSE events (1 for openai/hf, 2 for audacity) before entering wait_for,
    so we drain up to 8 events looking for the patched CancelledError."""

    import asyncio as aio

    async def drive() -> bool:
        for _ in range(8):
            try:
                await generator.__anext__()
            except aio.CancelledError:
                return True
            except StopAsyncIteration:
                return False
        return False

    loop = aio.new_event_loop()
    try:
        return loop.run_until_complete(drive())
    finally:
        loop.close()


async def _cancelling_wait_for(*_a: object, **_kw: object) -> object:
    """Stub for `asyncio.wait_for` that raises CancelledError synchronously.
    Used to drive the SSE poll loop into its CancelledError branch. The
    `await asyncio.sleep(0)` is a cooperative yield before raising — it
    keeps the function genuinely async without changing observable
    behaviour."""

    import asyncio as aio

    await aio.sleep(0)
    raise aio.CancelledError


def test_openai_stream_propagates_cancellation(monkeypatch: pytest.MonkeyPatch) -> None:
    """When the SSE consumer disconnects, `wait_for` raises CancelledError
    which the generator's `except asyncio.CancelledError` clause must catch
    long enough to cancel the background task, then re-raise."""

    import src.api.rest.rest_endpoints as rest

    monkeypatch.setattr(rest.settings, "OPENAI_API_KEY", "sk-x")
    monkeypatch.setattr(
        rest,
        "openai_speech_transcription",
        MagicMock(side_effect=_blocking_transcription_side_effect()),
    )
    monkeypatch.setattr(rest, "save_upload_to_temp_async", _async_return("/tmp/x.wav"))
    monkeypatch.setattr(rest.asyncio, "wait_for", _cancelling_wait_for)

    upload = MagicMock()
    upload.close = _async_close_noop()
    gen = rest._stream_openai(upload, "whisper-1", "en")
    assert _assert_generator_propagates_cancel(gen)


def test_hf_stream_propagates_cancellation(monkeypatch: pytest.MonkeyPatch) -> None:
    import src.api.rest.rest_endpoints as rest

    monkeypatch.setattr(rest.settings, "HF_TOKEN", "tok")
    monkeypatch.setattr(
        rest,
        "hf_speech_transcription",
        MagicMock(side_effect=_blocking_transcription_side_effect()),
    )
    monkeypatch.setattr(rest, "save_upload_to_temp_async", _async_return("/tmp/x.wav"))
    monkeypatch.setattr(rest.asyncio, "wait_for", _cancelling_wait_for)

    upload = MagicMock()
    upload.close = _async_close_noop()
    gen = rest._stream_hf(upload, "openai/whisper-large-v3", "hf-inference")
    assert _assert_generator_propagates_cancel(gen)


async def _slow_merge_for_cancel(**_kw: object) -> str:
    import asyncio as aio

    await aio.sleep(0.5)
    return "done"


def test_audacity_stream_propagates_cancellation(monkeypatch: pytest.MonkeyPatch) -> None:
    import src.api.rest.rest_endpoints as rest

    monkeypatch.setattr(rest, "extract_tracks_from_aup", MagicMock(return_value={"sp": "/tmp/x.wav"}))
    monkeypatch.setattr(rest, "transcribe_and_merge_tracks", _slow_merge_for_cancel)
    monkeypatch.setattr(rest, "save_upload_to_temp_async", _async_return("/tmp/p.zip"))
    monkeypatch.setattr(rest.asyncio, "wait_for", _cancelling_wait_for)

    upload = MagicMock()
    upload.close = _async_close_noop()
    gen = rest._stream_audacity(upload, "local", "model", "en", "hf-inference")
    assert _assert_generator_propagates_cancel(gen)


def _async_return(value: object) -> object:
    """Build a sync callable that returns a coroutine resolving to `value`.
    Used to patch `await save_upload_to_temp_async(...)` call sites without
    introducing an `async def` test helper that has no `await` of its own."""

    async def _inner(*_a: object, **_kw: object) -> object:
        import asyncio as aio

        await aio.sleep(0)  # cooperative yield so the surrounding flow remains awaitable
        return value

    return _inner


def _async_close_noop() -> object:
    """Awaitable no-op used to satisfy `await upload.close()` in finally
    blocks."""

    async def _inner() -> None:
        import asyncio as aio

        await aio.sleep(0)

    return _inner


def _blocking_transcription_side_effect() -> object:
    """Sync function used as `MagicMock(side_effect=...)` for the
    transcription stubs. Blocks long enough that the SSE poll loop
    actually reaches `asyncio.wait_for` before the task completes — which
    is what triggers the CancelledError path under test."""

    import time as _time

    def _inner(*_a: object, **_kw: object) -> str:
        _time.sleep(0.5)
        return "done"

    return _inner

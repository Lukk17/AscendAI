from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest

from src.transcription import huggingface_api_speach_to_text as mod


def _make_hf_http_error(message: str) -> mod.HfHubHTTPError:
    """huggingface_hub 1.x requires a real `httpx.Response` on
    `HfHubHTTPError`. Build a minimal one for tests."""

    response = httpx.Response(500, request=httpx.Request("POST", "https://hf.test"))
    return mod.HfHubHTTPError(message, response=response)


@pytest.fixture
def hf_token(monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setenv("HF_TOKEN", "test-token")
    return "test-token"


def test_get_client_caches(monkeypatch: pytest.MonkeyPatch) -> None:
    sentinels = [MagicMock(name="a"), MagicMock(name="b")]
    monkeypatch.setattr(mod, "InferenceClient", MagicMock(side_effect=sentinels))
    first = mod._get_client("hf-inference", "tok")
    second = mod._get_client("hf-inference", "tok")
    assert first is second


def test_transcribe_single_chunk_returns_text() -> None:
    client = MagicMock()
    client.automatic_speech_recognition.return_value = {"text": "hello"}
    assert mod._transcribe_single_chunk(client, "x.wav", "model") == "hello"


def test_transcribe_single_chunk_http_error() -> None:
    client = MagicMock()
    client.automatic_speech_recognition.side_effect = _make_hf_http_error("boom")
    with pytest.raises(ValueError, match="Hugging Face"):
        mod._transcribe_single_chunk(client, "x.wav", "model")


def test_hf_transcript_missing_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HF_TOKEN", raising=False)
    with pytest.raises(ValueError, match="HF_TOKEN"):
        mod.hf_transcript("x.wav", "model", "hf-inference")


class _FakeChunks:
    """Context manager returning a fixed list of chunk paths. Replaces
    `@contextmanager async def fake_chunks(...): yield [...]` to avoid the
    async-without-await + unreachable-yield pair the wrapper triggers."""

    def __init__(self, chunks: list[str]) -> None:
        self._chunks = chunks

    def __call__(self, _audio_path: str, _seconds: int) -> "_FakeChunks":
        return self

    def __enter__(self) -> list[str]:
        return self._chunks

    def __exit__(self, *_exc: Any) -> None:
        return None


class _FakeChunksRaises:
    """Context manager whose __enter__ raises before yielding anything."""

    def __init__(self, exc: Exception) -> None:
        self._exc = exc

    def __call__(self, _audio_path: str, _seconds: int) -> "_FakeChunksRaises":
        return self

    def __enter__(self) -> list[str]:
        raise self._exc

    def __exit__(self, *_exc: Any) -> None:
        return None


def test_hf_transcript_text_path(
    hf_token: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    del hf_token
    client = MagicMock()
    client.automatic_speech_recognition.return_value = {"text": "hi"}
    monkeypatch.setattr(mod, "_get_client", lambda *_a: client)

    chunk = tmp_path / "c.wav"
    chunk.write_bytes(b"x")
    monkeypatch.setattr(mod, "chunked_audio", _FakeChunks([str(chunk)]))
    progress: list[dict[str, Any]] = []
    result = mod.hf_transcript("a.wav", "m", "hf-inference", progress_callback=progress.append)
    assert result == "hi"
    assert progress


def test_hf_transcript_timestamps_path(
    hf_token: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    del hf_token
    client = MagicMock()
    client.automatic_speech_recognition.return_value = {"text": "frag"}
    monkeypatch.setattr(mod, "_get_client", lambda *_a: client)
    chunk = tmp_path / "c.wav"
    chunk.write_bytes(b"x")
    monkeypatch.setattr(mod, "chunked_audio", _FakeChunks([str(chunk), str(chunk)]))
    result = mod.hf_transcript("a.wav", "m", "hf-inference", with_timestamps=True)
    assert isinstance(result, list)
    assert len(result) == 2


def test_hf_transcript_oserror_passthrough(
    hf_token: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    del hf_token
    monkeypatch.setattr(mod, "chunked_audio", _FakeChunksRaises(OSError("ffmpeg crashed")))
    with pytest.raises(OSError, match="ffmpeg crashed"):
        mod.hf_transcript("a.wav", "m", "hf-inference")


def test_hf_transcript_unexpected_error(
    hf_token: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    del hf_token
    monkeypatch.setattr(mod, "chunked_audio", _FakeChunksRaises(RuntimeError("weird")))
    with pytest.raises(RuntimeError, match="unexpected error"):
        mod.hf_transcript("a.wav", "m", "hf-inference")

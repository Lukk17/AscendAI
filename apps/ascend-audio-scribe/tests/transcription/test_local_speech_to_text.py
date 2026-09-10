import sys
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.transcription import local_speech_to_text as mod


class _Segment:
    def __init__(self, text: str, start: float, end: float) -> None:
        self.text = text
        self.start = start
        self.end = end


def test_load_model_caches_and_returns_same_instance(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_torch = MagicMock()
    fake_torch.cuda.is_available.return_value = False
    monkeypatch.setitem(sys.modules, "torch", fake_torch)

    fake_whisper = MagicMock()
    fake_whisper.WhisperModel = MagicMock(return_value=MagicMock(name="model"))
    monkeypatch.setitem(sys.modules, "faster_whisper", fake_whisper)

    first = mod._load_model("path-a")
    second = mod._load_model("path-a")
    assert first is second


def test_load_model_reloads_on_path_change(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_torch = MagicMock()
    fake_torch.cuda.is_available.return_value = True
    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    fake_whisper = MagicMock()
    fake_whisper.WhisperModel = MagicMock(side_effect=[MagicMock(name="a"), MagicMock(name="b")])
    monkeypatch.setitem(sys.modules, "faster_whisper", fake_whisper)

    first = mod._load_model("path-a")
    second = mod._load_model("path-b")
    assert first is not second


def test_transcribe_chunk_sync_returns_offset_segments(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_model = MagicMock()
    fake_model.transcribe.return_value = (
        [_Segment("hello", 0.0, 1.0), _Segment("world", 1.0, 2.0)],
        MagicMock(),
    )
    monkeypatch.setattr(mod, "_load_model", lambda _path: fake_model)
    out = mod._transcribe_chunk_sync("model", "chunk.wav", "en", time_offset_s=10.0)
    assert out == [
        {"text": "hello", "start": 10.0, "end": 11.0},
        {"text": "world", "start": 11.0, "end": 12.0},
    ]


class _FakeChunks:
    """Context manager yielding pre-defined chunk paths. Replaces the
    ad-hoc `@contextmanager` wrapper to keep the test surface tight."""

    def __init__(self, chunks: list[str]) -> None:
        self._chunks = chunks

    def __call__(self, _audio_path: str, _seconds: int) -> "_FakeChunks":
        return self

    def __enter__(self) -> list[str]:
        return self._chunks

    def __exit__(self, *_exc: Any) -> None:
        return None


@pytest.mark.asyncio
async def test_local_speech_transcription_stream_yields_segments(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mod, "chunked_audio", _FakeChunks(["chunk0.wav", "chunk1.wav"]))
    monkeypatch.setattr(
        mod.asyncio,
        "to_thread",
        AsyncMock(return_value=[{"text": "hi", "start": 0.0, "end": 1.0}]),
    )

    results = [seg async for seg in mod.local_speech_transcription_stream("m", "a.wav", "en")]
    assert len(results) == 2
    assert results[0]["text"] == "hi"

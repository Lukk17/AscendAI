from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from openai import APIError

from src.transcription import openai_api_speach_to_text as mod


@pytest.fixture
def fake_openai_client() -> MagicMock:
    client = MagicMock()
    mod._client_instance = client
    return client


class _FakeChunks:
    """Context manager returning fixed chunk paths. Replaces the
    `@contextmanager` wrapper to avoid an async-without-await complaint
    on the helper function."""

    def __init__(self, chunks: list[str]) -> None:
        self._chunks = chunks

    def __call__(self, _audio_path: str, _seconds: int) -> "_FakeChunks":
        return self

    def __enter__(self) -> list[str]:
        return self._chunks

    def __exit__(self, *_exc: Any) -> None:
        return None


def test_get_client_lazy_init(monkeypatch: pytest.MonkeyPatch) -> None:
    mod._client_instance = None
    sentinel = MagicMock()
    monkeypatch.setattr(mod, "OpenAI", lambda **_kw: sentinel)
    first = mod._get_client()
    second = mod._get_client()
    assert first is sentinel
    assert first is second


def test_transcribe_single_chunk_without_timestamps(
    fake_openai_client: MagicMock, tmp_path: Path
) -> None:
    chunk = tmp_path / "c.wav"
    chunk.write_bytes(b"x")
    response = MagicMock()
    response.text = "hello"
    fake_openai_client.audio.transcriptions.create.return_value = response

    result = mod._transcribe_single_chunk(str(chunk), "whisper-1", "en", with_timestamps=False)
    assert result == "hello"


def test_transcribe_single_chunk_no_language(
    fake_openai_client: MagicMock, tmp_path: Path
) -> None:
    chunk = tmp_path / "c.wav"
    chunk.write_bytes(b"x")
    fake_openai_client.audio.transcriptions.create.return_value = MagicMock(text="x")
    mod._transcribe_single_chunk(str(chunk), "whisper-1", "", with_timestamps=False)
    kwargs = fake_openai_client.audio.transcriptions.create.call_args.kwargs
    assert "language" not in kwargs


def test_transcribe_single_chunk_with_timestamps(
    fake_openai_client: MagicMock, tmp_path: Path
) -> None:
    chunk = tmp_path / "c.wav"
    chunk.write_bytes(b"x")
    seg = MagicMock(text="hi", start=0.0, end=1.0)
    response = MagicMock(segments=[seg])
    fake_openai_client.audio.transcriptions.create.return_value = response

    result = mod._transcribe_single_chunk(str(chunk), "whisper-1", "en", with_timestamps=True)
    assert isinstance(result, list)
    assert result[0]["text"] == "hi"


def test_transcribe_single_chunk_with_timestamps_none_segments(
    fake_openai_client: MagicMock, tmp_path: Path
) -> None:
    """OpenAI verbose_json can return `segments=None` for an empty audio
    chunk; `_segments_from_response` must early-return `[]` rather than
    iterate None."""

    chunk = tmp_path / "c.wav"
    chunk.write_bytes(b"x")
    response = MagicMock(segments=None)
    fake_openai_client.audio.transcriptions.create.return_value = response

    result = mod._transcribe_single_chunk(str(chunk), "whisper-1", "en", with_timestamps=True)
    assert result == []


def test_transcribe_single_chunk_api_error(
    fake_openai_client: MagicMock, tmp_path: Path
) -> None:
    chunk = tmp_path / "c.wav"
    chunk.write_bytes(b"x")
    api_err = APIError("boom", request=MagicMock(), body=None)
    fake_openai_client.audio.transcriptions.create.side_effect = api_err
    with pytest.raises(ValueError, match="OpenAI API"):
        mod._transcribe_single_chunk(str(chunk), "whisper-1", "en", with_timestamps=False)


def test_openai_transcript_under_limit_uses_direct_call(
    fake_openai_client: MagicMock, tmp_path: Path
) -> None:
    f = tmp_path / "small.wav"
    f.write_bytes(b"x" * 100)
    response = MagicMock(text="direct")
    fake_openai_client.audio.transcriptions.create.return_value = response

    result = mod.openai_transcript(str(f), "whisper-1", "en")
    assert result == "direct"


def test_openai_transcript_with_chunking_text(
    fake_openai_client: MagicMock, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    big = tmp_path / "big.wav"
    big.write_bytes(b"x" * (mod.settings.OPENAI_API_LIMIT_BYTES + 1))

    chunk_a = tmp_path / "a.wav"
    chunk_b = tmp_path / "b.wav"
    chunk_a.write_bytes(b"a")
    chunk_b.write_bytes(b"b")
    monkeypatch.setattr(mod, "chunked_audio", _FakeChunks([str(chunk_a), str(chunk_b)]))

    response_a = MagicMock(text="part1")
    response_b = MagicMock(text="part2")
    fake_openai_client.audio.transcriptions.create.side_effect = [response_a, response_b]

    progress: list[dict[str, Any]] = []
    result = mod.openai_transcript(
        str(big), "whisper-1", "en", progress_callback=progress.append
    )
    assert result == "part1 part2"
    assert progress, "progress callback should have been invoked"


def test_openai_transcript_with_chunking_timestamps(
    fake_openai_client: MagicMock, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    big = tmp_path / "big.wav"
    big.write_bytes(b"x" * (mod.settings.OPENAI_API_LIMIT_BYTES + 1))
    chunk = tmp_path / "c.wav"
    chunk.write_bytes(b"x")
    monkeypatch.setattr(mod, "chunked_audio", _FakeChunks([str(chunk)]))

    seg = MagicMock(text="t0", start=0.0, end=1.0)
    response = MagicMock(segments=[seg])
    fake_openai_client.audio.transcriptions.create.return_value = response

    result = mod.openai_transcript(str(big), "whisper-1", "en", with_timestamps=True)
    assert isinstance(result, list)
    assert result[0]["text"] == "t0"


def test_openai_transcript_chunk_exceeds_limit(
    fake_openai_client: MagicMock, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    del fake_openai_client
    big = tmp_path / "big.wav"
    big.write_bytes(b"x" * (mod.settings.OPENAI_API_LIMIT_BYTES + 1))
    huge_chunk = tmp_path / "huge.wav"
    huge_chunk.write_bytes(b"x" * (mod.settings.OPENAI_API_LIMIT_BYTES + 1))
    monkeypatch.setattr(mod, "chunked_audio", _FakeChunks([str(huge_chunk)]))

    with pytest.raises(ValueError, match="exceeded OpenAI size limit"):
        mod.openai_transcript(str(big), "whisper-1", "en")

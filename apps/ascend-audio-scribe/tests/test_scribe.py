from typing import Any
from unittest.mock import MagicMock

import pytest

from src import scribe


class _AsyncIterOver:
    """Async iterator yielding pre-built items. Replaces `async def
    fake_stream(...): for s in items: yield s` to avoid the async helper
    triggering async-without-await checks."""

    def __init__(self, items: list[Any]) -> None:
        self._iter = iter(items)

    def __call__(self, *_args: Any, **_kwargs: Any) -> "_AsyncIterOver":
        return self

    def __aiter__(self) -> "_AsyncIterOver":
        return self

    async def __anext__(self) -> Any:
        try:
            return next(self._iter)
        except StopIteration as exc:
            raise StopAsyncIteration from exc


def test_openai_speech_transcription_text(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(scribe, "openai_transcript", MagicMock(return_value="hi"))
    result = scribe.openai_speech_transcription("a.wav", "m", "en")
    assert result == "hi"


def test_openai_speech_transcription_segments(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(scribe, "openai_transcript", MagicMock(return_value=[{"text": "x"}]))
    result = scribe.openai_speech_transcription("a.wav", "m", "en", with_timestamps=True)
    assert isinstance(result, list)


def test_hf_speech_transcription_text(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(scribe, "hf_transcript", MagicMock(return_value="h"))
    assert scribe.hf_speech_transcription("a.wav", "m", "hf-inference") == "h"


def test_hf_speech_transcription_segments(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(scribe, "hf_transcript", MagicMock(return_value=[{"text": "h"}]))
    out = scribe.hf_speech_transcription("a.wav", "m", "hf-inference", with_timestamps=True)
    assert isinstance(out, list)


@pytest.mark.asyncio
async def test_local_speech_transcription_yields(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        scribe,
        "local_speech_transcription_stream",
        _AsyncIterOver([{"text": "x"}, {"text": "y"}]),
    )
    segments = [s async for s in scribe.local_speech_transcription("a.wav", "m", "en")]
    assert len(segments) == 2

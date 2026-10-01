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
    # given
    monkeypatch.setattr(scribe, "openai_transcript", MagicMock(return_value="hi"))

    # when
    result = scribe.openai_speech_transcription("a.wav", "m", "en")

    # then
    assert result == "hi"


def test_openai_speech_transcription_segments(monkeypatch: pytest.MonkeyPatch) -> None:
    # given
    monkeypatch.setattr(scribe, "openai_transcript", MagicMock(return_value=[{"text": "x"}]))

    # when
    result = scribe.openai_speech_transcription("a.wav", "m", "en", with_timestamps=True)

    # then
    assert isinstance(result, list)


def test_hf_speech_transcription_text(monkeypatch: pytest.MonkeyPatch) -> None:
    # given
    monkeypatch.setattr(scribe, "hf_transcript", MagicMock(return_value="h"))

    # when / then
    assert scribe.hf_speech_transcription("a.wav", "m", "hf-inference") == "h"


def test_hf_speech_transcription_segments(monkeypatch: pytest.MonkeyPatch) -> None:
    # given
    monkeypatch.setattr(scribe, "hf_transcript", MagicMock(return_value=[{"text": "h"}]))

    # when
    out = scribe.hf_speech_transcription("a.wav", "m", "hf-inference", with_timestamps=True)

    # then
    assert isinstance(out, list)


@pytest.mark.asyncio
async def test_local_speech_transcription_yields(monkeypatch: pytest.MonkeyPatch) -> None:
    # given
    monkeypatch.setattr(
        scribe,
        "local_speech_transcription_stream",
        _AsyncIterOver([{"text": "x"}, {"text": "y"}]),
    )

    # when
    segments = [s async for s in scribe.local_speech_transcription("a.wav", "m", "en")]

    # then
    assert len(segments) == 2

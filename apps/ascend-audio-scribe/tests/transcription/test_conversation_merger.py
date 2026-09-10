from typing import Any
from unittest.mock import AsyncMock

import pytest

from src.transcription import conversation_merger as cm


def test_format_elapsed_time() -> None:
    assert cm.format_elapsed_time(0) == "[00:00:00]"
    assert cm.format_elapsed_time(3661) == "[01:01:01]"
    assert cm.format_elapsed_time(59.4) == "[00:00:59]"


class _AsyncIterOver:
    """Async iterator yielding pre-built items."""

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


@pytest.mark.asyncio
async def test_transcribe_one_track_local(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        cm,
        "local_speech_transcription",
        _AsyncIterOver([
            {"text": "a", "start": 0.0, "end": 1.0},
            {"text": "b", "start": 1.0, "end": 2.0},
        ]),
    )
    progress: list[dict[str, Any]] = []
    segments = await cm._transcribe_one_track(
        track_name="t1",
        track_wav="a.wav",
        track_num=1,
        total_tracks=1,
        provider="local",
        model="m",
        language="en",
        hf_provider="hf-inference",
        progress_callback=progress.append,
    )
    assert len(segments) == 2
    assert all(s["speaker"] == "t1" for s in segments)
    assert progress


@pytest.mark.asyncio
async def test_transcribe_one_track_openai(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        cm.asyncio,
        "to_thread",
        AsyncMock(return_value=[{"text": "a", "start": 0.0, "end": 1.0}]),
    )
    segments = await cm._transcribe_one_track(
        track_name="t",
        track_wav="x.wav",
        track_num=1,
        total_tracks=1,
        provider="openai",
        model="whisper-1",
        language="en",
        hf_provider="hf-inference",
        progress_callback=None,
    )
    assert segments[0]["speaker"] == "t"


@pytest.mark.asyncio
async def test_transcribe_one_track_hf(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        cm.asyncio,
        "to_thread",
        AsyncMock(return_value=[{"text": "h", "start": 0.0, "end": 1.0}]),
    )
    segments = await cm._transcribe_one_track(
        track_name="t",
        track_wav="x.wav",
        track_num=1,
        total_tracks=1,
        provider="huggingface",
        model="m",
        language="en",
        hf_provider="hf-inference",
        progress_callback=None,
    )
    assert segments[0]["speaker"] == "t"


@pytest.mark.asyncio
async def test_transcribe_one_track_unknown_provider() -> None:
    with pytest.raises(ValueError, match="Unknown provider"):
        await cm._transcribe_one_track(
            track_name="t",
            track_wav="x.wav",
            track_num=1,
            total_tracks=1,
            provider="alien",
            model="m",
            language="en",
            hf_provider="hf-inference",
            progress_callback=None,
        )


@pytest.mark.asyncio
async def test_transcribe_one_track_hf_handles_str(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cm.asyncio, "to_thread", AsyncMock(return_value="plain"))
    segments = await cm._transcribe_one_track(
        track_name="t",
        track_wav="x.wav",
        track_num=1,
        total_tracks=1,
        provider="huggingface",
        model="m",
        language="en",
        hf_provider="hf-inference",
        progress_callback=None,
    )
    assert segments == []


@pytest.mark.asyncio
async def test_transcribe_one_track_openai_handles_str(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cm.asyncio, "to_thread", AsyncMock(return_value="plain text result"))
    segments = await cm._transcribe_one_track(
        track_name="t",
        track_wav="x.wav",
        track_num=1,
        total_tracks=1,
        provider="openai",
        model="m",
        language="en",
        hf_provider="hf-inference",
        progress_callback=None,
    )
    assert segments == []


async def _stub_track(**kw: Any) -> list[dict[str, Any]]:
    import asyncio as _aio
    await _aio.sleep(0)
    offset = float(kw["track_num"])
    return [{
        "text": f"line-{kw['track_name']}",
        "start": offset,
        "end": offset + 1,
        "speaker": kw["track_name"],
    }]


@pytest.mark.asyncio
async def test_transcribe_and_merge_tracks_combines(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cm, "_transcribe_one_track", _stub_track)
    out = await cm.transcribe_and_merge_tracks(
        {"alice": "a.wav", "bob": "b.wav"}, provider="local", model="m", language="en"
    )
    assert "alice" in out
    assert "bob" in out


async def _empty_track(**kw: Any) -> list[dict[str, Any]]:
    import asyncio as _aio
    await _aio.sleep(0)
    return [{"text": "", "start": 0.0, "end": 1.0, "speaker": kw["track_name"]}]


@pytest.mark.asyncio
async def test_transcribe_and_merge_tracks_strips_blank(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cm, "_transcribe_one_track", _empty_track)
    out = await cm.transcribe_and_merge_tracks(
        {"t1": "x.wav"}, provider="local", model="m", language="en"
    )
    assert out == ""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import src.api.mcp.mcp_server as mcp_module
from src.api.mcp.mcp_server import (
    transcribe_audacity,
    transcribe_hf,
    transcribe_local,
    transcribe_openai,
)


async def _fake_local_segments(*_a: Any, **_k: Any) -> Any:
    yield {"text": "hello", "start": 0.0, "end": 1.0}


def test_mcp_local_success_pins_today_envelope() -> None:
    # given
    async def run() -> dict[str, Any]:
        with (
            patch.object(mcp_module, "download_to_temp_async", new=AsyncMock(return_value="/tmp/a.wav")),
            patch.object(mcp_module, "local_speech_transcription", new=_fake_local_segments),
        ):
            # when
            return await transcribe_local(audio_uri="file:///tmp/a.wav")

    import asyncio

    result = asyncio.run(run())
    # then
    assert result["status"] == "success"
    assert result["source"] == "local"


def test_mcp_openai_success_pins_today_envelope(monkeypatch: pytest.MonkeyPatch) -> None:
    # given
    from src.config.config import settings

    monkeypatch.setattr(settings, "OPENAI_API_KEY", "sk-x")
    # when
    import asyncio

    async def run() -> dict[str, Any]:
        with (
            patch.object(mcp_module, "download_to_temp_async", new=AsyncMock(return_value="/tmp/a.wav")),
            patch.object(
                mcp_module,
                "openai_speech_transcription",
                new=MagicMock(return_value="spoken words"),
            ),
        ):
            return await transcribe_openai(audio_uri="file:///tmp/a.wav")

    result = asyncio.run(run())
    # then
    assert result["status"] == "success"
    assert result["transcription"] == "spoken words"


def test_mcp_hf_success_pins_today_envelope(monkeypatch: pytest.MonkeyPatch) -> None:
    # given
    from src.config.config import settings

    monkeypatch.setattr(settings, "HF_TOKEN", "hf-x")
    # when
    import asyncio

    async def run() -> dict[str, Any]:
        with (
            patch.object(mcp_module, "download_to_temp_async", new=AsyncMock(return_value="/tmp/a.wav")),
            patch.object(
                mcp_module,
                "hf_speech_transcription",
                new=MagicMock(return_value="hf words"),
            ),
        ):
            return await transcribe_hf(audio_uri="file:///tmp/a.wav")

    result = asyncio.run(run())
    # then
    assert result["status"] == "success"
    assert result["transcription"] == "hf words"


def test_mcp_audacity_success_pins_today_envelope() -> None:
    # given
    async def run() -> dict[str, Any]:
        with (
            patch.object(mcp_module, "download_to_temp_async", new=AsyncMock(return_value="/tmp/p.zip")),
            patch.object(
                mcp_module,
                "extract_tracks_from_aup",
                new=MagicMock(return_value={"s1": "/tmp/x.wav"}),
            ),
            patch.object(
                mcp_module,
                "transcribe_and_merge_tracks",
                new=AsyncMock(return_value="merged"),
            ),
        ):
            # when
            return await transcribe_audacity(audio_uri="file:///tmp/p.zip")

    import asyncio

    result = asyncio.run(run())
    # then
    assert result["status"] == "success"
    assert result["transcription"] == "merged"

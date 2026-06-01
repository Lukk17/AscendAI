"""Orchestration facade. Both REST and MCP surfaces route through here so the
business logic doesn't fork by transport."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from src.transcription.huggingface_api_speach_to_text import hf_transcript
from src.transcription.local_speech_to_text import local_speech_transcription_stream
from src.transcription.openai_api_speach_to_text import openai_transcript

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable

logger = logging.getLogger(__name__)


def openai_speech_transcription(
    audio_file_path: str,
    model: str,
    language: str,
    with_timestamps: bool = False,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> list[dict[str, Any]] | str:
    response = openai_transcript(
        audio_file_path, model, language, with_timestamps, progress_callback=progress_callback
    )
    if with_timestamps:
        logger.info(f"[OpenAI] {len(response)} segments transcribed\n")
    else:
        logger.info(f"[OpenAI] {response}\n")
    return response


def hf_speech_transcription(
    audio_file_path: str,
    model: str,
    provider: str,
    with_timestamps: bool = False,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> list[dict[str, Any]] | str:
    logger.info("[HF] Starting transcription...")
    response_text = hf_transcript(
        audio_file_path, model, provider, with_timestamps, progress_callback=progress_callback
    )
    if with_timestamps:
        logger.info(f"[HF] {len(response_text)} segments transcribed\n")
    else:
        logger.info(f"[HF] {response_text}\n")
    return response_text


async def local_speech_transcription(
    audio_file_path: str, model_path: str, language: str
) -> AsyncIterator[dict[str, Any]]:
    logger.info("[Local] Starting transcription stream...")
    async for segment in local_speech_transcription_stream(model_path, audio_file_path, language):
        yield segment

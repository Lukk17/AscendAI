"""OpenAI Whisper transcription path.

Uses the shared `chunked_audio` ffmpeg helper for on-disk chunking (no pydub
full-decode-in-memory) and lazy-constructs the OpenAI client on first use
so importing this module doesn't require OPENAI_API_KEY.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import TYPE_CHECKING, Any

import httpx
from openai import APIError, OpenAI

from src.config.config import settings
from src.transcription.audio_chunker import chunked_audio

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger(__name__)

_client_lock = threading.Lock()
_client_instance: OpenAI | None = None


def _get_client() -> OpenAI:
    """Lazy OpenAI client singleton — avoids OPENAI_API_KEY enforcement at
    import time so unrelated paths (HF, local) work without it.

    The narrowing dance: capture the module global into a local under the
    lock, construct on miss, write back, and return the local. Static
    analysers can narrow the local to `OpenAI` even though they refuse to
    narrow the module global between statements."""

    global _client_instance  # noqa: PLW0603 — module cache

    with _client_lock:
        instance = _client_instance
        if instance is None:
            instance = OpenAI(
                timeout=httpx.Timeout(settings.API_TIMEOUT_SECONDS),
                max_retries=5,
            )
            _client_instance = instance
        return instance


def _build_create_kwargs(
    audio_file: Any, model: str, language: str, with_timestamps: bool
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {"model": model, "file": audio_file}
    if language:
        kwargs["language"] = language
    if with_timestamps:
        kwargs["response_format"] = "verbose_json"
        kwargs["timestamp_granularities"] = ["segment"]
    return kwargs


def _segments_from_response(response: Any) -> list[dict[str, Any]]:
    """Extract per-segment dicts from a verbose_json response.

    The OpenAI typeshed types `response.segments` as `list[Segment] | None
    | list[DiarizedSegment]`. We early-return on the None case (explicit
    `if not raw` so static analysers narrow), then iterate the resulting
    iterable directly — no `list()` re-materialisation needed."""

    raw: Any = getattr(response, "segments", None)
    if not raw:
        return []
    return [{"text": s.text, "start": s.start, "end": s.end} for s in raw]


def _transcribe_single_chunk(
    audio_chunk_path: str, model: str, language: str, with_timestamps: bool
) -> list[dict[str, Any]] | str:
    """Per-chunk OpenAI call. Raises ValueError on APIError so the router
    can map it to a 400/RFC 7807 envelope."""

    client = _get_client()
    try:
        with open(audio_chunk_path, "rb") as audio_file:
            kwargs = _build_create_kwargs(audio_file, model, language, with_timestamps)
            response = client.audio.transcriptions.create(**kwargs)

        if with_timestamps:
            return _segments_from_response(response)
        text: str = response.text
        return text
    except APIError as exc:
        logger.exception(f"OpenAI API error for model '{model}'")
        raise ValueError(
            "OpenAI API failed to process an audio chunk. It may be an invalid model "
            "or the API may be unavailable."
        ) from exc


def _derive_chunk_seconds() -> int:
    """Translate the OpenAI byte cap into a wall-clock chunk duration at the
    16 kHz mono 16-bit format every chunk is normalised to."""

    hf_seconds = settings.HF_CHUNK_LENGTH_SECONDS
    bytes_per_second = settings.TARGET_CHUNK_SIZE_BYTES // hf_seconds if hf_seconds > 0 else 32000
    bytes_per_second = max(bytes_per_second, 16000)
    return max(int(settings.TARGET_CHUNK_SIZE_BYTES / bytes_per_second), 1)


def _emit_progress(
    progress_callback: Callable[[dict[str, Any]], None] | None,
    payload: dict[str, Any],
) -> None:
    if progress_callback:
        progress_callback(payload)


def _check_chunk_size(chunk_path: str, chunk_num: int) -> int:
    chunk_size = os.path.getsize(chunk_path)
    if chunk_size > settings.OPENAI_API_LIMIT_BYTES:
        raise ValueError(f"Generated chunk {chunk_num} exceeded OpenAI size limit.")
    return chunk_size


def _accumulate_chunk_result(
    result: list[dict[str, Any]] | str,
    *,
    time_offset: float,
    full_segments: list[dict[str, Any]],
    full_text: list[str],
) -> None:
    """Sort the per-chunk OpenAI response into the right accumulator.
    `_transcribe_single_chunk` returns a `list[dict]` when timestamps were
    requested and a `str` otherwise — dispatch purely on runtime type."""

    if isinstance(result, list):
        for segment in result:
            segment["start"] += time_offset
            segment["end"] += time_offset
            full_segments.append(segment)
    else:
        full_text.append(result)


def openai_transcript(
    audio_file_path: str,
    model: str,
    language: str,
    with_timestamps: bool = False,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> list[dict[str, Any]] | str:
    """Transcribe an audio file via the OpenAI Whisper API.

    Files under the OpenAI per-request size limit go through directly; larger
    files are split via `chunked_audio` (ffmpeg `-f segment`) so we never
    decode the full audio into Python memory.
    """

    file_size = os.path.getsize(audio_file_path)
    logger.info(
        f"[OpenAI] Parameters: language='{language}', api_limit={settings.OPENAI_API_LIMIT_BYTES}, "
        f"target_chunk={settings.TARGET_CHUNK_SIZE_BYTES}, with_timestamps={with_timestamps}"
    )

    if file_size < settings.OPENAI_API_LIMIT_BYTES:
        logger.info(f"File size {file_size / 1024 / 1024:.2f} MB within limit; direct call.")
        return _transcribe_single_chunk(audio_file_path, model, language, with_timestamps)

    chunk_seconds = _derive_chunk_seconds()
    logger.info(f"File size {file_size / 1024 / 1024:.2f} MB exceeds limit; chunking @ {chunk_seconds}s.")

    full_text: list[str] = []
    full_segments: list[dict[str, Any]] = []

    with chunked_audio(audio_file_path, chunk_seconds) as chunks:
        num_chunks = len(chunks)
        for idx, chunk_path in enumerate(chunks):
            chunk_num = idx + 1
            chunk_size = _check_chunk_size(chunk_path, chunk_num)
            chunk_size_mb = chunk_size / 1024 / 1024
            _emit_progress(progress_callback, {
                "type": "progress",
                "message": f"Transcribing chunk {chunk_num}/{num_chunks}",
                "data": {"chunk": chunk_num, "total": num_chunks, "size_mb": round(chunk_size_mb, 2)},
            })

            chunk_start = time.monotonic()
            result = _transcribe_single_chunk(chunk_path, model, language, with_timestamps)
            elapsed = time.monotonic() - chunk_start

            _accumulate_chunk_result(
                result,
                time_offset=idx * chunk_seconds,
                full_segments=full_segments,
                full_text=full_text,
            )
            logger.info(f"Chunk {chunk_num}/{num_chunks} complete in {elapsed:.2f}s.")
            _emit_progress(progress_callback, {
                "type": "progress",
                "message": f"Chunk {chunk_num}/{num_chunks} complete in {elapsed:.2f}s",
                "data": {"chunk": chunk_num, "total": num_chunks, "elapsed_s": round(elapsed, 2)},
            })

    if with_timestamps:
        return full_segments
    return " ".join(full_text)

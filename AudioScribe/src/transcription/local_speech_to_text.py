"""Local faster-whisper transcription path.

Replaces the per-request `multiprocessing.spawn` worker with a lazy module-
level WhisperModel singleton guarded by an asyncio semaphore for GPU
serialisation. Streaming is per-segment now (not the prior batch-then-yield
shape) so SSE consumers see real progress.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from typing import TYPE_CHECKING, Any

from src.config.config import settings
from src.transcription.audio_chunker import chunked_audio

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

logger = logging.getLogger(__name__)

_model_lock = threading.Lock()
_model_instance: Any = None
_model_path_loaded: str | None = None

_gpu_semaphore = asyncio.Semaphore(1)


def _load_model(model_path: str) -> Any:
    """Lazy WhisperModel construction. Loads on first use; subsequent calls
    with the same path return the cached instance. Switching model_path
    triggers a reload (rare in practice)."""

    import torch
    from faster_whisper import WhisperModel

    global _model_instance, _model_path_loaded  # noqa: PLW0603 — module cache

    with _model_lock:
        if _model_instance is not None and _model_path_loaded == model_path:
            return _model_instance

        if torch.cuda.is_available():
            device, compute_type = "cuda", "float16"
        else:
            device, compute_type = "cpu", "int8"
        logger.info(f"Loading WhisperModel '{model_path}' on {device} ({compute_type})...")
        _model_instance = WhisperModel(model_path, device=device, compute_type=compute_type)
        _model_path_loaded = model_path
        logger.info("WhisperModel ready.")
        return _model_instance


def _transcribe_chunk_sync(
    model_path: str, chunk_path: str, language: str, time_offset_s: float
) -> list[dict[str, Any]]:
    """Synchronous per-chunk transcription. Returns a list of segment dicts
    with `text/start/end` already offset against the original audio."""

    model = _load_model(model_path)
    segments_chunk, _info = model.transcribe(
        chunk_path,
        beam_size=settings.BEAM_SIZE,
        language=language,
        best_of=settings.BEST_OF,
        condition_on_previous_text=settings.CONDITION_ON_PREVIOUS_TEXT,
        vad_filter=settings.VAD_FILTER,
        vad_parameters=settings.VAD_PARAMETERS,
        temperature=settings.TEMPERATURE,
    )
    return [
        {
            "text": segment.text.strip(),
            "start": segment.start + time_offset_s,
            "end": segment.end + time_offset_s,
        }
        for segment in segments_chunk
    ]


async def local_speech_transcription_stream(
    model_path: str, audio_path: str, language: str
) -> AsyncIterator[dict[str, Any]]:
    """Per-segment async generator. Chunks the audio on disk via ffmpeg,
    transcribes each chunk under the GPU semaphore, and yields segments as
    they arrive — SSE sees the first segment within seconds rather than at
    the very end of the job."""

    chunk_seconds = settings.CHUNK_LENGTH_MINUTES * 60

    async with _gpu_semaphore:
        loop = asyncio.get_running_loop()
        start_time = loop.time()
        logger.info(
            f"[Local] Transcription parameters: language='{language}', chunk_seconds={chunk_seconds}, "
            f"beam_size={settings.BEAM_SIZE}, best_of={settings.BEST_OF}, vad={settings.VAD_FILTER}"
        )

        with chunked_audio(audio_path, chunk_seconds) as chunks:
            for idx, chunk_path in enumerate(chunks):
                time_offset_s = float(idx * chunk_seconds)
                logger.info(f"[Local] Processing chunk {idx + 1}/{len(chunks)}...")
                segments = await asyncio.to_thread(
                    _transcribe_chunk_sync, model_path, chunk_path, language, time_offset_s
                )
                for segment in segments:
                    yield segment

        logger.info(f"[Local] Total transcription took {loop.time() - start_time:.2f}s.")

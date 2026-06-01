"""Hugging Face Inference transcription path.

Same ffmpeg-segment chunking strategy as OpenAI — no pydub buffer.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import TYPE_CHECKING, Any

from huggingface_hub import InferenceClient
from huggingface_hub.errors import HfHubHTTPError

from src.config.config import settings
from src.transcription.audio_chunker import chunked_audio

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger(__name__)

_client_lock = threading.Lock()
_client_cache: dict[tuple[str, str], InferenceClient] = {}


def _get_client(provider: str, token: str) -> InferenceClient:
    """Per-(provider, token) cached InferenceClient. Avoids HF auth reload on
    every call while honouring multiple-provider deployments."""

    key = (provider, token)
    with _client_lock:
        if key not in _client_cache:
            _client_cache[key] = InferenceClient(provider=provider, token=token)  # type: ignore[arg-type]
        return _client_cache[key]


def _transcribe_single_chunk(client: InferenceClient, audio_chunk_path: str, model: str) -> str:
    try:
        result = client.automatic_speech_recognition(audio_chunk_path, model=model)
        text: str = result.get("text", "") if hasattr(result, "get") else ""
        return text
    except HfHubHTTPError as exc:
        logger.exception(f"Hugging Face API error for model '{model}'")
        raise ValueError("Hugging Face API failed to process an audio chunk.") from exc


def hf_transcript(
    audio_file_path: str,
    model: str,
    provider: str,
    with_timestamps: bool = False,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> list[dict[str, Any]] | str:
    """Transcribe an audio file via the HF Inference API.

    Uses ffmpeg-segment chunking; the InferenceClient sees only small WAV
    files. No pydub decode of the full source.
    """

    hf_token = os.environ.get("HF_TOKEN")
    if not hf_token:
        raise ValueError("HF_TOKEN environment variable not set!")

    client = _get_client(provider, hf_token)
    logger.info(f"[HF] Parameters: model='{model}', provider='{provider}'")

    chunk_seconds = settings.HF_CHUNK_LENGTH_SECONDS

    full_text: list[str] = []
    full_segments: list[dict[str, Any]] = []

    try:
        with chunked_audio(audio_file_path, chunk_seconds) as chunks:
            num_chunks = len(chunks)
            for idx, chunk_path in enumerate(chunks):
                chunk_num = idx + 1
                chunk_size_mb = os.path.getsize(chunk_path) / 1024 / 1024
                if progress_callback:
                    progress_callback({
                        "type": "progress",
                        "message": f"Transcribing chunk {chunk_num}/{num_chunks}",
                        "data": {"chunk": chunk_num, "total": num_chunks, "size_mb": round(chunk_size_mb, 2)},
                    })

                chunk_start = time.monotonic()
                text = _transcribe_single_chunk(client, chunk_path, model)
                elapsed = time.monotonic() - chunk_start

                if with_timestamps:
                    full_segments.append({
                        "text": text,
                        "start": idx * chunk_seconds,
                        "end": (idx + 1) * chunk_seconds,
                    })
                else:
                    full_text.append(text)

                logger.info(f"Chunk {chunk_num}/{num_chunks} complete in {elapsed:.2f}s.")
                if progress_callback:
                    progress_callback({
                        "type": "progress",
                        "message": f"Chunk {chunk_num}/{num_chunks} complete in {elapsed:.2f}s",
                        "data": {"chunk": chunk_num, "total": num_chunks, "elapsed_s": round(elapsed, 2)},
                    })
    except (ValueError, OSError):
        # Service-authored exceptions propagate as-is; the global RFC 7807
        # handler maps them to 400 / 502 / etc.
        raise
    except Exception as exc:
        logger.exception("Unexpected HF error")
        raise RuntimeError("An unexpected error occurred during Hugging Face transcription.") from exc

    if with_timestamps:
        return full_segments
    return " ".join(full_text)

"""Shared on-disk audio chunker.

Replaces the per-backend `pydub.AudioSegment.from_file(...).export(...)`
loop with a single ffmpeg-`-f segment` invocation. ffmpeg streams the input,
splits into fixed-duration chunks (16 kHz mono 16-bit signed), and writes
them as numbered WAV files directly to a working directory. No Python-side
audio buffer is ever held.

This eliminates the 100-MB-per-hour-of-stereo-44.1kHz memory cost the audit
flagged for the OpenAI and HuggingFace backends.
"""

from __future__ import annotations

import logging
import os
import secrets
import tempfile
from contextlib import contextmanager, suppress
from typing import TYPE_CHECKING

from src.config.config import settings

if TYPE_CHECKING:
    from collections.abc import Generator

logger = logging.getLogger(__name__)

_SAMPLE_RATE = 16000
_CHANNELS = 1
_SAMPLE_FMT = "s16"


@contextmanager
def chunked_audio(audio_path: str, chunk_seconds: int) -> Generator[list[str], None, None]:
    """Yield a list of on-disk chunk paths for `audio_path`, split every
    `chunk_seconds`. The chunks are deleted when the contextmanager exits.

    Uses ffmpeg's `-f segment` muxer so the whole pipeline streams; we never
    load the full audio into Python memory. Output chunks are normalised to
    16 kHz mono 16-bit signed so every backend sees the same shape.
    """

    work_dir = tempfile.mkdtemp(prefix=f"audioscribe_chunks_{secrets.token_hex(4)}_")
    pattern = os.path.join(work_dir, "chunk_%05d.wav")

    args = [
        settings.FFMPEG_PATH,
        "-y",
        "-i", audio_path,
        "-f", "segment",
        "-segment_time", str(chunk_seconds),
        "-ar", str(_SAMPLE_RATE),
        "-ac", str(_CHANNELS),
        "-sample_fmt", _SAMPLE_FMT,
        "-loglevel", "error",
        pattern,
    ]

    import subprocess

    try:
        # S603: args[0] is settings.FFMPEG_PATH (a configured binary path);
        # remaining args are entirely service-controlled (numbers + a temp
        # path we just generated). No user-controlled string is interpolated.
        subprocess.run(  # noqa: S603
            args,
            check=True,
            capture_output=True,
            timeout=settings.FFMPEG_TIMEOUT_SECONDS,
        )
        chunks = sorted(
            os.path.join(work_dir, name) for name in os.listdir(work_dir) if name.endswith(".wav")
        )
        if not chunks:
            raise OSError("ffmpeg segment produced no chunks")
        logger.info(f"ffmpeg produced {len(chunks)} chunks in {work_dir}")
        yield chunks
    except subprocess.TimeoutExpired as exc:
        raise OSError(
            f"ffmpeg segmentation timed out after {settings.FFMPEG_TIMEOUT_SECONDS}s"
        ) from exc
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.decode(errors="replace") if exc.stderr else ""
        raise OSError(f"ffmpeg segmentation failed: {stderr}") from exc
    finally:
        for f in os.listdir(work_dir):
            with suppress(OSError):
                os.remove(os.path.join(work_dir, f))
        with suppress(OSError):
            os.rmdir(work_dir)

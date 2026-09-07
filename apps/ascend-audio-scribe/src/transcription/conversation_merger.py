"""Multi-track Audacity conversation merger.

Transcribes every extracted track in parallel (bounded by a semaphore whose
size depends on the provider — 1 for local-GPU, larger for network-bound
OpenAI / HF), then merges segments chronologically with speaker tags.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from src.scribe import hf_speech_transcription, local_speech_transcription, openai_speech_transcription

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger(__name__)

_PROVIDER_CONCURRENCY: dict[str, int] = {
    "local": 1,  # GPU-bound; serialised by Whisper's own semaphore anyway
    "openai": 4,  # network-bound; bounded to avoid OpenAI rate limits
    "huggingface": 4,
}


def format_elapsed_time(seconds: float) -> str:
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    return f"[{hours:02d}:{minutes:02d}:{secs:02d}]"


async def _transcribe_one_track(
    track_name: str,
    track_wav: str,
    track_num: int,
    total_tracks: int,
    provider: str,
    model: str,
    language: str,
    hf_provider: str,
    progress_callback: Callable[[dict[str, Any]], None] | None,
) -> list[dict[str, Any]]:
    """Transcribe a single track and tag every segment with the speaker."""

    logger.info(f"Transcribing track '{track_name}' ({track_num}/{total_tracks})...")
    if progress_callback:
        progress_callback({
            "type": "progress",
            "message": f"Transcribing track '{track_name}' ({track_num}/{total_tracks})",
            "data": {"track": track_num, "total_tracks": total_tracks, "track_name": track_name},
        })

    segments: list[dict[str, Any]] = []
    if provider == "local":
        async for s in local_speech_transcription(
            audio_file_path=track_wav, model_path=model, language=language
        ):
            segments.append({"text": s["text"], "start": float(s["start"]), "end": float(s["end"])})
    elif provider == "openai":
        result = await asyncio.to_thread(
            openai_speech_transcription,
            audio_file_path=track_wav,
            model=model,
            language=language,
            with_timestamps=True,
            progress_callback=progress_callback,
        )
        if isinstance(result, list):
            segments = result
    elif provider == "huggingface":
        result = await asyncio.to_thread(
            hf_speech_transcription,
            audio_file_path=track_wav,
            model=model,
            provider=hf_provider,
            with_timestamps=True,
            progress_callback=progress_callback,
        )
        if isinstance(result, list):
            segments = result
    else:
        raise ValueError(f"Unknown provider: {provider}")

    for segment in segments:
        segment["speaker"] = track_name

    logger.info(
        f"Track '{track_name}' ({track_num}/{total_tracks}) complete with {len(segments)} segments."
    )
    if progress_callback:
        progress_callback({
            "type": "progress",
            "message": f"Track '{track_name}' complete ({len(segments)} segments)",
            "data": {"track": track_num, "total_tracks": total_tracks, "segments": len(segments)},
        })

    return segments


async def transcribe_and_merge_tracks(
    tracks: dict[str, str],
    provider: str,
    model: str,
    language: str,
    hf_provider: str = "hf-inference",
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> str:
    """Drive every track through the chosen provider in parallel (bounded),
    then merge segments chronologically with `[HH:MM:SS] [Speaker] text`."""

    concurrency = _PROVIDER_CONCURRENCY.get(provider, 1)
    semaphore = asyncio.Semaphore(concurrency)
    total_tracks = len(tracks)

    async def _gated(track_name: str, track_wav: str, track_num: int) -> list[dict[str, Any]]:
        async with semaphore:
            return await _transcribe_one_track(
                track_name=track_name,
                track_wav=track_wav,
                track_num=track_num,
                total_tracks=total_tracks,
                provider=provider,
                model=model,
                language=language,
                hf_provider=hf_provider,
                progress_callback=progress_callback,
            )

    track_results = await asyncio.gather(
        *[
            _gated(name, path, idx + 1)
            for idx, (name, path) in enumerate(tracks.items())
        ]
    )

    all_segments: list[dict[str, Any]] = [s for segments in track_results for s in segments]
    all_segments.sort(key=lambda x: x["start"])

    result_lines: list[str] = []
    for segment in all_segments:
        time_tag = format_elapsed_time(segment["start"])
        speaker_tag = f"[{segment['speaker']}]"
        text = str(segment.get("text", "")).strip()
        if text:
            result_lines.append(f"{time_tag} {speaker_tag} {text}")

    return "\n".join(result_lines)

import asyncio
import logging
from typing import Callable, Optional

from src.scribe import openai_speech_transcription, hf_speech_transcription, local_speech_transcription

logger = logging.getLogger(__name__)


def format_elapsed_time(seconds: float) -> str:
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    return f"[{hours:02d}:{minutes:02d}:{secs:02d}]"


async def transcribe_and_merge_tracks(tracks: dict[str, str], provider: str, model: str, language: str,
                                      hf_provider: str = "hf-inference",
                                      progress_callback: Optional[Callable[[dict], None]] = None) -> str:
    all_segments = []
    track_names = list(tracks.keys())
    total_tracks = len(track_names)

    for track_idx, (track_name, track_wav) in enumerate(tracks.items()):
        track_num = track_idx + 1
        logger.info(f"Transcribing track '{track_name}' ({track_num}/{total_tracks})...")
        if progress_callback:
            progress_callback({"type": "progress", "message": f"Transcribing track '{track_name}' ({track_num}/{total_tracks})",
                               "data": {"track": track_num, "total_tracks": total_tracks, "track_name": track_name}})

        segments = []
        if provider == "local":
            async for s in local_speech_transcription(audio_file_path=track_wav, model_path=model, language=language):
                segments.append({"text": s['text'], "start": float(s['start']), "end": float(s['end'])})
        elif provider == "openai":
            segments = await asyncio.to_thread(
                openai_speech_transcription,
                audio_file_path=track_wav,
                model=model,
                language=language,
                with_timestamps=True,
                progress_callback=progress_callback
            )
        elif provider == "huggingface":
            segments = await asyncio.to_thread(
                hf_speech_transcription,
                audio_file_path=track_wav,
                model=model,
                provider=hf_provider,
                with_timestamps=True,
                progress_callback=progress_callback
            )
        else:
            raise ValueError(f"Unknown provider: {provider}")

        for segment in segments:
            segment['speaker'] = track_name
            all_segments.append(segment)

        logger.info(f"Track '{track_name}' ({track_num}/{total_tracks}) complete with {len(segments)} segments.")
        if progress_callback:
            progress_callback({"type": "progress", "message": f"Track '{track_name}' complete ({len(segments)} segments)",
                               "data": {"track": track_num, "total_tracks": total_tracks, "segments": len(segments)}})

    all_segments.sort(key=lambda x: x['start'])

    result_lines = []
    for segment in all_segments:
        time_tag = format_elapsed_time(segment['start'])
        speaker_tag = f"[{segment['speaker']}]"
        text = str(segment.get('text', '')).strip()
        if text:
            result_lines.append(f"{time_tag} {speaker_tag} {text}")

    return "\n".join(result_lines)

import asyncio
import logging

from src.scribe import openai_speech_transcription, hf_speech_transcription, local_speech_transcription

logger = logging.getLogger(__name__)


def format_elapsed_time(seconds: float) -> str:
    """Formats seconds into [HH:MM:SS] format."""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    return f"[{hours:02d}:{minutes:02d}:{secs:02d}]"


async def transcribe_and_merge_tracks(tracks: dict[str, str], provider: str, model: str, language: str, hf_provider: str = "hf-inference") -> str:
    """
    Transcribes multiple audio tracks sequentially and merges them chronologically.
    Returns a unified markdown string with timestamp and speaker tags.
    """
    all_segments = []

    for track_name, track_wav in tracks.items():
        logger.info(f"Transcribing track '{track_name}'...")

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
                with_timestamps=True
            )
        elif provider == "huggingface":
            segments = await asyncio.to_thread(
                hf_speech_transcription,
                audio_file_path=track_wav,
                model=model,
                provider=hf_provider,
                with_timestamps=True
            )
        else:
            raise ValueError(f"Unknown provider: {provider}")

        for segment in segments:
            segment['speaker'] = track_name
            all_segments.append(segment)

    all_segments.sort(key=lambda x: x['start'])

    result_lines = []
    for segment in all_segments:
        time_tag = format_elapsed_time(segment['start'])
        speaker_tag = f"[{segment['speaker']}]"
        text = str(segment.get('text', '')).strip()
        if text:
            result_lines.append(f"{time_tag} {speaker_tag} {text}")

    return "\n".join(result_lines)

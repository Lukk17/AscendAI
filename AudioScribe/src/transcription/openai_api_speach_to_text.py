import logging
import os
import tempfile
import time
from typing import Callable, Optional

import httpx
from openai import OpenAI, APIError
from pydub import AudioSegment

from src.config.config import settings

logger = logging.getLogger(__name__)

client = OpenAI(
    timeout=httpx.Timeout(settings.API_TIMEOUT_SECONDS),
    max_retries=5,
)


def _transcribe_single_chunk(audio_chunk_path: str, model: str, language: str, with_timestamps: bool) -> list[dict] | str:
    """Helper function to transcribe a single audio chunk."""
    try:
        with open(audio_chunk_path, "rb") as audio_file:
            kwargs = {"model": model, "file": audio_file}
            if language:
                kwargs["language"] = language
            if with_timestamps:
                kwargs["response_format"] = "verbose_json"
                kwargs["timestamp_granularities"] = ["segment"]
            response = client.audio.transcriptions.create(**kwargs)
            
        if with_timestamps:
            return [{"text": s.text, "start": s.start, "end": s.end} for s in response.segments]
        return response.text
    except APIError as e:
        logger.error(f"OpenAI API error during chunk transcription for model '{model}': {e}")
        raise ValueError(
            "OpenAI API failed to process an audio chunk. It may be an invalid model or the API may be unavailable.") from e


def openai_transcript(audio_file_path: str, model: str, language: str, with_timestamps: bool = False,
                      progress_callback: Optional[Callable[[dict], None]] = None):
    """
    Transcribes an audio file using the OpenAI Whisper API.
    Handles large files by automatically splitting them into chunks.
    """
    file_size = os.path.getsize(audio_file_path)

    logger.info(
        f"[OpenAI] Transcription Parameters: "
        f"Language='{language}', "
        f"APILimitBytes={settings.OPENAI_API_LIMIT_BYTES}, "
        f"TargetChunkBytes={settings.TARGET_CHUNK_SIZE_BYTES}, "
        f"WithTimestamps={with_timestamps}"
    )

    if file_size < settings.OPENAI_API_LIMIT_BYTES:
        logger.info(f"File size ({file_size / 1024 / 1024:.2f} MB) is within limit. Transcribing directly.")
        chunk_start = time.monotonic()
        result = _transcribe_single_chunk(audio_file_path, model, language, with_timestamps)
        elapsed = time.monotonic() - chunk_start
        logger.info(f"Transcription complete in {elapsed:.2f}s.")
        return result

    logger.info(f"File size ({file_size / 1024 / 1024:.2f} MB) exceeds limit. Splitting into chunks.")

    try:
        audio = AudioSegment.from_file(audio_file_path)
    except Exception as e:
        logger.exception("Pydub failed to load the audio file for chunking.")
        raise IOError("Failed to load audio file for chunking. It may be corrupt or an unsupported format.") from e

    audio = audio.set_frame_rate(16000).set_channels(1).set_sample_width(2)
    bytes_per_second = 32000

    chunk_length_ms = int((settings.TARGET_CHUNK_SIZE_BYTES / bytes_per_second) * 1000)

    full_transcription_text = []
    full_transcription_segments = []
    temp_files = []

    try:
        num_chunks = (len(audio) // chunk_length_ms) + 1
        logger.info(
            f"Splitting audio into {num_chunks} chunks of approximately {chunk_length_ms / 1000 / 60:.2f} minutes each.")

        for i, start_ms in enumerate(range(0, len(audio), chunk_length_ms)):
            chunk_num = i + 1
            end_ms = start_ms + chunk_length_ms
            chunk = audio[start_ms:end_ms]

            with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp_audio:
                chunk.export(tmp_audio.name, format="wav")
                tmp_path = tmp_audio.name

            temp_files.append(tmp_path)

            chunk_size = os.path.getsize(tmp_path)
            if chunk_size > settings.OPENAI_API_LIMIT_BYTES:
                logger.error(f"Chunk {chunk_num} size {chunk_size} exceeds limit {settings.OPENAI_API_LIMIT_BYTES}!")
                raise ValueError(f"Generated chunk {chunk_num} exceeded OpenAI size limit.")

            chunk_size_mb = chunk_size / 1024 / 1024
            logger.info(f"Transcribing chunk {chunk_num}/{num_chunks} ({chunk_size_mb:.2f} MB)...")
            if progress_callback:
                progress_callback({"type": "progress", "message": f"Transcribing chunk {chunk_num}/{num_chunks}",
                                   "data": {"chunk": chunk_num, "total": num_chunks, "size_mb": round(chunk_size_mb, 2)}})

            chunk_start = time.monotonic()
            chunk_transcription = _transcribe_single_chunk(tmp_path, model, language, with_timestamps)
            chunk_elapsed = time.monotonic() - chunk_start

            if with_timestamps:
                for segment in chunk_transcription:
                    segment['start'] += start_ms / 1000.0
                    segment['end'] += start_ms / 1000.0
                    full_transcription_segments.append(segment)
            else:
                full_transcription_text.append(chunk_transcription)

            logger.info(f"Chunk {chunk_num}/{num_chunks} complete in {chunk_elapsed:.2f}s.")
            if progress_callback:
                progress_callback({"type": "progress", "message": f"Chunk {chunk_num}/{num_chunks} complete in {chunk_elapsed:.2f}s",
                                   "data": {"chunk": chunk_num, "total": num_chunks, "elapsed_s": round(chunk_elapsed, 2)}})

        if with_timestamps:
            return full_transcription_segments
        return " ".join(full_transcription_text)

    finally:
        for f_path in temp_files:
            try:
                os.remove(f_path)
            except OSError:
                pass
        logger.info("Cleaned up all temporary audio chunks for OpenAI transcription.")

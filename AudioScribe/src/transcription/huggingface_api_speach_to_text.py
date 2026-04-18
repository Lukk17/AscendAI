import logging
import os
import tempfile
import time
from typing import Callable, Optional

from huggingface_hub import InferenceClient
from huggingface_hub.inference._generated.types import AutomaticSpeechRecognitionOutput
from huggingface_hub.utils import HfHubHTTPError
from pydub import AudioSegment

from src.config.config import settings

logger = logging.getLogger(__name__)


def _transcribe_single_chunk(client: InferenceClient, audio_chunk_path: str, model: str) -> str:
    """Helper function to transcribe a single audio chunk with the HF API."""
    try:
        result: AutomaticSpeechRecognitionOutput = client.automatic_speech_recognition(
            audio_chunk_path,
            model=model,
        )
        return result.get("text", "")
    except HfHubHTTPError as e:
        logger.error(f"Hugging Face API error during chunk transcription for model '{model}': {e}")
        raise ValueError("Hugging Face API failed to process an audio chunk.") from e


def hf_transcript(audio_file_path: str, model: str, provider: str, with_timestamps: bool = False,
                   progress_callback: Optional[Callable[[dict], None]] = None):
    """
    Transcribes an audio file using a Hugging Face provider.
    Handles long files by splitting them into small chunks to avoid timeouts on the free tier.
    """
    hf_token = os.environ.get("HF_TOKEN")
    if not hf_token:
        raise ValueError("HF_TOKEN environment variable not set!")

    client = InferenceClient(provider=provider, token=hf_token)

    logger.info(f"[HF] Transcription Parameters: Model='{model}', Provider='{provider}'")

    try:
        audio = AudioSegment.from_file(audio_file_path)
    except Exception as e:
        logger.exception("Pydub failed to load the audio file for chunking.")
        raise IOError("Failed to load audio file for chunking. It may be corrupt or an unsupported format.") from e

    chunk_length_ms = settings.HF_CHUNK_LENGTH_SECONDS * 1000

    full_transcription_text = []
    full_transcription_segments = []
    temp_files = []

    try:
        num_chunks = (len(audio) // chunk_length_ms) + 1
        logger.info(f"Splitting audio into {num_chunks} chunks of {settings.HF_CHUNK_LENGTH_SECONDS} seconds each.")

        for i, start_ms in enumerate(range(0, len(audio), chunk_length_ms)):
            chunk_num = i + 1
            end_ms = start_ms + chunk_length_ms
            chunk = audio[start_ms:end_ms]

            with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp_audio:
                chunk = chunk.set_frame_rate(16000)
                chunk.export(tmp_audio.name, format="wav")
                temp_files.append(tmp_audio.name)

                chunk_size_mb = os.path.getsize(tmp_audio.name) / 1024 / 1024
                logger.info(f"Transcribing chunk {chunk_num}/{num_chunks} ({chunk_size_mb:.2f} MB)...")
                if progress_callback:
                    progress_callback({"type": "progress", "message": f"Transcribing chunk {chunk_num}/{num_chunks}",
                                       "data": {"chunk": chunk_num, "total": num_chunks, "size_mb": round(chunk_size_mb, 2)}})

                chunk_start = time.monotonic()
                chunk_transcription_text = _transcribe_single_chunk(client, tmp_audio.name, model)
                chunk_elapsed = time.monotonic() - chunk_start

                if with_timestamps:
                    segment = {
                        "text": chunk_transcription_text,
                        "start": start_ms / 1000.0,
                        "end": (start_ms + len(chunk)) / 1000.0
                    }
                    full_transcription_segments.append(segment)
                else:
                    full_transcription_text.append(chunk_transcription_text)

                logger.info(f"Chunk {chunk_num}/{num_chunks} complete in {chunk_elapsed:.2f}s.")
                if progress_callback:
                    progress_callback({"type": "progress", "message": f"Chunk {chunk_num}/{num_chunks} complete in {chunk_elapsed:.2f}s",
                                       "data": {"chunk": chunk_num, "total": num_chunks, "elapsed_s": round(chunk_elapsed, 2)}})

        if with_timestamps:
            return full_transcription_segments
        return " ".join(full_transcription_text)

    except (ValueError, IOError):
        raise
    except Exception as e:
        logger.error(f"An unexpected error occurred during the HF chunking process: {e}")
        raise RuntimeError("An unexpected error occurred during Hugging Face transcription.") from e
    finally:
        for f_path in temp_files:
            try:
                os.remove(f_path)
            except OSError:
                pass
        logger.info("Cleaned up all temporary audio chunks for Hugging Face transcription.")

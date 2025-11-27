import logging
import os
import tempfile

from huggingface_hub import InferenceClient
from huggingface_hub.inference._generated.types import AutomaticSpeechRecognitionOutput
from huggingface_hub.utils import HfHubHTTPError
from pydub import AudioSegment

from src.config.settings import settings

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


def hf_transcript(audio_file_path: str, model: str, provider: str):
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

    full_transcription = []
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
                logger.info(f"Transcribing chunk {chunk_num}/{num_chunks}...")

                chunk_transcription = _transcribe_single_chunk(client, tmp_audio.name, model)
                full_transcription.append(chunk_transcription)
                logger.info(f"Chunk {chunk_num}/{num_chunks} complete.")

        return " ".join(full_transcription)

    except (ValueError, IOError):
        # Re-raise exceptions we expect and handle
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

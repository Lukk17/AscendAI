import logging
import os
import tempfile
import httpx
from openai import OpenAI, APIError

from src.config.settings import settings

logger = logging.getLogger(__name__)

client = OpenAI(
    timeout=httpx.Timeout(settings.API_TIMEOUT_SECONDS),
    max_retries=5,
)

def _transcribe_single_chunk(audio_chunk_path: str, model: str, language: str) -> str:
    """Helper function to transcribe a single audio chunk."""
    try:
        with open(audio_chunk_path, "rb") as audio_file:
            response = client.audio.transcriptions.create(
                model=model,
                file=audio_file,
                language=language
            )
        return response.text
    except APIError as e:
        logger.error(f"OpenAI API error during chunk transcription for model '{model}': {e}")
        raise ValueError(f"OpenAI API failed to process an audio chunk. It may be an invalid model or the API may be unavailable.") from e

def openai_transcript(audio_file_path: str, model: str, language: str):
    """
    Transcribes an audio file using the OpenAI Whisper API.
    Handles large files by automatically splitting them into chunks.
    """
    file_size = os.path.getsize(audio_file_path)
    
    logger.info(
        f"[OpenAI] Transcription Parameters: "
        f"Language='{language}', "
        f"APILimitBytes={settings.OPENAI_API_LIMIT_BYTES}, "
        f"TargetChunkBytes={settings.TARGET_CHUNK_SIZE_BYTES}"
    )

    if file_size < settings.OPENAI_API_LIMIT_BYTES:
        logger.info("File is smaller than the API limit. Transcribing directly.")
        return _transcribe_single_chunk(audio_file_path, model, language)

    logger.info(f"File size ({file_size / 1024 / 1024:.2f} MB) exceeds limit. Splitting into chunks.")
    
    try:
        audio = AudioSegment.from_file(audio_file_path)
    except Exception as e:
        logger.exception("Pydub failed to load the audio file for chunking.")
        raise IOError("Failed to load audio file for chunking. It may be corrupt or an unsupported format.") from e

    ratio = file_size / len(audio)
    chunk_length_ms = int(settings.TARGET_CHUNK_SIZE_BYTES / ratio)
    
    full_transcription = []
    temp_files = []
    
    try:
        num_chunks = (len(audio) // chunk_length_ms) + 1
        logger.info(f"Splitting audio into {num_chunks} chunks of approximately {chunk_length_ms / 1000 / 60:.2f} minutes each.")

        for i, start_ms in enumerate(range(0, len(audio), chunk_length_ms)):
            chunk_num = i + 1
            end_ms = start_ms + chunk_length_ms
            chunk = audio[start_ms:end_ms]
            
            with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp_audio:
                chunk.export(tmp_audio.name, format="wav")
                temp_files.append(tmp_audio.name)
                logger.info(f"Transcribing chunk {chunk_num}/{num_chunks}...")
                
                chunk_transcription = _transcribe_single_chunk(tmp_audio.name, model, language)
                full_transcription.append(chunk_transcription)
                logger.info(f"Chunk {chunk_num}/{num_chunks} complete.")

        return " ".join(full_transcription)

    finally:
        for f_path in temp_files:
            try:
                os.remove(f_path)
            except OSError:
                pass
        logger.info("Cleaned up all temporary audio chunks for OpenAI transcription.")

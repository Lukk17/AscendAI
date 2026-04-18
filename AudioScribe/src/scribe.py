import logging
from typing import Callable, Optional

from src.transcription.huggingface_api_speach_to_text import hf_transcript
from src.transcription.local_speech_to_text import local_speech_transcription_stream
from src.transcription.openai_api_speach_to_text import openai_transcript

logger = logging.getLogger(__name__)


def openai_speech_transcription(audio_file_path: str, model: str, language: str, with_timestamps: bool = False,
                                progress_callback: Optional[Callable[[dict], None]] = None):
    response = openai_transcript(audio_file_path, model, language, with_timestamps, progress_callback=progress_callback)
    if with_timestamps:
        logger.info(f"[OpenAI] {len(response)} segments transcribed\n")
    else:
        logger.info(f"[OpenAI] {response}\n")
    return response


def hf_speech_transcription(audio_file_path: str, model: str, provider: str, with_timestamps: bool = False,
                            progress_callback: Optional[Callable[[dict], None]] = None):
    logger.info("[HF] Starting transcription...")
    response_text = hf_transcript(audio_file_path, model, provider, with_timestamps, progress_callback=progress_callback)
    if with_timestamps:
        logger.info(f"[HF] {len(response_text)} segments transcribed\n")
    else:
        logger.info(f"[HF] {response_text}\n")
    return response_text


async def local_speech_transcription(audio_file_path: str, model_path: str, language: str):
    logger.info("[LLM] Starting transcription stream...")
    async for segment in local_speech_transcription_stream(model_path, audio_file_path, language):
        yield segment

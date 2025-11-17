import logging

from src.transcription.huggingface_api_speach_to_text import hf_transcript
from src.transcription.openai_api_speach_to_text import openai_transcript
from src.transcription.speech_to_text import local_speech_transcription_stream

logger = logging.getLogger(__name__)

def openai_speech_transcription(audio_file_path: str, model: str):
    logger.info("[OpenAI] Starting transcription...")
    response = openai_transcript(audio_file_path, model=model)
    logger.info(f"[OpenAI] {response}\n")
    return response

def hf_speech_transcription(audio_file_path: str, model: str):
    logger.info("[HF] Starting transcription...")
    response = hf_transcript(audio_file_path, model=model)
    logger.info(f"[HF] {response}\n")
    return response

async def local_speech_transcription(audio_file_path: str, model_path: str):
    logger.info("[Master process] Starting transcription stream...")
    async for segment in local_speech_transcription_stream(model_path, audio_file_path):
        yield segment

import logging

from src.transcription.huggingface_api_speach_to_text import hf_transcript
from src.transcription.openai_api_speach_to_text import openai_transcript
from src.transcription.speech_to_text import local_speech_transcription_stream

logger = logging.getLogger(__name__)

def openai_speech_transcription(audio_file_path: str, model: str, language: str):
    response = openai_transcript(audio_file_path, model, language)
    logger.info(f"[OpenAI] {response}\n")
    return response

def hf_speech_transcription(audio_file_path: str, model: str, provider: str):
    logger.info("[HF] Starting transcription...")
    response_text = hf_transcript(audio_file_path, model, provider)
    logger.info(f"[HF] {response_text}\n")
    return response_text

async def local_speech_transcription(audio_file_path: str, model_path: str, language: str):
    logger.info("[LLM] Starting transcription stream...")
    async for segment in local_speech_transcription_stream(model_path, audio_file_path, language):
        yield segment

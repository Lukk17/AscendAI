import logging

from src.transcription.huggingface_api_speach_to_text import hf_transcript
from src.transcription.openai_api_speach_to_text import openai_transcript
from src.transcription.speech_to_text import local_speech_transcription_stream

logger = logging.getLogger(__name__)

def openai_speech_transcription(audio_file_path: str, model: str):
    response = openai_transcript(audio_file_path, model=model)
    logger.info(f"\n[LLM] {response}\n")
    return response

def hf_speech_transcription(audio_file_path: str, model: str):
    logger.info("\n[HF] Starting transcription...")
    response_text = hf_transcript(audio_file_path, model=model)
    logger.info(f"\n[HF] {response_text}\n")
    return response_text

# This function is now a proper async generator that yields from the core stream
async def local_speech_transcription(audio_file_path: str, model_path: str):
    logger.info("\n[LLM] Starting transcription stream...")
    async for segment in local_speech_transcription_stream(model_path, audio_file_path):
        yield segment

import os

from src.transcription.openai_api_speach_to_text import openai_transcript
from src.transcription.speech_to_text import transcript_speach

WHISPER_MODEL_PATH = os.getenv("WHISPER_MODEL_PATH")


def openai_speech_transcription(audio_file_path: str):
    response = openai_transcript(audio_file_path)
    print(f"\n[LLM] {response.text}\n")
    return response.text


def local_speech_transcription(audio_file_path: str):
    print("\n[LLM] Starting transcription...")
    chunks, duration_time = transcript_speach(WHISPER_MODEL_PATH,
                                              audio_file_path)
    transcription_json = [
        {
            "start": float(chunk["timestamp"][0]) if chunk.get("timestamp") else None,
            "end": float(chunk["timestamp"][1]) if chunk.get("timestamp") else None,
            "text": chunk.get("text", "")
        }
        for chunk in chunks
    ]

    print(f"\n[LLM] {duration_time}\n")
    return transcription_json, duration_time

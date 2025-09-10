"""Application constants."""
import os

WHISPER_SAMPLING_RATE = 16000

WHISPER_MODEL_PATH = os.getenv("WHISPER_MODEL_PATH")

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
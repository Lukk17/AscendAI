from typing import Optional, List, Dict, Union

from pydantic_settings import BaseSettings, SettingsConfigDict


class AppSettings(BaseSettings):
    """
    Centralized application settings.
    Reads from environment variables automatically.
    """
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # --- API Keys ---
    OPENAI_API_KEY: Optional[str] = None
    HF_TOKEN: Optional[str] = None

    # --- Server Settings ---
    MCP_HOST: str = "0.0.0.0"
    MCP_PORT: int = 7017
    API_TIMEOUT_SECONDS: int = 120  # 2 minutes

    # --- Transcription Settings ---
    TRANSCRIPTION_LANGUAGE: str = "en"

    # --- Local Transcription (faster-whisper) ---
    CHUNK_LENGTH_MINUTES: int = 15
    TEMPERATURE: List[float] = [0.0, 0.2, 0.4, 0.6, 0.8, 1.0]
    VAD_PARAMETERS: Dict[str, Union[int, float]] = {'min_silence_duration_ms': 1000, 'threshold': 0.4}
    VAD_FILTER: bool = True
    CONDITION_ON_PREVIOUS_TEXT: bool = True
    BEST_OF: int = 5
    BEAM_SIZE: int = 10

    # --- OpenAI Transcription ---
    OPENAI_API_LIMIT_BYTES: int = 25 * 1024 * 1024
    TARGET_CHUNK_SIZE_BYTES: int = 23 * 1024 * 1024

    # --- Hugging Face Transcription ---
    HF_CHUNK_LENGTH_SECONDS: int = 20


# Create a single, importable instance of the settings
settings = AppSettings()

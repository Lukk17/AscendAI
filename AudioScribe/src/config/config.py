from typing import Optional, List, Dict, Union

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
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

    # --- IO Settings ---
    SUPPORTED_AUDIO_EXTENSIONS: List[str] = Field(
        default=["wav", "mp3", "flac", "m4a", "mp4", "mpeg", "mpga", "oga", "ogg", "webm"],
        description="Supported audio file extensions"
    )
    TEMP_FILE_SUFFIX_DEFAULT: str = Field(default="", description="Default suffix for temp files")

    # --- Transcription Settings ---
    TRANSCRIPTION_LANGUAGE: str = "en"

    # --- Local Transcription (faster-whisper) ---
    DEFAULT_MODEL_LOCAL: str = "Systran/faster-whisper-large-v3"
    CHUNK_LENGTH_MINUTES: int = 15
    TEMPERATURE: List[float] = [0.0, 0.2, 0.4, 0.6, 0.8, 1.0]
    VAD_PARAMETERS: Dict[str, Union[int, float]] = {'min_silence_duration_ms': 1000, 'threshold': 0.4}
    VAD_FILTER: bool = True
    CONDITION_ON_PREVIOUS_TEXT: bool = True
    BEST_OF: int = 5
    BEAM_SIZE: int = 10

    # --- OpenAI Transcription ---
    DEFAULT_MODEL_OPENAI: str = "whisper-1"
    # 25 MB - 10% margin = 22.5 MB = 23,592,960 bytes
    OPENAI_API_LIMIT_BYTES: int = int(22.5 * 1024 * 1024)
    # Target 20 MB chunks to be safe (accounting for re-encoding overhead)
    TARGET_CHUNK_SIZE_BYTES: int = 20 * 1024 * 1024

    # --- Hugging Face Transcription ---
    DEFAULT_MODEL_HF: str = "openai/whisper-large-v3"
    HF_CHUNK_LENGTH_SECONDS: int = 20


# Create a single, importable instance of the settings
settings = Settings()

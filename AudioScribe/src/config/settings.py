from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional


class AppSettings(BaseSettings):
    """
    Centralized application settings.
    Reads from environment variables automatically.
    """
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # API Keys
    OPENAI_API_KEY: Optional[str] = None
    HF_TOKEN: Optional[str] = None

    # MCP Server settings
    MCP_HOST: str = "0.0.0.0"
    MCP_PORT: int = 7017

    # Audio processing constants
    WHISPER_SAMPLING_RATE: int = 16000


# Create a single, importable instance of the settings
settings = AppSettings()

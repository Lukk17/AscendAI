from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    API_HOST: str = Field(default="0.0.0.0")
    API_PORT: int = Field(default=7022)
    LOG_LEVEL: str = Field(default="INFO")
    DEFAULT_LANGUAGE: str = Field(default="en")
    DEFAULT_OUTPUT_FORMAT: str = Field(default="json")
    MAX_FILE_SIZE_MB: int = Field(default=50)
    OCR_REQUEST_TIMEOUT: float = Field(default=120.0)


settings = Settings()

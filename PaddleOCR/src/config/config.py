from typing import Annotated, Literal

from pydantic import BeforeValidator, Field
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


def _csv_to_tuple(value: object) -> object:
    """Accept a comma-separated env-var value and turn it into a tuple of strings.

    pydantic-settings treats tuple / list fields as "complex" and tries to JSON-decode
    the env value before any pydantic validator runs. The `NoDecode` marker on the
    annotation below tells the EnvSettingsSource to skip that JSON pass, after which
    this BeforeValidator turns the raw CSV string into a tuple.
    """
    if isinstance(value, str):
        return tuple(item.strip() for item in value.split(",") if item.strip())

    return value


CsvTuple = Annotated[tuple[str, ...], NoDecode, BeforeValidator(_csv_to_tuple)]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    API_HOST: str = Field(default="0.0.0.0")  # noqa: S104  intentional all-interface bind for containerised service
    API_PORT: int = Field(default=7022)
    LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(default="INFO")
    LOG_FORMAT: Literal["json", "color"] = Field(default="json")
    DEFAULT_LANGUAGE: str = Field(default="en", pattern=r"^[a-z]{2,5}$")
    MAX_FILE_SIZE_MB: int = Field(default=50, ge=1, le=1024)
    OCR_REQUEST_TIMEOUT: float = Field(default=120.0, gt=0)
    ENGINE_CACHE_MAX_SIZE: int = Field(default=8, ge=1)
    SUPPORTED_LANGUAGES: CsvTuple = Field(
        default=("en", "pl", "de", "fr", "es", "it", "pt", "nl", "ru", "ch", "ja", "ko")
    )

    MCP_FILE_URI_ROOT: str | None = Field(default=None)
    MCP_ALLOWED_HOSTS: CsvTuple = Field(default=())
    MCP_DOWNLOAD_TIMEOUT_SECONDS: float = Field(default=30.0, gt=0)

    RATE_LIMIT_DEFAULT: str = Field(default="60/minute")
    RATE_LIMIT_OCR: str = Field(default="20/minute")

    OTEL_ENABLED: bool = Field(default=False)
    OTEL_EXPORTER_OTLP_ENDPOINT: str = Field(default="http://otel-collector:4317")


settings = Settings()

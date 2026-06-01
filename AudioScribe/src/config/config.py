from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    """Centralized application settings. Reads from environment variables automatically."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    OPENAI_API_KEY: str | None = None
    HF_TOKEN: str | None = None

    MCP_HOST: str = Field(default="0.0.0.0", description="Bind address")
    MCP_PORT: int = Field(default=7017, description="Service port")
    API_TIMEOUT_SECONDS: int = Field(default=120, description="Upstream HTTP client timeout")

    SUPPORTED_AUDIO_EXTENSIONS: list[str] = Field(
        default=["wav", "mp3", "flac", "m4a", "mp4", "mpeg", "mpga", "oga", "ogg", "webm"],
        description="Audio file extensions accepted on upload + URI download",
    )
    TEMP_FILE_SUFFIX_DEFAULT: str = Field(default="", description="Default temp-file suffix")

    TRANSCRIPTION_LANGUAGE: str = Field(default="en", description="Default ISO 639-1 language code")

    DEFAULT_MODEL_LOCAL: str = "Systran/faster-whisper-large-v3"
    CHUNK_LENGTH_MINUTES: int = 15
    TEMPERATURE: list[float] = Field(default=[0.0, 0.2, 0.4, 0.6, 0.8, 1.0])
    VAD_PARAMETERS: dict[str, int | float] = Field(
        default={"min_silence_duration_ms": 1000, "threshold": 0.4}
    )
    VAD_FILTER: bool = True
    CONDITION_ON_PREVIOUS_TEXT: bool = True
    BEST_OF: int = 5
    BEAM_SIZE: int = 10

    DEFAULT_MODEL_OPENAI: str = "whisper-1"
    OPENAI_API_LIMIT_BYTES: int = int(22.5 * 1024 * 1024)
    TARGET_CHUNK_SIZE_BYTES: int = 20 * 1024 * 1024

    DEFAULT_MODEL_HF: str = "openai/whisper-large-v3"
    HF_CHUNK_LENGTH_SECONDS: int = 20

    FFMPEG_PATH: str = Field(default="ffmpeg", description="Absolute or PATH-resolvable ffmpeg binary")
    FFPROBE_PATH: str = Field(default="ffprobe", description="Absolute or PATH-resolvable ffprobe binary")
    FFMPEG_TIMEOUT_SECONDS: int = Field(default=180, description="Per-invocation ffmpeg timeout")

    DOWNLOAD_FILE_TTL_SECONDS: int = Field(default=300, description="Transcript download TTL")
    DOWNLOAD_CLEANUP_INTERVAL_SECONDS: int = Field(
        default=75, description="Background cleanup sweep interval"
    )

    # 5 GiB cap on both upload + download per the user spec.
    MAX_UPLOAD_BYTES: int = Field(default=5 * 1024 * 1024 * 1024, description="Max multipart upload size")
    MAX_DOWNLOAD_BYTES: int = Field(
        default=5 * 1024 * 1024 * 1024, description="Max HTTP download size for MCP audio_uri"
    )
    MAX_ZIP_UNCOMPRESSED_BYTES: int = Field(
        default=5 * 1024 * 1024 * 1024, description="Max cumulative uncompressed size for Audacity zip"
    )
    UPLOAD_BUFFER_BYTES: int = Field(default=64 * 1024, description="Read/write buffer size for streamed I/O")

    LANGUAGE_PATTERN: str = Field(
        default=r"^[a-zA-Z]{2,8}(?:-[a-zA-Z0-9]{1,8})?$",
        description="Allowed shape for language codes (ISO 639-1/2 with optional region tag)",
    )
    PROVIDER_PATTERN: str = Field(
        default=r"^[a-z][a-z0-9-]{0,32}$", description="Allowed shape for hf_provider"
    )
    MODEL_PATTERN: str = Field(
        default=r"^[A-Za-z0-9._/\-]{1,128}$", description="Allowed shape for model identifiers"
    )

    MCP_FILE_URI_ROOT: str | None = Field(
        default=None,
        description="When set, enables file:// jailed to this path. Unset ⇒ file:// rejected.",
    )
    MCP_ALLOWED_HOSTS: Annotated[list[str], NoDecode] = Field(
        default_factory=list,
        description="Hostnames that bypass the SSRF private-IP check (e.g. docker-internal MinIO).",
    )
    MCP_DOWNLOAD_TIMEOUT_SECONDS: int = Field(
        default=30, description="Total wall-clock budget for an MCP HTTP fetch"
    )

    LOG_LEVEL: str = Field(default="INFO", description="Logging Level")

    @field_validator("MCP_ALLOWED_HOSTS", mode="before")
    @classmethod
    def _split_csv_hosts(cls, value: object) -> object:
        """Accept comma-separated strings from env vars (docker-compose
        ergonomics) in addition to the native JSON-list form pydantic-settings
        expects for `list[str]`."""

        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value


settings = Settings()

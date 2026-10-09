from ascend_python_common.settings import McpFetchSettings, RateLimit, ServiceSettings
from pydantic import Field


class Settings(ServiceSettings, McpFetchSettings):
    """Centralized application settings. Reads from environment variables automatically."""

    OPENAI_API_KEY: str | None = None
    HF_TOKEN: str | None = None

    API_PORT: int = Field(default=7017, ge=1, le=65535, description="Service port")
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

    MCP_DOWNLOAD_TIMEOUT_SECONDS: float = Field(
        default=30.0, gt=0, description="Total wall-clock budget for an MCP HTTP fetch"
    )
    FETCH_MAX_REDIRECT_HOPS: int = Field(
        default=10, ge=0, description="Redirect hops the URI fetch guard follows"
    )

    RATE_LIMIT_DEFAULT: RateLimit = Field(
        default="600/minute", description="Default rate limit for REST routes and MCP tools"
    )
    RATE_LIMIT_TRANSCRIBE: RateLimit = Field(
        default="60/minute", description="Stricter limit on transcription routes and tools"
    )

    REDIS_URL: str = Field(
        default="redis://127.0.0.1:6379/0",
        description="Shared storage for the rate limit windows, one budget per caller",
    )


settings = Settings()

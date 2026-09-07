import math
import tempfile
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BeforeValidator, Field, model_validator
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


def _empty_string_to_none(value: object) -> object:
    """Let an operator restore "unset" over the environment (e.g. `VAR=` in compose).

    Without this, a field whose default is a non-None int can never be overridden back
    to None from the environment: pydantic-settings passes the empty string straight to
    int parsing, which fails, rather than treating it as absent.
    """
    if isinstance(value, str) and value.strip() == "":
        return None

    return value


OptionalInt = Annotated[int | None, BeforeValidator(_empty_string_to_none)]


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
    # Upper bound of 6 accommodates "korean", the longest code PaddleOCR's own model
    # resolution table (paddleocr._pipelines.ocr.PaddleOCR._get_ocr_model_names) accepts
    # among the codes this service declares supported.
    DEFAULT_LANGUAGE: str = Field(default="en", pattern=r"^[a-z]{2,6}$")
    MAX_FILE_SIZE_MB: int = Field(default=50, ge=1, le=1024)
    OCR_REQUEST_TIMEOUT: float = Field(default=120.0, gt=0)
    ENGINE_CACHE_MAX_SIZE: int = Field(default=8, ge=1)
    # "japan" and "korean" are PaddleOCR's own codes for those two languages, not the
    # ISO two-letter "ja"/"ko": the engine's model resolution table (see comment on
    # DEFAULT_LANGUAGE above) returns no model for "ja"/"ko" and raises immediately.
    SUPPORTED_LANGUAGES: CsvTuple = Field(
        default=("en", "pl", "de", "fr", "es", "it", "pt", "nl", "ru", "ch", "japan", "korean")
    )

    MCP_FILE_URI_ROOT: str | None = Field(default=None)
    MCP_ALLOWED_HOSTS: CsvTuple = Field(default=())
    MCP_DOWNLOAD_TIMEOUT_SECONDS: float = Field(default=30.0, gt=0)

    RATE_LIMIT_DEFAULT: str = Field(default="60/minute")
    RATE_LIMIT_OCR: str = Field(default="20/minute")

    OTEL_ENABLED: bool = Field(default=False)
    OTEL_EXPORTER_OTLP_ENDPOINT: str = Field(default="http://otel-collector:4317")

    # The memory argument this change makes rests on there being exactly one job in
    # flight at a time: one call's peak is already most of the container's memory
    # ceiling (see PaddleOCR/openspec/.../design.md, "the measured memory model"), so
    # this value governs both the ProcessPoolExecutor's max_workers and the admission
    # gate's permit count (see src/service/ocr_service.py) and raising it is a memory
    # decision, not a throughput one.
    OCR_WORKER_COUNT: int = Field(default=1, ge=1)
    # First round value above the observed per-page inference floor on this
    # deployment's 4.0 CPU allocation (measured 47-100s per page; see design.md).
    OCR_PAGE_TIMEOUT_SECONDS: float = Field(default=120.0, gt=0)
    # Covers pickling the arguments, the spawn-context handoff and the result trip
    # back, so the worker gives up slightly before the parent does.
    OCR_DISPATCH_MARGIN_SECONDS: float = Field(default=5.0, gt=0)
    # Derived from the fitted memory model at a chosen resident budget, deployed
    # together with OCR_DETECTOR_MAX_SIDE since neither is a safe default alone
    # (design.md Decision 11). Covers the three standard page sizes (A4, Letter,
    # Legal) with the detector bound applied.
    OCR_MAX_INFERENCE_PIXELS: int = Field(default=2_500_000, ge=1)
    # Bounds what text detection sees, independently of the page's own size. Unset
    # keeps today's detection behaviour. See design.md Decision 11.
    OCR_DETECTOR_MAX_SIDE: OptionalInt = Field(default=1536, ge=1)
    OCR_POOL_REBUILD_MAX_CONSECUTIVE: int = Field(default=3, ge=1)
    OCR_SCRATCH_DIR: str = Field(default_factory=lambda: str(Path(tempfile.gettempdir()) / "paddle-ocr-scratch"))

    @model_validator(mode="after")
    def _validate_page_budget(self) -> "Settings":
        if self.OCR_PAGE_TIMEOUT_SECONDS > self.OCR_REQUEST_TIMEOUT:
            raise ValueError(
                f"OCR_PAGE_TIMEOUT_SECONDS ({self.OCR_PAGE_TIMEOUT_SECONDS}) exceeds "
                f"OCR_REQUEST_TIMEOUT ({self.OCR_REQUEST_TIMEOUT}); the derived page limit would be zero"
            )

        return self

    @property
    def OCR_MAX_PAGES(self) -> int:  # matches the ALL_CAPS settings convention above
        return math.floor(self.OCR_REQUEST_TIMEOUT / self.OCR_PAGE_TIMEOUT_SECONDS)

    @property
    def OCR_RECLAMATION_GRACE_SECONDS(self) -> float:  # matches settings convention above
        return self.OCR_PAGE_TIMEOUT_SECONDS + self.OCR_DISPATCH_MARGIN_SECONDS


settings = Settings()

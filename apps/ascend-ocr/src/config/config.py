import re
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Annotated, Final, Literal

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


MODEL_NAME_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._-]*$"
_HTTP_URL_CORE = r"https?://[^\s/?#]+(?:[/?#][^\s]*)?"
HTTP_URL_PATTERN = rf"^{_HTTP_URL_CORE}$"
# The public endpoint is allowed to be empty, which means "the same as the endpoint".
OPTIONAL_HTTP_URL_PATTERN = rf"^(?:{_HTTP_URL_CORE})?$"
# Names AWS accepts for a general-purpose bucket, which is also what the
# S3-compatible store the platform runs accepts: 3 to 63 characters, lower case,
# starting and ending alphanumeric.
S3_BUCKET_NAME_PATTERN = r"^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$"


@dataclass(frozen=True, slots=True)
class ModelPair:
    """The two models one OCR engine is built from, and the key its cache entry lives under."""

    detection: str
    recognition: str

    def __str__(self) -> str:
        return f"{self.detection}/{self.recognition}"


# A language paddleocr's PP-OCRv6 coverage set (_PPOCRV6_LANGS in
# paddleocr/_pipelines/ocr.py) leaves out names its own pair here rather than falling
# back to the library's own resolution a second time (ADR-007). Empty while "ru" and
# "korean", the only two, are switched off (ADR-011).
LANGUAGE_MODEL_OVERRIDES: dict[str, ModelPair] = {}

MCP_ENDPOINT_PATH: Final[str] = "/mcp"


QualityMode = Literal["normal", "high"]

DEFAULT_QUALITY: Final[QualityMode] = "high"

POINTS_PER_INCH: Final[float] = 72.0
# US Legal, the longest standard page this service targets.
LARGEST_PAGE_LONG_SIDE_INCHES: Final[float] = 14.0
# Measured: 28 of 28 lines read correctly at 3.3x, none at 6.85x (ADR-006).
MAX_DETECTOR_DOWNSCALE_RATIO: Final[float] = 3.3
# Measured worst page per detection model in a Linux container with 4 CPUs, 2026-09-25,
# PaddleOCR 3.7.0, high mode, detection bounded to 1536, fastest of three runs: a dense
# Polish A4 prose page at 300 dpi (48 lines, 4000 characters) on the small detector, with
# the engine's threads capped to the container's CPUs, a plain 4200 x 4200 page on the
# server detector (measured before that cap), which no supported language loads and
# which prices a detector nobody measured (ADR-010, ADR-011).
MEASURED_WORST_PAGE_SECONDS: Final[Mapping[str, float]] = MappingProxyType(
    {"PP-OCRv6_small_det": 25.1, "PP-OCRv5_server_det": 96.0}
)

_QUALITY_PAIR_PATTERN = re.compile(r"^\s*(\d+)\s*:\s*(\d+)\s*$")


@dataclass(frozen=True, slots=True)
class QualityProfile:
    """The render resolution and the detector bound one quality mode reads a page with, as one locked pair.

    Raises:
        ValueError: when either number is not positive, or the pair downscales the largest page further than
            MAX_DETECTOR_DOWNSCALE_RATIO.
    """

    render_dpi: int
    detector_max_side: int

    def __post_init__(self) -> None:
        if self.render_dpi <= 0 or self.detector_max_side <= 0:
            raise ValueError(f"Quality pair {self} must hold two positive numbers")

        if self.worst_downscale_ratio > MAX_DETECTOR_DOWNSCALE_RATIO:
            raise ValueError(
                f"Quality pair {self} downscales the largest page {self.worst_downscale_ratio:.2f}x for detection, "
                f"beyond the {MAX_DETECTOR_DOWNSCALE_RATIO}x measured to read every line correctly"
            )

    def __str__(self) -> str:
        return f"{self.render_dpi}:{self.detector_max_side}"

    @property
    def render_scale(self) -> float:
        return self.render_dpi / POINTS_PER_INCH

    @property
    def max_long_side_pixels(self) -> int:
        return round(self.render_dpi * LARGEST_PAGE_LONG_SIDE_INCHES)

    @property
    def max_inference_pixels(self) -> int:
        """The most pixels one page can reach the engine with, which is a square at the largest long side."""
        return self.max_long_side_pixels * self.max_long_side_pixels

    @property
    def worst_downscale_ratio(self) -> float:
        return self.max_long_side_pixels / self.detector_max_side


def _parse_quality_pair(value: object) -> object:
    """Read one mode's pair from the environment, written `<dpi>:<detector bound>`."""
    if not isinstance(value, str):
        return value

    match = _QUALITY_PAIR_PATTERN.match(value)
    if match is None:
        raise ValueError(f"expected '<dpi>:<detector bound>', got {value!r}")

    return QualityProfile(render_dpi=int(match.group(1)), detector_max_side=int(match.group(2)))


QualityPair = Annotated[QualityProfile, NoDecode, BeforeValidator(_parse_quality_pair)]


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
    # resolution table (paddleocr._pipelines.ocr.PaddleOCR._get_ocr_model_names) accepts,
    # so a request in it reaches the unsupported-language refusal rather than a pattern error.
    DEFAULT_LANGUAGE: str = Field(default="en", pattern=r"^[a-z]{2,6}$")
    MAX_FILE_SIZE_MB: int = Field(default=50, ge=1, le=1024)
    # Counts cached engines, not languages: the cache is keyed by the model pair a
    # language resolves to, so every supported language shares one entry. The second slot
    # stays empty until a language is opted back in with a pair of its own, and then keeps
    # it from evicting the pair almost every request uses. The startup banner prices only
    # the engines a supported language can reach, so an unfilled slot costs nothing. See
    # docs/architecture/arc42/07-deployment-view.md.
    ENGINE_CACHE_MAX_SIZE: int = Field(default=2, ge=1)
    # The pair every language PP-OCRv6 covers is read with. Explicit because the library
    # picks the medium member when left to itself, where the small member is better than
    # the previously selected PP-OCRv5_server pair on both published accuracy axes and
    # 2.6x faster - see ADR-007.
    OCR_TEXT_DETECTION_MODEL: str = Field(default="PP-OCRv6_small_det", pattern=MODEL_NAME_PATTERN)
    OCR_TEXT_RECOGNITION_MODEL: str = Field(default="PP-OCRv6_small_rec", pattern=MODEL_NAME_PATTERN)
    # "japan" is PaddleOCR's own code for Japanese, not the ISO two-letter "ja": the
    # engine's model resolution table (see comment on DEFAULT_LANGUAGE above) returns no
    # model for "ja" and raises immediately. "ru" and "korean" are switched off, because
    # the PP-OCRv5 server detector they loaded peaked above the container limit (ADR-011).
    SUPPORTED_LANGUAGES: CsvTuple = Field(default=("en", "pl", "de", "fr", "es", "it", "pt", "nl", "ch", "japan"))

    MCP_FILE_URI_ROOT: str | None = Field(default=None)
    MCP_ALLOWED_HOSTS: CsvTuple = Field(default=())
    MCP_DOWNLOAD_TIMEOUT_SECONDS: float = Field(default=30.0, gt=0)

    RATE_LIMIT_DEFAULT: str = Field(default="60/minute")
    RATE_LIMIT_OCR: str = Field(default="20/minute")

    OTEL_ENABLED: bool = Field(default=False)
    OTEL_EXPORTER_OTLP_ENDPOINT: str = Field(default="http://otel-collector:4317")

    # One document is read at a time, and every promise the queue makes about how long
    # a submission waits is computed against that. This value governs both the
    # ProcessPoolExecutor's max_workers and the admission gate's permit count (see
    # src/service/ocr_service.py), so raising it is a change to the queue's promise as
    # well as to throughput, and it multiplies the service's memory peak.
    OCR_WORKER_COUNT: int = Field(default=1, ge=1)
    # The service's only configured time input: a page is allowed this multiple of its
    # own engine's worst measured page, and every duration the service enforces derives
    # from that allowance (ADR-010).
    OCR_PAGE_ALLOWANCE_HEADROOM: float = Field(default=4.5, gt=0)
    # Covers pickling the arguments, the spawn-context handoff and the result trip
    # back, so the worker gives up slightly before the parent does.
    OCR_DISPATCH_MARGIN_SECONDS: float = Field(default=5.0, gt=0)
    # One setting per mode, each holding both halves of its pair (ADR-010).
    OCR_QUALITY_NORMAL: QualityPair = Field(default=QualityProfile(render_dpi=150, detector_max_side=1024))
    OCR_QUALITY_HIGH: QualityPair = Field(default=QualityProfile(render_dpi=300, detector_max_side=1536))
    # Pillow's own decompression-bomb threshold, and the value its global guard is set to.
    OCR_MAX_SOURCE_PIXELS: int = Field(default=89_478_485, ge=1)
    OCR_POOL_REBUILD_MAX_CONSECUTIVE: int = Field(default=3, ge=1)

    # How long one document may hold the single worker and everything queued behind it.
    # At the worst measured page a hundred pages is about 47 minutes, and at the allowance it
    # is the derived reading ceiling below. Memory is the cross-check rather than the
    # derivation: one straightened page peaked at 2771 MiB whatever the page count, plus
    # roughly 11.5 MiB a page retained.
    OCR_JOB_MAX_PAGES: int = Field(default=100, ge=1)
    OCR_JOBS_DIR: str = Field(default_factory=lambda: str(Path(tempfile.gettempdir()) / "ascend-ocr-jobs"))
    # Counted from when the work finished, so a caller whose polling died has a working
    # session to restart it and collect. It is also how long a document's own text sits
    # in the result bucket.
    OCR_JOB_RETENTION_SECONDS: float = Field(default=3600.0, gt=0)
    # A backstop against a defect rather than an eviction policy a caller meets: the
    # single worker cannot produce this many finished records inside one retention
    # window at the measured per-page cost.
    OCR_JOB_MAX_RETAINED: int = Field(default=1000, ge=1)
    # Bounds the wait, which is the only thing a waiting caller cares about: the pages
    # already waiting multiplied by the per-page allowance is the worst case.
    OCR_JOB_QUEUE_MAX_PAGES: int = Field(default=200, ge=1)
    # Bounds the disk the waiting submissions hold: a chosen 400 MB budget divided by
    # MAX_FILE_SIZE_MB. It also bounds the list operation, which can never return more
    # than this many waiting entries plus the one running document.
    OCR_JOB_QUEUE_MAX_DOCUMENTS: int = Field(default=8, ge=1)

    # The address this service writes results to. Mirrors the ascend-ai-agent's own
    # app.s3.* properties for the same store, including why a public endpoint exists:
    # the address a presigned URL is signed against is not always the one this service
    # reaches the store on.
    OCR_RESULT_S3_ENDPOINT: str = Field(default="http://localhost:9070", pattern=HTTP_URL_PATTERN)
    OCR_RESULT_S3_PUBLIC_ENDPOINT: str = Field(default="", pattern=OPTIONAL_HTTP_URL_PATTERN)
    # Its own bucket rather than the agent's knowledge-base, whose contents the agent's
    # manual ingestion lists and indexes as source documents.
    OCR_RESULT_S3_BUCKET: str = Field(default="ocr-results", pattern=S3_BUCKET_NAME_PATTERN)
    OCR_RESULT_S3_ACCESS_KEY: str = Field(default="")
    OCR_RESULT_S3_SECRET_KEY: str = Field(default="")

    @model_validator(mode="after")
    def _default_public_endpoint_to_endpoint(self) -> "Settings":
        if not self.OCR_RESULT_S3_PUBLIC_ENDPOINT:
            self.OCR_RESULT_S3_PUBLIC_ENDPOINT = self.OCR_RESULT_S3_ENDPOINT

        return self

    @model_validator(mode="after")
    def _validate_queue_holds_one_maximal_document(self) -> "Settings":
        if self.OCR_JOB_QUEUE_MAX_PAGES < self.OCR_JOB_MAX_PAGES:
            raise ValueError(
                f"OCR_JOB_QUEUE_MAX_PAGES ({self.OCR_JOB_QUEUE_MAX_PAGES}) is below OCR_JOB_MAX_PAGES "
                f"({self.OCR_JOB_MAX_PAGES}); a single maximal document could never be queued"
            )

        return self

    def quality_profile(self, mode: QualityMode) -> QualityProfile:
        return self.OCR_QUALITY_HIGH if mode == "high" else self.OCR_QUALITY_NORMAL

    def model_pair(self, language: str) -> ModelPair:
        """Return the detection and recognition models a language is read with."""
        override = LANGUAGE_MODEL_OVERRIDES.get(language)
        if override is not None:
            return override

        return ModelPair(self.OCR_TEXT_DETECTION_MODEL, self.OCR_TEXT_RECOGNITION_MODEL)

    def reachable_model_pairs(self) -> frozenset[ModelPair]:
        """Return every engine an accepted language can load, the default language included."""
        return frozenset(self.model_pair(language) for language in {*self.SUPPORTED_LANGUAGES, self.DEFAULT_LANGUAGE})

    def page_allowance_seconds(self, pair: ModelPair) -> float:
        """How long one page may take on this engine, in either quality mode.

        A detection model nobody measured is allowed the slowest measured page.
        """
        measured = MEASURED_WORST_PAGE_SECONDS.get(pair.detection, max(MEASURED_WORST_PAGE_SECONDS.values()))

        return self.OCR_PAGE_ALLOWANCE_HEADROOM * measured

    def reclamation_grace_seconds(self, pair: ModelPair) -> float:
        """How long past its budget a worker reading on this engine is waited for before it is replaced."""
        return self.page_allowance_seconds(pair) + self.OCR_DISPATCH_MARGIN_SECONDS

    @property
    def OCR_WORST_PAGE_ALLOWANCE_SECONDS(self) -> float:  # matches settings convention above
        """The allowance of the slowest engine any accepted language can load."""
        return max(self.page_allowance_seconds(pair) for pair in self.reachable_model_pairs())

    @property
    def OCR_JOB_READING_CEILING_SECONDS(self) -> float:  # matches settings convention above
        """The longest one document may be read for."""
        return self.OCR_JOB_MAX_PAGES * self.OCR_WORST_PAGE_ALLOWANCE_SECONDS

    @property
    def OCR_JOB_MAX_LIFETIME_SECONDS(self) -> float:  # matches settings convention above
        """The longest wait the queue admits plus the longest read, past which a record is wedged."""
        return (self.OCR_JOB_QUEUE_MAX_PAGES + self.OCR_JOB_MAX_PAGES) * self.OCR_WORST_PAGE_ALLOWANCE_SECONDS


settings = Settings()

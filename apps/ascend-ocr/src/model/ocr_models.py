from typing import Final, Literal

from pydantic import BaseModel, Field

from src.config.config import DEFAULT_QUALITY, QualityMode

SCHEMA_VERSION: Literal["1"] = "1"

LANGUAGE_PATTERN: Final[str] = r"^[a-z]{2,6}$"

# An identifier is the only thing standing between a caller and a document's extracted
# text (see ADR-009), so it is 128 bits from a cryptographic source rather than a
# counter, and base64url of 16 bytes is always 22 characters.
JOB_ID_BYTES: Final[int] = 16
JOB_ID_LENGTH: Final[int] = 22
JOB_ID_PATTERN: Final[str] = rf"^[A-Za-z0-9_-]{{{JOB_ID_LENGTH}}}$"

JobState = Literal["waiting", "running", "succeeded", "failed", "cancelled"]

TERMINAL_JOB_STATES: Final[frozenset[str]] = frozenset({"succeeded", "failed", "cancelled"})

# Record-level failure reasons. They live inside a job record and are never HTTP
# statuses, because the request that reads a failed record succeeded (ADR-002).
FAILURE_SERVICE_RESTARTED: Final[str] = "SERVICE_RESTARTED"
FAILURE_LIFETIME_EXCEEDED: Final[str] = "LIFETIME_EXCEEDED"
FAILURE_RESULT_STORE_UNAVAILABLE: Final[str] = "RESULT_STORE_UNAVAILABLE"

# Both say nothing was learned about the document, so resubmitting it is worthwhile.
# LIFETIME_EXCEEDED is deliberately absent: a record wedged past the longest legitimate
# wait plus the longest legitimate read is a defect, and resubmitting invites it again.
RETRYABLE_FAILURE_REASONS: Final[frozenset[str]] = frozenset(
    {FAILURE_SERVICE_RESTARTED, FAILURE_RESULT_STORE_UNAVAILABLE}
)


def _is_absent(value: object) -> bool:
    return value is None


class OcrTextLine(BaseModel):
    text: str = Field(max_length=10_000)
    confidence: float = Field(ge=0.0, le=1.0)
    bounding_box: list[list[float]] = Field(max_length=32)


class OcrPageResult(BaseModel):
    page_number: int = Field(ge=1)
    lines: list[OcrTextLine]


class OcrJsonResponse(BaseModel):
    schema_version: Literal["1"] = SCHEMA_VERSION
    filename: str = Field(max_length=512)
    # Upper bound of 6 accommodates "korean", the longest PaddleOCR-native language
    # code, switched off for now (see config.SUPPORTED_LANGUAGES).
    language: str = Field(pattern=LANGUAGE_PATTERN)
    pages: list[OcrPageResult]
    processing_time_seconds: float = Field(ge=0.0)


class JobResultLocation(BaseModel):
    """Where a finished document's Markdown lives, as it is persisted in the record."""

    bucket: str = Field(min_length=1, max_length=63)
    key: str = Field(min_length=1, max_length=1024)


class JobRecord(BaseModel):
    """One piece of work, as it is persisted under OCR_JOBS_DIR and read on every poll."""

    job_id: str = Field(pattern=JOB_ID_PATTERN)
    state: JobState
    surface: Literal["rest", "mcp"]
    filename: str = Field(max_length=512)
    language: str = Field(pattern=LANGUAGE_PATTERN)
    # Defaulted so a record written before quality modes existed still reads.
    quality: QualityMode = DEFAULT_QUALITY
    # Defaulted so a record written before straightening existed still reads.
    straighten: bool = False
    page_count: int = Field(ge=1)
    submitted_at: float = Field(ge=0.0)
    started_at: float | None = Field(default=None, ge=0.0)
    finished_at: float | None = Field(default=None, ge=0.0)
    pages_done: int = Field(default=0, ge=0)
    processing_time_seconds: float | None = Field(default=None, ge=0.0)
    error_code: str | None = Field(default=None, max_length=64)
    error_reason: str | None = Field(default=None, max_length=512)
    retryable: bool = False
    result: JobResultLocation | None = None
    # The submitting request's trace context, so the inference that happens minutes
    # later is still a child of the call that asked for it rather than a root span.
    trace_carrier: dict[str, str] | None = None

    @property
    def is_terminal(self) -> bool:
        return self.state in TERMINAL_JOB_STATES


class JobResultReference(BaseModel):
    """The address of a finished result, plus the description that does not grow with it."""

    bucket: str
    key: str
    url: str
    schema_version: Literal["1"] = SCHEMA_VERSION
    filename: str = Field(max_length=512)
    language: str = Field(pattern=LANGUAGE_PATTERN)
    quality: QualityMode
    straighten: bool
    page_count: int = Field(ge=1)
    processing_time_seconds: float = Field(ge=0.0)


class JobSubmitResponse(BaseModel):
    job_id: str = Field(pattern=JOB_ID_PATTERN)
    state: JobState
    page_count: int = Field(ge=1)
    queue_position: int = Field(ge=0)
    pages_ahead: int = Field(ge=0)
    status_url: str
    poll_after_seconds: float = Field(gt=0.0)


class JobStatusResponse(BaseModel):
    job_id: str = Field(pattern=JOB_ID_PATTERN)
    state: JobState
    page_count: int = Field(ge=1)
    pages_done: int = Field(ge=0)
    submitted_at: float = Field(ge=0.0)
    started_at: float | None = Field(default=None, ge=0.0)
    finished_at: float | None = Field(default=None, ge=0.0)
    queue_position: int | None = Field(default=None, ge=0)
    pages_ahead: int | None = Field(default=None, ge=0)
    # Absent on a terminal state, so its absence is itself the signal that there is
    # nothing left to ask.
    poll_after_seconds: float | None = Field(default=None, gt=0.0, exclude_if=_is_absent)
    error_code: str | None = Field(default=None, max_length=64)
    error_reason: str | None = Field(default=None, max_length=512)
    retryable: bool = False
    result: JobResultReference | None = None


class JobListEntry(BaseModel):
    job_id: str = Field(pattern=JOB_ID_PATTERN)
    state: Literal["waiting", "running"]
    page_count: int = Field(ge=1)
    pages_done: int = Field(ge=0)
    elapsed_seconds: float = Field(ge=0.0)
    queue_position: int | None = Field(default=None, ge=0)


class JobListResponse(BaseModel):
    jobs: list[JobListEntry]


class HealthResponse(BaseModel):
    status: Literal["ok", "warming-up"] = "ok"
    version: str


class ReadinessResponse(BaseModel):
    status: Literal["ready", "not-ready"]
    version: str
    engine_warm: bool
    accepting_work: bool
    jobs_queued: int = Field(ge=0)
    jobs_running: int = Field(ge=0)

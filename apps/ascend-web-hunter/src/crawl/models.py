import fnmatch
from datetime import UTC, datetime
from typing import Any, Final, Literal

from pydantic import AnyUrl, BaseModel, Field, model_validator

from src.config.config import settings
from src.reader.web_reader import OutputFormat

DEFAULT_TENANT: Final[str] = "default"
TENANT_PATTERN: Final[str] = r"^[a-z0-9-]{1,64}$"

JobState = Literal["waiting", "running", "succeeded", "failed", "cancelled"]


class JobNotFoundError(Exception):
    def __init__(self, job_id: str):
        self.job_id = job_id
        self.message = f"Crawl job {job_id} was not found."
        super().__init__(self.message)


class InvalidTenantError(ValueError):
    def __init__(self, tenant: str):
        self.tenant = tenant
        self.message = (
            f"Tenant {tenant!r} is not a value of [a-z0-9-] with 1 to 64 characters."
        )
        super().__init__(self.message)


class CrawlRequest(BaseModel):
    seeds: list[AnyUrl] = Field(min_length=1, max_length=settings.CRAWL_MAX_SEEDS)
    include_patterns: list[str] = Field(
        default_factory=list, max_length=settings.CRAWL_MAX_PATTERNS
    )
    exclude_patterns: list[str] = Field(
        default_factory=list, max_length=settings.CRAWL_MAX_PATTERNS
    )
    max_depth: int = Field(
        default=settings.CRAWL_DEFAULT_DEPTH,
        ge=0,
        le=settings.CRAWL_MAX_DEPTH,
    )
    page_budget: int = Field(
        default=settings.CRAWL_DEFAULT_PAGE_BUDGET,
        ge=1,
        le=settings.CRAWL_MAX_PAGES,
    )
    same_domain_only: bool = True
    respect_robots: bool = True
    output_format: OutputFormat = "text"
    extraction_schema: dict[str, Any] | None = None
    profile: str | None = None

    @model_validator(mode="after")
    def _enforce_current_bounds(self) -> "CrawlRequest":
        bounds = (
            ("seeds", len(self.seeds), settings.CRAWL_MAX_SEEDS),
            ("include_patterns", len(self.include_patterns), settings.CRAWL_MAX_PATTERNS),
            ("exclude_patterns", len(self.exclude_patterns), settings.CRAWL_MAX_PATTERNS),
            ("max_depth", self.max_depth, settings.CRAWL_MAX_DEPTH),
            ("page_budget", self.page_budget, settings.CRAWL_MAX_PAGES),
        )
        for name, value, limit in bounds:
            if value > limit:
                raise ValueError(f"{name} of {value} is above the current limit {limit}")
        return self


class JobCounts(BaseModel):
    queued: int = Field(default=0, ge=0)
    fetched: int = Field(default=0, ge=0)
    unchanged: int = Field(default=0, ge=0)
    failed: int = Field(default=0, ge=0)
    skipped_unsafe: int = Field(default=0, ge=0)

class JobRecord(BaseModel):
    job_id: str = Field(min_length=1)
    tenant_id: str = Field(pattern=TENANT_PATTERN)
    state: JobState = "waiting"
    request: CrawlRequest
    counts: JobCounts = Field(default_factory=JobCounts)
    pages_ndjson_key: str | None = None
    error: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


def match_glob(patterns: list[str], path: str) -> bool:
    return any(fnmatch.fnmatchcase(path, pattern) for pattern in patterns)


class CrawlSubmission(BaseModel):
    job_id: str
    state: JobState = "waiting"
    poll_after_seconds: int = Field(ge=1)


class CrawlJobView(BaseModel):
    job_id: str
    tenant_id: str
    state: JobState
    counts: JobCounts
    pages_ndjson_key: str | None = None
    error: str | None = None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_record(cls, record: "JobRecord") -> "CrawlJobView":
        return cls(
            job_id=record.job_id,
            tenant_id=record.tenant_id,
            state=record.state,
            counts=record.counts,
            pages_ndjson_key=record.pages_ndjson_key,
            error=record.error,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )


class CrawlJobList(BaseModel):
    jobs: list[CrawlJobView]

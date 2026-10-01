import time
from typing import TYPE_CHECKING, Final, Literal

from src.api.exception_handlers import FileSizeExceededError, JobNotFoundError, UnsupportedLanguageError
from src.api.limits import enforce_page_limit, inspect_input
from src.api.mime_sniffer import sniff_mime
from src.config.config import QualityMode, settings
from src.config.logging_config import get_logger
from src.model.ocr_models import (
    JobListEntry,
    JobListResponse,
    JobRecord,
    JobResultReference,
    JobStatusResponse,
    JobSubmitResponse,
)
from src.observability.tracing import inject_trace_context
from src.service.job_runner import JobRunner, poll_hint_seconds
from src.service.job_store import JobStore, log_transition, new_job_id
from src.service.result_store import result_store

if TYPE_CHECKING:
    from src.service.result_store import ResultLinkSigner

logger = get_logger(__name__)

BYTES_PER_MB: Final[int] = 1024 * 1024
JOBS_PATH: Final[str] = "/v1/ocr/jobs"

Surface = Literal["rest", "mcp"]


class JobService:
    """The four operations, above one queue and one store, so the two surfaces cannot drift.

    Everything a caller can observe about a job is built here: both surfaces call these
    methods and neither adds a guard, a state or a bound the other does not have.
    """

    def __init__(self, store: JobStore, results: "ResultLinkSigner", runner: JobRunner) -> None:
        self._store = store
        self._results = results
        self._runner = runner

    async def submit(
        self,
        file_bytes: bytes,
        filename: str,
        language: str,
        quality: QualityMode,
        surface: Surface,
        *,
        straighten: bool = False,
    ) -> JobSubmitResponse:
        """Accept a document for later collection, or refuse it before anything is queued.

        Raises:
            UnsupportedLanguageError: when the language is not in SUPPORTED_LANGUAGES.
            FileSizeExceededError: on the byte cap, the source pixel ceiling or the page ceiling.
            UnsupportedFileTypeError: when the header is not one this service reads.
            QueueFullError: when the queue is at either of its two bounds.
        """
        ensure_language_supported(language)
        enforce_byte_cap(len(file_bytes))
        shape = inspect_input(file_bytes, sniff_mime(file_bytes))
        enforce_page_limit(shape)

        record = JobRecord(
            job_id=new_job_id(),
            state="waiting",
            surface=surface,
            filename=filename,
            language=language,
            quality=quality,
            straighten=straighten,
            page_count=shape.page_count,
            submitted_at=time.time(),
            trace_carrier=inject_trace_context(),
        )

        self._runner.reserve(record.page_count)
        try:
            await self._store.create(record, file_bytes)
        finally:
            self._runner.release(record.page_count)

        self._runner.admit(record)
        log_transition(record)

        return JobSubmitResponse(
            job_id=record.job_id,
            state=record.state,
            page_count=record.page_count,
            queue_position=self._position_of(record.job_id),
            pages_ahead=self._runner.pages_ahead_of(record.job_id),
            status_url=f"{JOBS_PATH}/{record.job_id}",
            poll_after_seconds=poll_hint_seconds(self._runner.seconds_remaining_for(record.job_id)),
        )

    def status(self, job_id: str) -> JobStatusResponse:
        """Return everything observable about one job.

        Raises:
            JobNotFoundError: when the identifier is malformed, unknown or expired.
        """
        record = self._store.read(job_id)

        if record.is_terminal:
            return self._terminal_status(record)

        is_waiting = record.state == "waiting"

        return JobStatusResponse(
            job_id=record.job_id,
            state=record.state,
            page_count=record.page_count,
            pages_done=self._runner.pages_done_of(record.job_id),
            submitted_at=record.submitted_at,
            started_at=record.started_at,
            queue_position=self._position_of(record.job_id) if is_waiting else None,
            pages_ahead=self._runner.pages_ahead_of(record.job_id) if is_waiting else None,
            poll_after_seconds=poll_hint_seconds(self._runner.seconds_remaining_for(record.job_id)),
        )

    def list_jobs(self) -> JobListResponse:
        """List what the service is doing now, which is bounded by the queue's own document bound."""
        now = time.time()
        entries: list[JobListEntry] = []

        for position, (entry, state) in enumerate(self._runner.entries_in_flight()):
            try:
                record = self._store.read(entry.job_id)
            except JobNotFoundError:
                logger.warning("Job %s is in flight with no readable record, omitting it", entry.job_id)

                continue

            entries.append(
                JobListEntry(
                    job_id=record.job_id,
                    state="running" if state == "running" else "waiting",
                    page_count=record.page_count,
                    pages_done=self._runner.pages_done_of(record.job_id),
                    elapsed_seconds=max(now - (record.started_at or record.submitted_at), 0.0),
                    queue_position=None if state == "running" else position,
                )
            )

        return JobListResponse(jobs=entries)

    async def delete(self, job_id: str) -> None:
        """Cancel unfinished work, or forget finished work along with its stored result.

        Raises:
            JobNotFoundError: when the identifier is malformed, unknown or expired.
        """
        record = self._store.read(job_id)

        if record.is_terminal:
            await self._store.delete(record)

            return

        self._runner.cancel(record)

    def _terminal_status(self, record: JobRecord) -> JobStatusResponse:
        return JobStatusResponse(
            job_id=record.job_id,
            state=record.state,
            page_count=record.page_count,
            pages_done=record.pages_done,
            submitted_at=record.submitted_at,
            started_at=record.started_at,
            finished_at=record.finished_at,
            error_code=record.error_code,
            error_reason=record.error_reason,
            retryable=record.retryable,
            result=self._result_reference(record),
        )

    def _result_reference(self, record: JobRecord) -> JobResultReference | None:
        if record.result is None:
            return None

        return JobResultReference(
            bucket=record.result.bucket,
            key=record.result.key,
            url=self._results.presigned_url(record.result.key, self._remaining_retention(record)),
            filename=record.filename,
            language=record.language,
            quality=record.quality,
            straighten=record.straighten,
            page_count=record.page_count,
            processing_time_seconds=record.processing_time_seconds or 0.0,
        )

    def _remaining_retention(self, record: JobRecord) -> float:
        """How long the object has left, so a link can never outlive what it points at."""
        finished_at = record.finished_at or record.submitted_at

        return settings.OCR_JOB_RETENTION_SECONDS - (time.time() - finished_at)

    def _position_of(self, job_id: str) -> int:
        position = self._runner.position_of(job_id)

        return 0 if position is None else position


def ensure_language_supported(language: str) -> None:
    """Refuse a language this service does not read, identically on both surfaces.

    Raises:
        UnsupportedLanguageError: naming every supported language and never the one asked for.
    """
    if language in settings.SUPPORTED_LANGUAGES:
        return

    supported = ", ".join(settings.SUPPORTED_LANGUAGES)
    raise UnsupportedLanguageError(f"Language is not supported. Supported languages: {supported}")


def enforce_byte_cap(size_bytes: int) -> None:
    """Refuse a submission larger than the byte cap, identically on both surfaces.

    Raises:
        FileSizeExceededError: when the submission exceeds MAX_FILE_SIZE_MB.
    """
    max_size_bytes = settings.MAX_FILE_SIZE_MB * BYTES_PER_MB
    if size_bytes > max_size_bytes:
        raise FileSizeExceededError(f"File size {size_bytes} bytes exceeds maximum {settings.MAX_FILE_SIZE_MB} MB")


# The composition root for the job path. Both surfaces and the lifespan import these
# names, so there is one store, one queue and one result store in the process.
job_store = JobStore(result_store)
job_runner = JobRunner(job_store, result_store)
job_service = JobService(job_store, result_store, job_runner)

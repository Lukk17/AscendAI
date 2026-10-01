import asyncio
import os
import re
import secrets
import time
from pathlib import Path
from typing import TYPE_CHECKING, Final

from pydantic import ValidationError

from src.api.exception_handlers import JobNotFoundError
from src.config.config import settings
from src.config.logging_config import get_logger
from src.model.ocr_models import (
    FAILURE_LIFETIME_EXCEEDED,
    FAILURE_SERVICE_RESTARTED,
    JOB_ID_BYTES,
    JOB_ID_PATTERN,
    RETRYABLE_FAILURE_REASONS,
    JobRecord,
    JobResultLocation,
    JobState,
)
from src.observability.metrics import JOB_DURATION_SECONDS, JOBS_TOTAL

if TYPE_CHECKING:
    from src.service.result_store import ResultDeleter


logger = get_logger(__name__)

_JOB_ID_RE: Final[re.Pattern[str]] = re.compile(JOB_ID_PATTERN)

RECORD_SUFFIX: Final[str] = ".json"
INPUT_SUFFIX: Final[str] = ".input"
PROGRESS_SUFFIX: Final[str] = ".progress"
_TEMP_SUFFIX: Final[str] = ".tmp"


def log_transition(record: JobRecord) -> None:
    """Emit the one line a state transition produces, carrying no document text and no address."""
    logger.info(
        "Job %s -> %s (pages=%d, reason=%s)",
        record.job_id,
        record.state,
        record.page_count,
        record.error_code or "-",
    )


def new_job_id() -> str:
    """Return an identifier with 128 bits of entropy, URL-safe and never derived from the input."""
    return secrets.token_urlsafe(JOB_ID_BYTES)


def validate_job_id(candidate: str) -> str:
    """Return the identifier unchanged, or refuse it before any path or object key is built.

    Raises:
        JobNotFoundError: when the candidate is not shaped like an identifier this
            service issues, so a traversal attempt is answered exactly like a typo.
    """
    if not _JOB_ID_RE.match(candidate):
        raise JobNotFoundError(f"Identifier is not shaped like a job identifier: {candidate[:64]!r}")

    return candidate


def jobs_dir() -> Path:
    directory = Path(settings.OCR_JOBS_DIR)
    directory.mkdir(parents=True, exist_ok=True)

    return directory


def job_path(job_id: str, suffix: str) -> Path:
    # Validated before the directory is even resolved, so a traversal-shaped identifier
    # never reaches the filesystem at all.
    name = f"{validate_job_id(job_id)}{suffix}"

    return jobs_dir() / name


def atomic_write_bytes(path: Path, payload: bytes) -> None:
    """Write through a temporary file in the same directory, so no reader sees a partial file."""
    temp_path = path.with_name(f"{path.name}{_TEMP_SUFFIX}")
    temp_path.write_bytes(payload)
    os.replace(temp_path, path)


def write_progress(job_id: str, pages_done: int) -> None:
    """Record how many pages are read. Called from the worker process, between pages."""
    atomic_write_bytes(job_path(job_id, PROGRESS_SUFFIX), str(pages_done).encode("utf-8"))


def read_progress(job_id: str) -> int:
    """Return the pages read so far, or zero when the worker has not finished one yet."""
    try:
        return int(job_path(job_id, PROGRESS_SUFFIX).read_bytes())
    except (OSError, ValueError):
        return 0


class JobStore:
    """Job records on disk: one JSON record per job, its submitted bytes, and its progress.

    Every write goes through a temporary file plus an atomic replace, and the API
    process is the only writer of a record, so a poll never observes half of one.
    """

    def __init__(self, result_deleter: "ResultDeleter") -> None:
        self._result_deleter = result_deleter

    async def create(self, record: JobRecord, payload: bytes) -> None:
        """Persist the submitted bytes and then the record, so a record always has its input."""
        await asyncio.to_thread(atomic_write_bytes, job_path(record.job_id, INPUT_SUFFIX), payload)
        self.write(record)

    def write(self, record: JobRecord) -> None:
        atomic_write_bytes(job_path(record.job_id, RECORD_SUFFIX), record.model_dump_json().encode("utf-8"))

    def read(self, job_id: str) -> JobRecord:
        """Return the record for an identifier.

        Raises:
            JobNotFoundError: when the identifier is malformed, unknown or expired.
        """
        path = job_path(job_id, RECORD_SUFFIX)
        try:
            raw = path.read_bytes()
        except OSError as exc:
            raise JobNotFoundError(f"No record for job {job_id}") from exc

        try:
            return JobRecord.model_validate_json(raw)
        except ValidationError as exc:
            raise JobNotFoundError(f"Record for job {job_id} is unreadable") from exc

    def exists(self, job_id: str) -> bool:
        return job_path(job_id, RECORD_SUFFIX).exists()

    async def read_input(self, job_id: str) -> bytes:
        """Return the submitted bytes.

        Raises:
            JobNotFoundError: when the submitted bytes are no longer held.
        """
        path = job_path(job_id, INPUT_SUFFIX)
        try:
            return await asyncio.to_thread(path.read_bytes)
        except OSError as exc:
            raise JobNotFoundError(f"No submitted bytes for job {job_id}") from exc

    def delete_input(self, job_id: str) -> None:
        _remove(job_path(job_id, INPUT_SUFFIX))

    async def delete(self, record: JobRecord) -> None:
        """Remove a job entirely: its result object first, then its record and its files.

        Raises:
            Exception: whatever the result store raises, so a record is never removed
                while the object it names is still in the bucket.
        """
        await self._delete_result_object(record)
        for suffix in (RECORD_SUFFIX, INPUT_SUFFIX, PROGRESS_SUFFIX):
            _remove(job_path(record.job_id, suffix))

    def records(self) -> list[JobRecord]:
        """Return every readable record, oldest submission first."""
        found: list[JobRecord] = []
        for path in sorted(jobs_dir().glob(f"*{RECORD_SUFFIX}")):
            try:
                found.append(JobRecord.model_validate_json(path.read_bytes()))
            except (OSError, ValidationError):
                logger.warning("Ignoring unreadable job record: %s", path.name)

        return sorted(found, key=lambda record: record.submitted_at)

    def recover_after_restart(self) -> list[JobRecord]:
        """Fail every record that was waiting or running, so nothing is polled forever.

        Resuming is deliberately not attempted: the service cannot know whether the
        document it was reading is what brought it down, so a resume would feed the
        killer its own input again.
        """
        recovered: list[JobRecord] = []
        for record in self.records():
            if record.is_terminal:
                continue

            recovered.append(self.fail(record, FAILURE_SERVICE_RESTARTED, "Service restarted before the work finished"))

        return recovered

    def start(self, job_id: str, started_at: float) -> JobRecord | None:
        """Record waiting work as running, or return nothing when it is no longer waiting.

        The read and the write have no await between them, so a cancel on the same event
        loop lands either before the check or after the write, never in between.
        """
        try:
            record = self.read(job_id)
        except JobNotFoundError:
            return None

        if record.state != "waiting":
            return None

        record.state = "running"
        record.started_at = started_at
        self.write(record)

        return record

    def fail(self, record: JobRecord, code: str, detail: str) -> JobRecord:
        """Write a terminal failed record carrying the reason, whether it is worth resubmitting, and the pages read."""
        record.error_code = code
        record.error_reason = detail
        record.retryable = code in RETRYABLE_FAILURE_REASONS

        return self._finish_before_the_last_page(record, "failed")

    def cancel(self, record: JobRecord) -> JobRecord:
        """Write a terminal cancelled record, which is not a failure, carries no result, and keeps the pages read."""
        return self._finish_before_the_last_page(record, "cancelled")

    def succeed(self, record: JobRecord, location: JobResultLocation, processing_time_seconds: float) -> JobRecord:
        """Write a terminal successful record, which is only ever done once the object is in the bucket."""
        record.result = location
        record.processing_time_seconds = processing_time_seconds
        record.pages_done = record.page_count

        return self._finish(record, "succeeded")

    def _finish_before_the_last_page(self, record: JobRecord, state: JobState) -> JobRecord:
        """Keep the pages the worker reported, read before _finish removes the progress file that holds them."""
        record.pages_done = read_progress(record.job_id)

        return self._finish(record, state)

    def _finish(self, record: JobRecord, state: JobState) -> JobRecord:
        record.state = state
        record.finished_at = time.time()
        self.delete_input(record.job_id)
        _remove(job_path(record.job_id, PROGRESS_SUFFIX))
        self.write(record)

        JOBS_TOTAL.labels(outcome=state).inc()
        if record.started_at is not None:
            JOB_DURATION_SECONDS.observe(max(record.finished_at - record.started_at, 0.0))

        log_transition(record)

        return record

    async def sweep(self) -> None:
        """Run both sweeps, so expiry and wedged work are noticed without a caller asking."""
        self.sweep_lifetime()
        await self.sweep_retention()

    def sweep_lifetime(self) -> list[JobRecord]:
        """Fail anything still waiting or running past the longest legitimate wait plus read."""
        cutoff = time.time() - settings.OCR_JOB_MAX_LIFETIME_SECONDS
        expired: list[JobRecord] = []

        for record in self.records():
            if record.is_terminal or record.submitted_at > cutoff:
                continue

            expired.append(self.fail(record, FAILURE_LIFETIME_EXCEEDED, "Work exceeded the maximum lifetime for a job"))
            logger.warning("Job %s failed: it outlived the maximum lifetime for a job", record.job_id)

        return expired

    async def sweep_retention(self) -> list[JobRecord]:
        """Remove finished records past their window, then the oldest beyond the count bound."""
        finished = [record for record in self.records() if record.is_terminal]
        cutoff = time.time() - settings.OCR_JOB_RETENTION_SECONDS
        removed: set[str] = set()

        for record in finished:
            if _finished_at(record) > cutoff:
                continue

            await self._delete_swept(record, removed)

        retained = sorted((record for record in finished if record.job_id not in removed), key=_finished_at)
        overflow = len(retained) - settings.OCR_JOB_MAX_RETAINED
        for record in retained[: max(overflow, 0)]:
            await self._delete_swept(record, removed)

        return [record for record in finished if record.job_id in removed]

    async def _delete_swept(self, record: JobRecord, removed: set[str]) -> None:
        """Remove one swept record, leaving it in place when its result object will not go.

        A record that still names an object nobody can reach is recoverable, because the
        next sweep tries again. An object nobody names is not, because nothing knows it
        is there.
        """
        try:
            await self.delete(record)
        except Exception:
            logger.exception("Leaving job %s in place: its result object could not be deleted", record.job_id)

            return

        removed.add(record.job_id)

    def retained_count(self) -> int:
        return sum(1 for record in self.records() if record.is_terminal)

    async def _delete_result_object(self, record: JobRecord) -> None:
        if record.result is None:
            return

        await asyncio.to_thread(self._result_deleter.delete_result, record.result.key)


def _finished_at(record: JobRecord) -> float:
    return record.finished_at or record.submitted_at


def _remove(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        logger.warning("Failed to remove job file: %s", path.name)

import asyncio
import math
from typing import TYPE_CHECKING, Final

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from src.config.config import settings
from src.config.logging_config import get_logger
from src.model.ocr_models import JobResultLocation, OcrJsonResponse
from src.observability.metrics import RESULT_UPLOAD_ATTEMPTS_TOTAL, RESULT_UPLOAD_FAILURES_TOTAL

if TYPE_CHECKING:
    from typing import Protocol

    from mypy_boto3_s3.client import S3Client

    class ResultDeleter(Protocol):
        """The one thing the job store needs from the result store, so it can order the deletes."""

        def delete_result(self, key: str) -> None: ...

    class ResultWriter(ResultDeleter, Protocol):
        """What the job runner needs: write a finished document, and remove it when its job is gone."""

        async def upload(self, job_id: str, markdown: str) -> JobResultLocation: ...

    class ResultLinkSigner(Protocol):
        """What the job service needs to hand a caller the address of a finished document."""

        def presigned_url(self, key: str, expires_in_seconds: float) -> str: ...


logger = get_logger(__name__)

RESULT_KEY_SUFFIX: Final[str] = ".md"
MARKDOWN_CONTENT_TYPE: Final[str] = "text/markdown; charset=utf-8"

# The local emulator reports this region and the agent's own S3 client names it, so the
# two address the same store the same way.
_REGION: Final[str] = "us-east-1"
_CONNECT_TIMEOUT_SECONDS: Final[int] = 5
_READ_TIMEOUT_SECONDS: Final[int] = 30
# Bounded here rather than inside botocore, so the number of attempts a job pays for is
# the one this module states and retries and their metric cannot disagree.
UPLOAD_MAX_ATTEMPTS: Final[int] = 3
UPLOAD_RETRY_BASE_SECONDS: Final[float] = 0.5
_MIN_PRESIGN_SECONDS: Final[int] = 1
_MISSING_BUCKET_CODES: Final[frozenset[str]] = frozenset({"404", "NoSuchBucket", "NotFound"})


class ResultStoreUnavailableError(Exception):
    """The finished Markdown could not be written, after every attempt this module allows."""


def render_markdown(result: OcrJsonResponse) -> str:
    """Render a finished document as the text the agent indexes, and nothing else.

    No front matter and no per-line metadata: whatever this returns is indexed verbatim
    by the ingestion pipeline downstream, so anything that is not the document's own
    text would be indexed as if it were.
    """
    pages = ["\n".join([f"## Page {page.page_number}", *(line.text for line in page.lines)]) for page in result.pages]

    return "\n\n".join(pages) + "\n"


class ResultStore:
    """The S3-compatible bucket a finished document's Markdown is written to.

    Two clients, because the address this service reaches the store on is not always the
    address a presigned URL has to carry.
    """

    def __init__(self) -> None:
        self._client: S3Client | None = None
        self._public_client: S3Client | None = None
        self.bucket_reachable: bool | None = None

    @property
    def bucket(self) -> str:
        return settings.OCR_RESULT_S3_BUCKET

    def client(self) -> "S3Client":
        if self._client is None:
            self._client = self._build_client(settings.OCR_RESULT_S3_ENDPOINT)

        return self._client

    def public_client(self) -> "S3Client":
        if self._public_client is None:
            self._public_client = self._build_client(settings.OCR_RESULT_S3_PUBLIC_ENDPOINT)

        return self._public_client

    def ensure_bucket(self) -> bool:
        """Head the result bucket and create it when missing, warning rather than refusing.

        A bucket that does not answer at boot stops delivery, not the reading: the job
        record is local, so the service can still accept work, read it and record that
        storing the result failed.
        """
        try:
            client = self.client()
            try:
                client.head_bucket(Bucket=self.bucket)
            except ClientError as exc:
                if _error_code(exc) not in _MISSING_BUCKET_CODES:
                    raise

                logger.info("Result bucket '%s' not found, creating it", self.bucket)
                client.create_bucket(Bucket=self.bucket)
        except Exception as exc:
            logger.warning("Result store at %s did not answer: %s", settings.OCR_RESULT_S3_ENDPOINT, exc)
            self.bucket_reachable = False

            return False

        self.bucket_reachable = True

        return True

    async def upload(self, job_id: str, markdown: str) -> JobResultLocation:
        """Write one job's Markdown, retrying a bounded number of times.

        Raises:
            ResultStoreUnavailableError: when every attempt failed, so the job finishes
                unsuccessfully with a reason that names the store rather than the document.
        """
        key = f"{job_id}{RESULT_KEY_SUFFIX}"
        body = markdown.encode("utf-8")
        last_error: Exception | None = None

        for attempt in range(1, UPLOAD_MAX_ATTEMPTS + 1):
            RESULT_UPLOAD_ATTEMPTS_TOTAL.inc()
            try:
                await asyncio.to_thread(self._put_object, key, body)
            except Exception as exc:
                last_error = exc
                RESULT_UPLOAD_FAILURES_TOTAL.inc()
                logger.warning("Result upload attempt %d of %d failed: %s", attempt, UPLOAD_MAX_ATTEMPTS, exc)
                if attempt < UPLOAD_MAX_ATTEMPTS:
                    await asyncio.sleep(UPLOAD_RETRY_BASE_SECONDS * attempt)

                continue

            return JobResultLocation(bucket=self.bucket, key=key)

        raise ResultStoreUnavailableError(
            f"Could not write the result for job {job_id} after {UPLOAD_MAX_ATTEMPTS} attempts"
        ) from last_error

    def presigned_url(self, key: str, expires_in_seconds: float) -> str:
        """Sign a GET URL against the public endpoint, never outliving the object it points at."""
        expires_in = max(_MIN_PRESIGN_SECONDS, math.floor(expires_in_seconds))

        return self.public_client().generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": key},
            ExpiresIn=expires_in,
        )

    def delete_result(self, key: str) -> None:
        """Remove one result object. Deleting a key that is already gone is not an error."""
        self.client().delete_object(Bucket=self.bucket, Key=key)

    def _put_object(self, key: str, body: bytes) -> None:
        self.client().put_object(Bucket=self.bucket, Key=key, Body=body, ContentType=MARKDOWN_CONTENT_TYPE)

    def _build_client(self, endpoint: str) -> "S3Client":
        # Built from this service's own settings rather than from the environment's
        # ambient AWS configuration, so a host that happens to hold credentials for a
        # real AWS account cannot become the store this service writes documents to.
        return boto3.client(
            "s3",
            endpoint_url=endpoint,
            region_name=_REGION,
            aws_access_key_id=settings.OCR_RESULT_S3_ACCESS_KEY,
            aws_secret_access_key=settings.OCR_RESULT_S3_SECRET_KEY,
            config=Config(
                s3={"addressing_style": "path"},
                signature_version="s3v4",
                connect_timeout=_CONNECT_TIMEOUT_SECONDS,
                read_timeout=_READ_TIMEOUT_SECONDS,
                retries={"max_attempts": 1, "mode": "standard"},
            ),
        )


def _error_code(exc: ClientError) -> str:
    return str(exc.response.get("Error", {}).get("Code", ""))


result_store = ResultStore()

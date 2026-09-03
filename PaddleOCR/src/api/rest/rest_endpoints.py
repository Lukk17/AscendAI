import asyncio
import time

from fastapi import APIRouter, Request, UploadFile

from src.api.exception_handlers import (
    FileSizeExceededError,
    OcrProcessingError,
    UnsupportedFileTypeError,
)
from src.api.middleware.rate_limit import limiter
from src.api.mime_sniffer import sniff_mime
from src.config.config import settings
from src.config.logging_config import get_logger
from src.model.ocr_models import OcrJsonResponse
from src.observability.metrics import (
    OCR_DURATION_SECONDS,
    OCR_REQUESTS_TOTAL,
)
from src.observability.tracing import inject_trace_context
from src.service.ocr_service import get_process_pool, ocr_service

logger = get_logger(__name__)

rest_router = APIRouter(prefix="/v1")

BYTES_PER_MB: int = 1024 * 1024


@rest_router.post("/ocr", response_model=None, summary="Run OCR on an uploaded file")
@limiter.limit(settings.RATE_LIMIT_OCR)
async def process_ocr(
    request: Request,
    file: UploadFile,
    lang: str | None = None,
) -> OcrJsonResponse:
    _ = request
    language: str = lang or settings.DEFAULT_LANGUAGE
    OCR_REQUESTS_TOTAL.labels(surface="rest", language=language).inc()

    file_bytes: bytes = await file.read()
    _validate_file_size(len(file_bytes))
    sniff_mime(file_bytes)

    filename: str = file.filename or "upload"

    start = time.monotonic()
    # Captured from the auto-instrumented request span so the worker process, which
    # executes _execute_ocr on a separate interpreter, can reattach its inference span
    # as this request's child instead of starting an orphaned one.
    trace_carrier = inject_trace_context()

    try:
        loop = asyncio.get_running_loop()
        return await asyncio.wait_for(
            loop.run_in_executor(get_process_pool(), _execute_ocr, file_bytes, filename, language, trace_carrier),
            timeout=settings.OCR_REQUEST_TIMEOUT,
        )
    finally:
        OCR_DURATION_SECONDS.labels(surface="rest", language=language).observe(time.monotonic() - start)


def _validate_file_size(size_bytes: int) -> None:
    max_size_bytes: int = settings.MAX_FILE_SIZE_MB * BYTES_PER_MB
    if size_bytes > max_size_bytes:
        raise FileSizeExceededError(f"File size {size_bytes} bytes exceeds maximum {settings.MAX_FILE_SIZE_MB} MB")


def _execute_ocr(
    file_bytes: bytes,
    filename: str,
    language: str,
    trace_carrier: dict[str, str] | None = None,
) -> OcrJsonResponse:
    try:
        return ocr_service.process_file(file_bytes, filename, language, trace_carrier)
    except (FileSizeExceededError, UnsupportedFileTypeError):
        raise
    except Exception as exc:
        raise OcrProcessingError(str(exc)) from exc

import time
from typing import Annotated

from fastapi import APIRouter, Form, Request, UploadFile

from src.api.exception_handlers import FileSizeExceededError
from src.api.limits import enforce_page_limit, enforce_pixel_ceiling, inspect_input
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
from src.service.ocr_service import dispatch_ocr_request

logger = get_logger(__name__)

rest_router = APIRouter(prefix="/v1")

BYTES_PER_MB: int = 1024 * 1024
_SURFACE: str = "rest"


@rest_router.post("/ocr", response_model=None, summary="Run OCR on an uploaded file")
@limiter.limit(settings.RATE_LIMIT_OCR)
async def process_ocr(
    request: Request,
    file: UploadFile,
    lang: Annotated[str | None, Form()] = None,
) -> OcrJsonResponse:
    _ = request
    language: str = lang or settings.DEFAULT_LANGUAGE
    OCR_REQUESTS_TOTAL.labels(surface=_SURFACE, language=language).inc()

    file_bytes: bytes = await file.read()
    _validate_file_size(len(file_bytes))
    mime = sniff_mime(file_bytes)
    shape = inspect_input(file_bytes, mime)
    enforce_pixel_ceiling(shape)
    enforce_page_limit(shape)

    filename: str = file.filename or "upload"
    effective_budget = min(shape.page_count * settings.OCR_PAGE_TIMEOUT_SECONDS, settings.OCR_REQUEST_TIMEOUT)

    start = time.monotonic()
    # Captured from the auto-instrumented request span so the worker process, which
    # executes the OCR call on a separate interpreter, can reattach its inference span
    # as this request's child instead of starting an orphaned one.
    trace_carrier = inject_trace_context()

    try:
        return await dispatch_ocr_request(file_bytes, filename, language, effective_budget, _SURFACE, trace_carrier)
    finally:
        OCR_DURATION_SECONDS.labels(surface=_SURFACE, language=language).observe(time.monotonic() - start)


def _validate_file_size(size_bytes: int) -> None:
    max_size_bytes: int = settings.MAX_FILE_SIZE_MB * BYTES_PER_MB
    if size_bytes > max_size_bytes:
        raise FileSizeExceededError(f"File size {size_bytes} bytes exceeds maximum {settings.MAX_FILE_SIZE_MB} MB")

import logging
import math
from typing import Final, cast

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from src.config.config import MCP_ENDPOINT_PATH
from src.observability.metrics import OCR_ERRORS_TOTAL

logger = logging.getLogger(__name__)


class OcrProcessingError(Exception):
    pass


class FileSizeExceededError(Exception):
    pass


class UnsupportedFileTypeError(Exception):
    pass


class UnsafeUriError(Exception):
    pass


class DownloadFailedError(Exception):
    pass


class JobNotFoundError(Exception):
    """No record is held for this identifier: it never existed, expired, or is malformed."""


class QueueFullError(Exception):
    """A submission would exceed one of the queue's two bounds, so it is refused for now."""

    def __init__(self, message: str, retry_after_seconds: float) -> None:
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


class UnsupportedLanguageError(Exception):
    """A submission asked for a language this service does not read. The message is the caller-facing detail."""


ERROR_CODE_OCR_FAILED: Final[str] = "OCR_FAILED"
ERROR_CODE_FILE_TOO_LARGE: Final[str] = "FILE_TOO_LARGE"
ERROR_CODE_UNSUPPORTED_FILE_TYPE: Final[str] = "UNSUPPORTED_FILE_TYPE"
ERROR_CODE_UNSAFE_URI: Final[str] = "UNSAFE_URI"
ERROR_CODE_DOWNLOAD_FAILED: Final[str] = "DOWNLOAD_FAILED"
ERROR_CODE_INTERNAL: Final[str] = "INTERNAL_ERROR"
ERROR_CODE_QUEUE_FULL: Final[str] = "QUEUE_FULL"
ERROR_CODE_JOB_NOT_FOUND: Final[str] = "JOB_NOT_FOUND"
ERROR_CODE_UNSUPPORTED_LANGUAGE: Final[str] = "UNSUPPORTED_LANGUAGE"


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(OcrProcessingError, _ocr_processing_handler)
    app.add_exception_handler(FileSizeExceededError, _file_size_exceeded_handler)
    app.add_exception_handler(UnsupportedFileTypeError, _unsupported_file_type_handler)
    app.add_exception_handler(UnsafeUriError, _unsafe_uri_handler)
    app.add_exception_handler(DownloadFailedError, _download_failed_handler)
    app.add_exception_handler(QueueFullError, _queue_full_handler)
    app.add_exception_handler(JobNotFoundError, _job_not_found_handler)
    app.add_exception_handler(UnsupportedLanguageError, _unsupported_language_handler)
    app.add_exception_handler(Exception, _global_exception_handler)


def _ocr_processing_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.error("OCR processing failed: %s", exc)
    _increment(ERROR_CODE_OCR_FAILED, request)

    return JSONResponse(
        status_code=422,
        content={"code": ERROR_CODE_OCR_FAILED, "detail": "OCR processing failed"},
    )


def log_refusal(code: str, exc: Exception) -> None:
    """Record a refusal that worked as designed: one warning naming its code, and no traceback."""
    logger.warning("Refused with %s: %s", code, exc)


def _file_size_exceeded_handler(request: Request, exc: Exception) -> JSONResponse:
    log_refusal(ERROR_CODE_FILE_TOO_LARGE, exc)
    _increment(ERROR_CODE_FILE_TOO_LARGE, request)

    return JSONResponse(
        status_code=400,
        content={"code": ERROR_CODE_FILE_TOO_LARGE, "detail": "File too large"},
    )


def _unsupported_file_type_handler(request: Request, exc: Exception) -> JSONResponse:
    log_refusal(ERROR_CODE_UNSUPPORTED_FILE_TYPE, exc)
    _increment(ERROR_CODE_UNSUPPORTED_FILE_TYPE, request)

    return JSONResponse(
        status_code=400,
        content={"code": ERROR_CODE_UNSUPPORTED_FILE_TYPE, "detail": "Unsupported file type"},
    )


def _unsafe_uri_handler(request: Request, exc: Exception) -> JSONResponse:
    log_refusal(ERROR_CODE_UNSAFE_URI, exc)
    _increment(ERROR_CODE_UNSAFE_URI, request)

    return JSONResponse(
        status_code=400,
        content={"code": ERROR_CODE_UNSAFE_URI, "detail": "URI is not permitted"},
    )


def _download_failed_handler(request: Request, exc: Exception) -> JSONResponse:
    log_refusal(ERROR_CODE_DOWNLOAD_FAILED, exc)
    _increment(ERROR_CODE_DOWNLOAD_FAILED, request)

    return JSONResponse(
        status_code=502,
        content={"code": ERROR_CODE_DOWNLOAD_FAILED, "detail": "Failed to fetch source"},
    )


def _queue_full_handler(request: Request, exc: Exception) -> JSONResponse:
    log_refusal(ERROR_CODE_QUEUE_FULL, exc)
    _increment(ERROR_CODE_QUEUE_FULL, request)
    retry_after = max(1, math.ceil(cast(QueueFullError, exc).retry_after_seconds))

    return JSONResponse(
        status_code=503,
        content={"code": ERROR_CODE_QUEUE_FULL, "detail": "Queue is full, retry later"},
        headers={"Retry-After": str(retry_after)},
    )


def _job_not_found_handler(request: Request, exc: Exception) -> JSONResponse:
    log_refusal(ERROR_CODE_JOB_NOT_FOUND, exc)
    _increment(ERROR_CODE_JOB_NOT_FOUND, request)

    return JSONResponse(
        status_code=404,
        content={"code": ERROR_CODE_JOB_NOT_FOUND, "detail": "Job identifier is unknown or expired"},
    )


def _unsupported_language_handler(request: Request, exc: Exception) -> JSONResponse:
    log_refusal(ERROR_CODE_UNSUPPORTED_LANGUAGE, exc)
    _increment(ERROR_CODE_UNSUPPORTED_LANGUAGE, request)

    return JSONResponse(
        status_code=400,
        content={"code": ERROR_CODE_UNSUPPORTED_LANGUAGE, "detail": str(exc)},
    )


def _global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled exception: %s", exc)
    _increment(ERROR_CODE_INTERNAL, request)

    return JSONResponse(
        status_code=500,
        content={"code": ERROR_CODE_INTERNAL, "detail": "Internal server error"},
    )


def _increment(code: str, request: Request) -> None:
    surface = "mcp" if request.url.path == MCP_ENDPOINT_PATH else "rest"
    OCR_ERRORS_TOTAL.labels(error_code=code, surface=surface).inc()

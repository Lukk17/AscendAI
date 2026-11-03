import math
from typing import Final

from ascend_python_common.errors import ErrorRegistry, ProblemCode, install_error_handlers
from fastapi import FastAPI


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
    """A submission asked for a language this service does not read.

    The message is the caller-facing detail.
    """


ERROR_CODE_OCR_FAILED: Final[str] = "OCR_FAILED"
ERROR_CODE_FILE_TOO_LARGE: Final[str] = "FILE_TOO_LARGE"
ERROR_CODE_UNSUPPORTED_FILE_TYPE: Final[str] = "UNSUPPORTED_FILE_TYPE"
ERROR_CODE_UNSAFE_URI: Final[str] = "UNSAFE_URI"
ERROR_CODE_DOWNLOAD_FAILED: Final[str] = "DOWNLOAD_FAILED"
ERROR_CODE_INTERNAL: Final[str] = "INTERNAL_ERROR"
ERROR_CODE_QUEUE_FULL: Final[str] = "QUEUE_FULL"
ERROR_CODE_JOB_NOT_FOUND: Final[str] = "JOB_NOT_FOUND"
ERROR_CODE_UNSUPPORTED_LANGUAGE: Final[str] = "UNSUPPORTED_LANGUAGE"

OCR_FAILED: Final[ProblemCode] = ProblemCode(ERROR_CODE_OCR_FAILED, 422)
FILE_TOO_LARGE: Final[ProblemCode] = ProblemCode(ERROR_CODE_FILE_TOO_LARGE, 400)
UNSUPPORTED_FILE_TYPE: Final[ProblemCode] = ProblemCode(ERROR_CODE_UNSUPPORTED_FILE_TYPE, 400)
UNSAFE_URI: Final[ProblemCode] = ProblemCode(ERROR_CODE_UNSAFE_URI, 400)
DOWNLOAD_FAILED: Final[ProblemCode] = ProblemCode(ERROR_CODE_DOWNLOAD_FAILED, 502)
INTERNAL_ERROR: Final[ProblemCode] = ProblemCode(ERROR_CODE_INTERNAL, 500)
QUEUE_FULL: Final[ProblemCode] = ProblemCode(ERROR_CODE_QUEUE_FULL, 503)
JOB_NOT_FOUND: Final[ProblemCode] = ProblemCode(ERROR_CODE_JOB_NOT_FOUND, 404)
UNSUPPORTED_LANGUAGE: Final[ProblemCode] = ProblemCode(ERROR_CODE_UNSUPPORTED_LANGUAGE, 400)


def _queue_full_headers(exc: BaseException) -> dict[str, str] | None:
    if not isinstance(exc, QueueFullError):
        return None
    return {"Retry-After": str(max(1, math.ceil(exc.retry_after_seconds)))}


def build_error_registry() -> ErrorRegistry:
    registry = ErrorRegistry(internal_code=INTERNAL_ERROR)
    registry.register(OcrProcessingError, OCR_FAILED, "OCR processing failed")
    registry.register(FileSizeExceededError, FILE_TOO_LARGE, "File too large")
    registry.register(UnsupportedFileTypeError, UNSUPPORTED_FILE_TYPE, "Unsupported file type")
    registry.register(UnsafeUriError, UNSAFE_URI, "URI is not permitted")
    registry.register(DownloadFailedError, DOWNLOAD_FAILED, "Failed to fetch source", expected=True)
    registry.register(QueueFullError, QUEUE_FULL, "Queue is full, retry later", headers=_queue_full_headers)
    registry.register(JobNotFoundError, JOB_NOT_FOUND, "Job identifier is unknown or expired")
    registry.register(UnsupportedLanguageError, UNSUPPORTED_LANGUAGE, str)
    return registry


error_registry = build_error_registry()


def register_exception_handlers(app: FastAPI) -> None:
    install_error_handlers(app, error_registry)


__all__ = [
    "DOWNLOAD_FAILED",
    "ERROR_CODE_DOWNLOAD_FAILED",
    "ERROR_CODE_FILE_TOO_LARGE",
    "ERROR_CODE_INTERNAL",
    "ERROR_CODE_JOB_NOT_FOUND",
    "ERROR_CODE_OCR_FAILED",
    "ERROR_CODE_QUEUE_FULL",
    "ERROR_CODE_UNSAFE_URI",
    "ERROR_CODE_UNSUPPORTED_FILE_TYPE",
    "ERROR_CODE_UNSUPPORTED_LANGUAGE",
    "FILE_TOO_LARGE",
    "INTERNAL_ERROR",
    "JOB_NOT_FOUND",
    "OCR_FAILED",
    "QUEUE_FULL",
    "UNSAFE_URI",
    "UNSUPPORTED_FILE_TYPE",
    "UNSUPPORTED_LANGUAGE",
    "DownloadFailedError",
    "FileSizeExceededError",
    "JobNotFoundError",
    "OcrProcessingError",
    "QueueFullError",
    "UnsafeUriError",
    "UnsupportedFileTypeError",
    "UnsupportedLanguageError",
    "build_error_registry",
    "error_registry",
    "register_exception_handlers",
]

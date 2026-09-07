import logging

from fastapi import Request, status
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

PROBLEM_JSON = "application/problem+json"
_PROBLEM_TYPE_BASE = "https://ascend.ai/errors"


class FileSizeExceededError(Exception):
    """Raised when upload, download, or zip extraction exceeds the configured
    cap. Distinct from ValueError so it can map to 413 (Content Too Large)
    rather than 400 (Validation Failed)."""


def value_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Map ValueError (e.g. unsafe URI, missing field, empty input) to 400 with
    an RFC 7807 problem document. The exception detail is safe to surface here
    because for ValueError the message IS the actionable failure reason and is
    authored by the service, not by an upstream library.

    Signature is `Exception` (rather than `ValueError`) to satisfy
    Starlette's typeshed for `add_exception_handler`; the registration key
    restricts dispatch at runtime."""

    logger.warning(f"ValueError on {request.method} {request.url}: {exc}")

    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        media_type=PROBLEM_JSON,
        content={
            "type": f"{_PROBLEM_TYPE_BASE}/validation",
            "title": "Validation Failed",
            "status": status.HTTP_400_BAD_REQUEST,
            "detail": str(exc),
            "instance": str(request.url.path),
        },
    )


def file_size_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """413 for upload / download / zip-extract size cap breaches. Distinct
    from value_error_handler because FileSizeExceededError is not a
    ValueError subclass — clients need the 413 status to know the failure
    is request-size, not request-shape.

    Signature accepts `Exception` to satisfy Starlette's typing for
    `add_exception_handler`; runtime registration restricts dispatch to
    `FileSizeExceededError` via the handler-registration key."""

    logger.warning(f"FileSizeExceeded on {request.method} {request.url}: {exc}")

    return JSONResponse(
        status_code=status.HTTP_413_CONTENT_TOO_LARGE,
        media_type=PROBLEM_JSON,
        content={
            "type": f"{_PROBLEM_TYPE_BASE}/file-too-large",
            "title": "File Too Large",
            "status": status.HTTP_413_CONTENT_TOO_LARGE,
            "detail": str(exc),
            "instance": str(request.url.path),
        },
    )


def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Catch-all for unhandled exceptions. The exception is logged with full
    traceback server-side; the response body never carries internal detail
    (upstream URLs, DSNs, mem0 / faster-whisper internal state)."""

    logger.exception(f"Unhandled Exception during {request.method} {request.url}: {exc}")

    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        media_type=PROBLEM_JSON,
        content={
            "type": f"{_PROBLEM_TYPE_BASE}/internal",
            "title": "Internal Server Error",
            "status": status.HTTP_500_INTERNAL_SERVER_ERROR,
            "instance": str(request.url.path),
        },
    )

import logging

from fastapi import Request, status
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

PROBLEM_JSON = "application/problem+json"
_PROBLEM_TYPE_BASE = "https://ascend.ai/errors"


def value_error_handler(request: Request, exc: ValueError) -> JSONResponse:
    """Map ValueError (e.g. unknown provider, missing API key, empty text)
    to 400 with an RFC 7807 problem document. The exception detail goes
    into `detail` because for ValueError the message IS the actionable
    failure reason and was authored by us, not by an upstream library."""

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


def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Catch-all handler for unhandled exceptions. The exception is logged
    with full traceback server-side; the response body never carries
    internal detail (upstream URLs, DSNs, mem0 internal state)."""

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

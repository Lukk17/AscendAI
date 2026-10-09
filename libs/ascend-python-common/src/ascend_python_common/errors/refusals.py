import logging
from typing import Final

from fastapi import Request
from prometheus_client import Counter

logger = logging.getLogger(__name__)

ERRORS_TOTAL: Final[Counter] = Counter(
    "ascend_service_errors_total",
    "Count of refused and unexpected error responses.",
    ["code", "surface", "operation"],
)


def operation_of(request: Request) -> str:
    route = request.scope.get("route")
    path = getattr(route, "path", None)
    if isinstance(path, str) and path:
        return path
    return "unmatched"


def report(
    code: str,
    detail: str,
    status: int,
    surface: str,
    operation: str,
    exc: BaseException,
    expected: bool = False,
) -> None:
    ERRORS_TOTAL.labels(code=code, surface=surface, operation=operation).inc()
    if status < 500 or expected:
        logger.warning("Refused with %s: %s", code, detail)
    else:
        logger.error(
            "Unhandled %s: %s",
            code,
            detail,
            exc_info=(type(exc), exc, exc.__traceback__),
        )


__all__ = ["ERRORS_TOTAL", "operation_of", "report"]

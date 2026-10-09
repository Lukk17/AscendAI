from collections.abc import Callable
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from slowapi.errors import RateLimitExceeded
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import JSONResponse

from ascend_python_common.errors.codes import (
    INTERNAL_FIXED_DETAIL,
    RATE_LIMITED,
    UNAUTHORIZED_FIXED_DETAIL,
    VALIDATION,
    ProblemCode,
    platform_code_for_status,
)
from ascend_python_common.errors.problem import problem_response
from ascend_python_common.errors.refusals import operation_of, report
from ascend_python_common.errors.registry import (
    ErrorEntry,
    ErrorRegistry,
    resolve_detail,
    resolve_extensions,
    resolve_headers,
)

Handler = Callable[[Request, Any], JSONResponse]


def _registry_handler(entry: ErrorEntry) -> Handler:
    def handle(request: Request, exc: BaseException) -> JSONResponse:
        detail = resolve_detail(entry, exc)
        headers = resolve_headers(entry, exc)
        extensions = resolve_extensions(entry, exc)
        report(
            entry.code.code,
            detail,
            entry.code.status,
            "rest",
            operation_of(request),
            exc,
            entry.expected,
        )
        return problem_response(request, entry.code, detail, headers=headers, extensions=extensions)

    return handle


def _http_detail(exc: HTTPException) -> str:
    if exc.status_code == 401:
        return UNAUTHORIZED_FIXED_DETAIL
    if exc.status_code == 500:
        return INTERNAL_FIXED_DETAIL
    return str(exc.detail)


def _http_headers(exc: HTTPException) -> dict[str, str] | None:
    merged: dict[str, str] = dict(exc.headers) if exc.headers else {}
    if exc.status_code == 401:
        merged.setdefault("WWW-Authenticate", "Bearer")
    return merged or None


def _http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    code = platform_code_for_status(exc.status_code)
    detail = _http_detail(exc)
    headers = _http_headers(exc)
    report(code.code, detail, code.status, "rest", operation_of(request), exc, False)
    return problem_response(request, code, detail, headers=headers)


def _validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    errors = sorted(
        (
            {
                "field": ".".join(str(part) for part in err.get("loc", ())[1:]),
                "message": str(err.get("msg", "")),
            }
            for err in exc.errors()
        ),
        key=lambda item: item["field"],
    )
    detail = "Request validation failed"
    report(VALIDATION.code, detail, VALIDATION.status, "rest", operation_of(request), exc, False)
    return problem_response(request, VALIDATION, detail, extensions={"errors": errors})


def _rate_limit_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    detail = f"Rate limit exceeded: {exc.detail}"
    report(RATE_LIMITED.code, detail, RATE_LIMITED.status, "rest", operation_of(request), exc, False)
    return problem_response(request, RATE_LIMITED, detail, headers={"Retry-After": "60"})


def _unhandled_handler(internal_code: ProblemCode) -> Handler:
    def handle(request: Request, exc: Exception) -> JSONResponse:
        report(
            internal_code.code,
            INTERNAL_FIXED_DETAIL,
            internal_code.status,
            "rest",
            operation_of(request),
            exc,
            False,
        )
        return problem_response(request, internal_code, INTERNAL_FIXED_DETAIL)

    return handle


def install_error_handlers(app: FastAPI, registry: ErrorRegistry) -> None:
    for exc_type, entry in registry.entries.items():
        app.add_exception_handler(exc_type, _registry_handler(entry))
    app.add_exception_handler(HTTPException, _http_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(StarletteHTTPException, _http_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, _validation_handler)  # type: ignore[arg-type]
    app.add_exception_handler(RateLimitExceeded, _rate_limit_handler)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, _unhandled_handler(registry.internal_code))


__all__ = ["install_error_handlers"]

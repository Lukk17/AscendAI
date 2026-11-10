from http import HTTPStatus
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse

from ascend_python_common.errors.codes import ERROR_TYPE_BASE, ProblemCode
from ascend_python_common.tracing import current_trace_id

PROBLEM_MEDIA_TYPE = "application/problem+json"
STANDARD_MEMBERS = frozenset({"type", "title", "status", "detail", "instance", "code", "traceId"})


def problem_type_slug(code: str) -> str:
    return code.lower().replace("_", "-")


def problem_response(
    request: Request,
    code: ProblemCode,
    detail: str,
    headers: dict[str, str] | None = None,
    extensions: dict[str, Any] | None = None,
) -> JSONResponse:
    content: dict[str, Any] = {
        "type": ERROR_TYPE_BASE + problem_type_slug(code.code),
        "title": HTTPStatus(code.status).phrase,
        "status": code.status,
        "detail": detail,
        "instance": request.url.path,
        "code": code.code,
    }
    trace_id = current_trace_id()
    if trace_id is not None:
        content["traceId"] = trace_id
    content.update({key: value for key, value in (extensions or {}).items() if key not in STANDARD_MEMBERS})
    return JSONResponse(
        status_code=code.status,
        content=content,
        media_type=PROBLEM_MEDIA_TYPE,
        headers=headers,
    )


__all__ = ["PROBLEM_MEDIA_TYPE", "STANDARD_MEMBERS", "problem_response", "problem_type_slug"]

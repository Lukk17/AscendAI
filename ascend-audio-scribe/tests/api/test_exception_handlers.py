from typing import cast

from starlette.requests import Request
from starlette.types import Scope

from src.api.exception_handlers import (
    PROBLEM_JSON,
    FileSizeExceededError,
    file_size_error_handler,
    global_exception_handler,
    value_error_handler,
)


def _make_request(path: str = "/") -> Request:
    scope = cast(
        "Scope",
        {"type": "http", "method": "POST", "path": path, "headers": [], "query_string": b""},
    )
    return Request(scope)


def test_value_error_handler_returns_400_problem_json() -> None:
    response = value_error_handler(_make_request(), ValueError("oops"))
    assert response.status_code == 400
    assert response.media_type == PROBLEM_JSON
    body = response.body.decode()
    assert "oops" in body
    assert "/validation" in body


def test_file_size_error_handler_returns_413_problem_json() -> None:
    response = file_size_error_handler(_make_request(), FileSizeExceededError("too big"))
    assert response.status_code == 413
    assert response.media_type == PROBLEM_JSON
    body = response.body.decode()
    assert "too big" in body
    assert "/file-too-large" in body


def test_global_exception_handler_redacts_detail() -> None:
    sentinel = "UPSTREAM_LEAK_MARKER"
    response = global_exception_handler(_make_request("/x"), RuntimeError(sentinel))
    assert response.status_code == 500
    body = response.body.decode()
    assert sentinel not in body
    assert "/x" in body

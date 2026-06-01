from typing import cast

from starlette.requests import Request
from starlette.types import Scope

from src.api.exception_handlers import (
    PROBLEM_JSON,
    global_exception_handler,
    value_error_handler,
)


def _make_request(path: str = "/api/v1/memory") -> Request:
    scope = cast(
        "Scope",
        {
            "type": "http",
            "method": "POST",
            "path": path,
            "headers": [],
            "query_string": b"",
        },
    )
    return Request(scope)


def test_value_error_handler_returns_problem_json_400():
    response = value_error_handler(_make_request(), ValueError("oops"))
    assert response.status_code == 400
    assert response.media_type == PROBLEM_JSON


def test_value_error_handler_includes_path_and_detail():
    request = _make_request("/api/v1/memory/insert")
    response = value_error_handler(request, ValueError("missing field"))
    assert response.status_code == 400
    body = response.body.decode()
    assert "missing field" in body
    assert "/api/v1/memory/insert" in body


def test_global_exception_handler_returns_problem_json_500():
    response = global_exception_handler(_make_request(), RuntimeError("kaboom"))
    assert response.status_code == 500
    assert response.media_type == PROBLEM_JSON


def test_global_exception_handler_does_not_leak_exception_detail():
    request = _make_request("/api/v1/memory/wipe")
    # Sentinel marker stands in for what a real upstream might leak (DSN,
    # token fragment, stack frame). The test only asserts the marker does not
    # surface in the response body, so any unique string works.
    sentinel_secret = "UPSTREAM_LEAK_MARKER_42"
    response = global_exception_handler(request, RuntimeError(sentinel_secret))
    assert response.status_code == 500
    assert sentinel_secret not in response.body.decode()
    assert "/api/v1/memory/wipe" in response.body.decode()

import httpx
import pytest
from fastapi import Request

from src.api.exception_handlers import (
    global_exception_handler,
    httpx_exception_handler,
    human_intervention_exception_handler,
)
from src.api.exceptions import HumanInterventionRequiredException


def _make_request() -> Request:
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/test",
        "raw_path": b"/test",
        "query_string": b"",
        "headers": [],
        "server": ("test", 80),
        "scheme": "http",
        "client": ("127.0.0.1", 0),
        "root_path": "",
    }

    return Request(scope)


@pytest.mark.asyncio
async def test_httpx_exception_handler_returns_503():
    response = await httpx_exception_handler(_make_request(), httpx.HTTPError("upstream"))
    assert response.status_code == 503


@pytest.mark.asyncio
async def test_global_exception_handler_returns_500():
    response = await global_exception_handler(_make_request(), RuntimeError("boom"))
    assert response.status_code == 500


@pytest.mark.asyncio
async def test_human_intervention_handler_returns_428_captcha():
    exc = HumanInterventionRequiredException(vnc_url="http://vnc", intervention_type="captcha")
    response = await human_intervention_exception_handler(_make_request(), exc)
    assert response.status_code == 428


@pytest.mark.asyncio
async def test_human_intervention_handler_returns_428_login():
    exc = HumanInterventionRequiredException(vnc_url="http://vnc/log", intervention_type="login")
    response = await human_intervention_exception_handler(_make_request(), exc)
    assert response.status_code == 428

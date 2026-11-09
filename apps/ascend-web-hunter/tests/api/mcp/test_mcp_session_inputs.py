"""Every MCP tool that takes a profile or a session address checks it at the boundary."""

import inspect
import logging
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any

import pytest
from ascend_python_common.errors.mcp import McpRefusalMiddleware
from fastmcp.exceptions import FastMCPError, ToolError
from pydantic import TypeAdapter, ValidationError

from src.api.exception_handlers import error_registry
from src.api.mcp.mcp_server import crawl_submit, session_clear, session_establish, session_status, web_read
from src.session.profile import MAX_URL_LENGTH, InvalidProfileError

_BAD_PROFILES = ("a\nb", "a" * 65)

_PROFILE_TOOLS: tuple[Callable[..., Any], ...] = (
    web_read,
    session_establish,
    session_status,
    session_clear,
    crawl_submit,
)

_SESSION_TOOLS: tuple[Callable[..., Any], ...] = (session_establish, session_status, session_clear)

_USER_INFO_URL = "https://x.com:443@y.com/"


def _parameter_type(tool: Callable[..., Any], name: str) -> TypeAdapter[Any]:
    return TypeAdapter(inspect.signature(tool).parameters[name].annotation)


def _refusal_code(exc: ValidationError) -> str | None:
    entry = error_registry.lookup(exc)

    return None if entry is None else entry.code.code


@pytest.mark.parametrize("tool", _PROFILE_TOOLS, ids=lambda tool: tool.__name__)
@pytest.mark.parametrize("profile", _BAD_PROFILES, ids=["newline", "too-long"])
def test_every_profile_parameter_refuses_a_bad_profile_as_invalid_profile(
    tool: Callable[..., Any], profile: str
) -> None:
    # when
    with pytest.raises(InvalidProfileError) as exc:
        _parameter_type(tool, "profile").validate_python(profile)

    # then
    entry = error_registry.lookup(exc.value)
    assert entry is not None
    assert entry.code.code == "invalid_profile"


@pytest.mark.parametrize("tool", _PROFILE_TOOLS, ids=lambda tool: tool.__name__)
def test_every_profile_parameter_reads_an_empty_profile_as_the_default_profile(
    tool: Callable[..., Any],
) -> None:
    # when
    profile = _parameter_type(tool, "profile").validate_python("")

    # then
    assert profile is None


@pytest.mark.parametrize("tool", _SESSION_TOOLS, ids=lambda tool: tool.__name__)
def test_every_session_address_parameter_refuses_user_info_as_validation(tool: Callable[..., Any]) -> None:
    # when
    with pytest.raises(ValidationError) as exc:
        _parameter_type(tool, "url").validate_python(_USER_INFO_URL)

    # then
    assert _refusal_code(exc.value) == "validation"


async def _refused_tool_text(tool: Callable[..., Any], name: str, value: str) -> str:
    async def call_next(_context: Any) -> None:
        _parameter_type(tool, name).validate_python(value)

    context = SimpleNamespace(message=SimpleNamespace(name=tool.__name__), fastmcp_context=None)
    with pytest.raises(ToolError) as exc:
        await McpRefusalMiddleware(error_registry).on_call_tool(context, call_next)  # type: ignore[arg-type]

    return str(exc.value)


@pytest.mark.parametrize("tool", _PROFILE_TOOLS, ids=lambda tool: tool.__name__)
@pytest.mark.parametrize("profile", _BAD_PROFILES, ids=["newline", "too-long"])
async def test_a_call_with_a_bad_profile_answers_an_invalid_profile_tool_error(
    tool: Callable[..., Any], profile: str
) -> None:
    # when
    text = await _refused_tool_text(tool, "profile", profile)

    # then
    assert text.startswith("invalid_profile: ")


async def test_a_call_with_a_session_address_carrying_user_info_answers_a_validation_tool_error() -> None:
    # when
    text = await _refused_tool_text(session_status, "url", _USER_INFO_URL)

    # then
    assert text.startswith("validation: ")


_ADDRESS_WITH_USER_INFO = "https://user:topsecret@example.com/"

_ADDRESS_TOOLS: tuple[Callable[..., Any], ...] = (web_read, session_establish, session_status, session_clear)


def test_the_address_limit_is_the_one_rest_reads_use() -> None:
    # then
    assert MAX_URL_LENGTH == 2083


@pytest.mark.parametrize("tool", _ADDRESS_TOOLS, ids=lambda tool: tool.__name__)
async def test_a_too_long_address_answers_a_validation_tool_error(tool: Callable[..., Any]) -> None:
    # given
    url = "https://example.com/" + "a" * MAX_URL_LENGTH

    # when
    text = await _refused_tool_text(tool, "url", url)

    # then
    assert text == "validation: String should have at most 2083 characters"


@pytest.mark.parametrize("tool", _ADDRESS_TOOLS, ids=lambda tool: tool.__name__)
def test_an_address_at_the_limit_is_accepted(tool: Callable[..., Any]) -> None:
    # given
    url = "https://example.com/" + "a" * (MAX_URL_LENGTH - len("https://example.com/"))

    # when
    accepted = _parameter_type(tool, "url").validate_python(url)

    # then
    assert accepted == url


async def test_a_too_long_crawl_seed_answers_a_validation_tool_error() -> None:
    # given
    seed = "https://example.com/" + "a" * MAX_URL_LENGTH

    # when
    with pytest.raises(ToolError) as exc:
        await crawl_submit(seeds=[seed])

    # then
    assert str(exc.value) == "validation: seeds.0: Value error, url must have at most 2083 characters"


async def test_a_refused_address_keeps_its_secret_out_of_the_tool_error_and_the_log(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # when
    with caplog.at_level(logging.DEBUG):
        text = await _refused_tool_text(session_status, "url", _ADDRESS_WITH_USER_INFO)

    # then
    assert text == "validation: Value error, url must not carry user info before the host"
    assert "topsecret" not in caplog.text
    assert "Refused with validation" in caplog.text


def test_a_bad_profile_is_logged_by_fastmcp_below_error_and_without_a_traceback() -> None:
    # when
    with pytest.raises(InvalidProfileError) as exc:
        _parameter_type(session_status, "profile").validate_python("a\nb")

    # then
    assert isinstance(exc.value, FastMCPError)
    assert exc.value.log_level < logging.ERROR
    assert str(exc.value) == "profile must match [A-Za-z0-9_-]{1,64}"

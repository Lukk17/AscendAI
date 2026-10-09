import json
import logging
import re
import sys
import uuid
from collections.abc import Iterator

import pytest
from opentelemetry.sdk.trace import TracerProvider
from pydantic import Field

from ascend_python_common.log_config import (
    COLOR_FORMAT_DEFAULTS,
    DATE_FORMAT,
    LOG_COLORS,
    LOGGERS_ROUTED_THROUGH_ROOT,
    MCP_TRANSPORT_LOGGER_NAMES,
    UVICORN_LOGGER_NAMES,
    CenteredLevelFormatter,
    configure_logging,
    get_logger,
)
from ascend_python_common.request_context import (
    LogFilterFailureWarning,
    McpSessionIdRedactionFilter,
    _NeverRaisingLogFilter,
    _RequestLogIds,
    digest_of_mcp_session_id,
    mcp_request_log_context,
)
from ascend_python_common.settings import RateLimit, ServiceSettings

ABSENT_FIELD = "-"
CORRELATION_ID = "corr-1"
SESSION_DIGEST = "0123456789abcdef"
SERVICE_NAME = "probe-service"
ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*m")


class _LogTestSettings(ServiceSettings):
    API_PORT: int = Field(default=7022, ge=1, le=65535)
    RATE_LIMIT_DEFAULT: RateLimit = Field(default="600/minute")


settings = _LogTestSettings()


@pytest.fixture(autouse=True)
def _clean_log_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("LOG_LEVEL", "LOG_FORMAT"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def restored_logging() -> Iterator[None]:
    root = logging.getLogger()
    routed = [logging.getLogger(name) for name in LOGGERS_ROUTED_THROUGH_ROOT]
    saved_root = (list(root.handlers), root.level)
    saved_routed = [(list(each.handlers), each.level, each.propagate) for each in routed]
    try:
        yield
    finally:
        root.handlers[:] = saved_root[0]
        root.setLevel(saved_root[1])
        for routed_logger, (handlers, level, propagate) in zip(routed, saved_routed, strict=True):
            routed_logger.handlers[:] = handlers
            routed_logger.setLevel(level)
            routed_logger.propagate = propagate


def _last_json_line(capsys: pytest.CaptureFixture[str]) -> dict[str, object]:
    # given
    captured = capsys.readouterr()
    # when
    parsed: dict[str, object] = json.loads((captured.err + captured.out).strip().splitlines()[-1])
    # then
    assert isinstance(parsed, dict)
    return parsed


def test_json_line_carries_every_required_field(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    restored_logging: None,
) -> None:
    # given
    monkeypatch.setattr(settings, "LOG_FORMAT", "json")
    monkeypatch.setattr(settings, "LOG_LEVEL", "INFO")
    configure_logging(SERVICE_NAME, settings)
    # when
    logging.getLogger("test.json.fields").info("hello fields")
    parsed = _last_json_line(capsys)
    # then
    assert parsed["message"] == "hello fields"
    assert parsed["service"] == SERVICE_NAME
    assert parsed["level"] == "INFO"
    assert parsed["correlation_id"] == ABSENT_FIELD
    assert parsed["mcp_session_id"] is None
    assert parsed["trace_id"] == ABSENT_FIELD
    assert parsed["span_id"] == ABSENT_FIELD
    assert {"timestamp", "name", "module"} <= set(parsed)


def test_color_line_starts_with_the_service_name_prefix(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    restored_logging: None,
) -> None:
    # given
    monkeypatch.setattr(settings, "LOG_FORMAT", "color")
    monkeypatch.setattr(settings, "LOG_LEVEL", "INFO")
    configure_logging(SERVICE_NAME, settings)
    # when
    logging.getLogger("test.color.prefix").info("hello color")
    captured = capsys.readouterr()
    # then
    [line] = [line for line in ANSI_ESCAPE.sub("", captured.err).splitlines() if "hello color" in line]
    assert line.startswith(f"[{SERVICE_NAME}]")


def test_no_info_line_and_no_access_line_at_warning(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    restored_logging: None,
) -> None:
    # given
    monkeypatch.setattr(settings, "LOG_FORMAT", "json")
    monkeypatch.setattr(settings, "LOG_LEVEL", "WARNING")
    configure_logging(SERVICE_NAME, settings)
    # when
    logging.getLogger("test.quiet").info("suppressed info line")
    logging.getLogger("uvicorn.access").info("suppressed access line")
    captured = capsys.readouterr()
    # then
    assert "suppressed info line" not in captured.err + captured.out
    assert "suppressed access line" not in captured.err + captured.out


def test_debug_line_is_written_at_debug(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    restored_logging: None,
) -> None:
    # given
    monkeypatch.setattr(settings, "LOG_FORMAT", "json")
    monkeypatch.setattr(settings, "LOG_LEVEL", "DEBUG")
    configure_logging(SERVICE_NAME, settings)
    # when
    logging.getLogger("test.debug").debug("visible debug line")
    parsed = _last_json_line(capsys)
    # then
    assert parsed["message"] == "visible debug line"
    assert parsed["level"] == "DEBUG"


def test_32_hex_token_is_masked_in_a_transport_line(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    restored_logging: None,
) -> None:
    # given
    monkeypatch.setattr(settings, "LOG_FORMAT", "json")
    monkeypatch.setattr(settings, "LOG_LEVEL", "INFO")
    configure_logging(SERVICE_NAME, settings)
    session_id = uuid.uuid4().hex
    # when
    logging.getLogger("mcp.server.streamable_http").error(
        "Created new transport with session ID: %s", session_id
    )
    captured = capsys.readouterr()
    # then
    written = captured.err + captured.out
    assert session_id not in written
    assert digest_of_mcp_session_id(session_id) in written


def test_32_hex_token_is_masked_in_the_traceback_text(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    restored_logging: None,
) -> None:
    # given
    monkeypatch.setattr(settings, "LOG_FORMAT", "color")
    monkeypatch.setattr(settings, "LOG_LEVEL", "INFO")
    configure_logging(SERVICE_NAME, settings)
    session_id = uuid.uuid4().hex
    # when
    try:
        raise RuntimeError(f"transport {session_id} crashed")
    except RuntimeError:
        logging.getLogger("mcp.server.streamable_http").exception("session worker failed")
    captured = capsys.readouterr()
    # then
    written = captured.err + captured.out
    assert session_id not in written
    assert digest_of_mcp_session_id(session_id) in written


def test_trace_ids_follow_the_current_span(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    restored_logging: None,
) -> None:
    # given
    monkeypatch.setattr(settings, "LOG_FORMAT", "json")
    monkeypatch.setattr(settings, "LOG_LEVEL", "INFO")
    configure_logging(SERVICE_NAME, settings)
    tracer = TracerProvider().get_tracer(__name__)
    # when
    with tracer.start_as_current_span("probe") as span:
        logging.getLogger("test.trace").info("inside a span")
    parsed = _last_json_line(capsys)
    # then
    span_context = span.get_span_context()
    assert parsed["trace_id"] == f"{span_context.trace_id:032x}"
    assert parsed["span_id"] == f"{span_context.span_id:016x}"


def test_bound_request_ids_reach_the_json_line(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    restored_logging: None,
) -> None:
    # given
    monkeypatch.setattr(settings, "LOG_FORMAT", "json")
    monkeypatch.setattr(settings, "LOG_LEVEL", "INFO")
    configure_logging(SERVICE_NAME, settings)
    # when
    with mcp_request_log_context(CORRELATION_ID, SESSION_DIGEST):
        logging.getLogger("test.json.bound").info("inside a request")
    parsed = _last_json_line(capsys)
    # then
    assert parsed["correlation_id"] == CORRELATION_ID
    assert parsed["mcp_session_id"] == SESSION_DIGEST


def test_ids_carried_by_an_escaping_exception_reach_the_line() -> None:
    # given
    carried = _RequestLogIds(CORRELATION_ID, SESSION_DIGEST)
    record = logging.LogRecord(
        name="test",
        level=logging.ERROR,
        pathname="",
        lineno=0,
        msg="boom",
        args=(),
        exc_info=None,
    )
    try:
        raise RuntimeError("boom")
    except RuntimeError as exc:
        setattr(exc, "_ascend_request_log_ids", carried)
        record.exc_info = sys.exc_info()
    # when
    kept = logging.Filter().filter(record) and True
    from ascend_python_common.request_context import CorrelationIdLogFilter

    applied = CorrelationIdLogFilter().filter(record)
    # then
    assert kept is True
    assert applied is True
    assert record.correlation_id == CORRELATION_ID  # type: ignore[attr-defined]
    assert record.mcp_session_id == SESSION_DIGEST  # type: ignore[attr-defined]


def test_record_with_unusable_exc_info_falls_back_to_unbound_ids() -> None:
    # given
    from ascend_python_common.request_context import CorrelationIdLogFilter

    plain = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg="plain",
        args=(),
        exc_info=None,
    )
    plain.exc_info = "not-a-tuple"  # type: ignore[assignment]
    other = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg="other",
        args=(),
        exc_info=None,
    )
    other.exc_info = (ValueError, "not-an-exception", None)  # type: ignore[assignment]
    # when
    assert CorrelationIdLogFilter().filter(plain) is True
    assert CorrelationIdLogFilter().filter(other) is True
    # then
    assert plain.correlation_id == ABSENT_FIELD  # type: ignore[attr-defined]
    assert other.correlation_id == ABSENT_FIELD  # type: ignore[attr-defined]


def test_framework_loggers_are_routed_through_root(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    restored_logging: None,
) -> None:
    # given
    monkeypatch.setattr(settings, "LOG_FORMAT", "json")
    monkeypatch.setattr(settings, "LOG_LEVEL", "INFO")
    fastmcp_logger = logging.getLogger("fastmcp")
    fastmcp_logger.addHandler(logging.NullHandler())
    fastmcp_logger.propagate = False
    # when
    configure_logging(SERVICE_NAME, settings)
    with mcp_request_log_context(CORRELATION_ID, SESSION_DIGEST):
        logging.getLogger("fastmcp.server.probe").warning("fastmcp probe line")
    captured = capsys.readouterr()
    # then
    assert fastmcp_logger.handlers == []
    assert fastmcp_logger.propagate is True
    routed = [logging.getLogger(name) for name in UVICORN_LOGGER_NAMES]
    assert [(each.handlers, each.level, each.propagate) for each in routed] == [
        ([], logging.NOTSET, True)
    ] * 3
    [line] = [line for line in captured.err.splitlines() if "fastmcp probe line" in line]
    assert CORRELATION_ID in line
    assert SESSION_DIGEST in line


def test_repeated_setup_attaches_the_transport_filter_once(
    monkeypatch: pytest.MonkeyPatch, restored_logging: None
) -> None:
    # given
    monkeypatch.setattr(settings, "LOG_FORMAT", "json")
    monkeypatch.setattr(settings, "LOG_LEVEL", "INFO")
    # when
    configure_logging(SERVICE_NAME, settings)
    configure_logging(SERVICE_NAME, settings)
    # then
    filter_counts = [
        sum(isinstance(each, McpSessionIdRedactionFilter) for each in logging.getLogger(name).filters)
        for name in MCP_TRANSPORT_LOGGER_NAMES
    ]
    assert filter_counts == [1, 1]


def test_failing_trace_filter_keeps_the_line_and_warns(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    restored_logging: None,
) -> None:
    # given
    monkeypatch.setattr(settings, "LOG_FORMAT", "json")
    monkeypatch.setattr(settings, "LOG_LEVEL", "INFO")
    configure_logging(SERVICE_NAME, settings)

    def _boom() -> object:
        raise RuntimeError("tracer broken")

    import opentelemetry.trace

    monkeypatch.setattr(opentelemetry.trace, "get_current_span", _boom)
    # when
    with pytest.warns(LogFilterFailureWarning):
        logging.getLogger("test.broken-filter").info("kept line")
    parsed = _last_json_line(capsys)
    # then
    assert parsed["message"] == "kept line"


def test_formatter_without_a_level_marker_returns_the_line_unchanged() -> None:
    # given
    plain = CenteredLevelFormatter("%(message)s", datefmt=DATE_FORMAT, log_colors=LOG_COLORS)
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg="no level marker",
        args=(),
        exc_info=None,
    )
    # when
    result = plain.format(record)
    # then
    assert "no level marker" in result
    assert "  INFO  " not in result


def test_color_format_defaults_both_ids_to_a_dash() -> None:
    # given
    expected = {"correlation_id": ABSENT_FIELD, "mcp_session_id": ABSENT_FIELD}
    # when
    actual = COLOR_FORMAT_DEFAULTS
    # then
    assert actual == expected


def test_base_filter_apply_raises_not_implemented() -> None:
    # given
    class _BareFilter(_NeverRaisingLogFilter):
        def _apply(self, record: logging.LogRecord) -> None:
            super()._apply(record)  # type: ignore[safe-super]

    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg="base",
        args=(),
        exc_info=None,
    )
    # when
    with pytest.raises(NotImplementedError):
        _BareFilter()._apply(record)
    # then
    assert record.msg == "base"


def test_get_logger_returns_the_named_logger() -> None:
    # given
    name = "my.module"
    # when
    logger = get_logger(name)
    # then
    assert logger.name == name

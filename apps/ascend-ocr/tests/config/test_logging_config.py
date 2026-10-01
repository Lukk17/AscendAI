import copy
import io
import json
import logging
import logging.config
import sys
import uuid
from collections.abc import Iterator

import pytest
from uvicorn.config import LOGGING_CONFIG as UVICORN_DEFAULT_LOG_CONFIG

from src.api.middleware.correlation_id import (
    McpSessionIdRedactionFilter,
    digest_of_mcp_session_id,
    mcp_request_log_context,
)
from src.config.config import settings
from src.config.logging_config import (
    APP_LOG_FORMAT,
    COLOR_FORMAT_DEFAULTS,
    DATE_FORMAT,
    LOG_COLORS,
    LOGGERS_ROUTED_THROUGH_ROOT,
    MCP_TRANSPORT_LOGGER_NAMES,
    UVICORN_LOGGER_NAMES,
    CenteredLevelFormatter,
    get_logger,
    setup_logging,
)
from src.config.startup_banner import log_startup_banner

FASTMCP_LOGGER = "fastmcp"
ABSENT_FIELD = "-"
CORRELATION_ID = "corr-1"
SESSION_DIGEST = "0123456789abcdef"
MCP_SESSION_MANAGER_LOGGER = "mcp.server.streamable_http_manager"
OTLP_EXPORTER_LOGGER = "opentelemetry.exporter.otlp.proto.grpc.exporter"
UVICORN_ACCESS_FORMAT = '%s - "%s %s HTTP/%s" %d'
UVICORN_ACCESS_ARGS = ("127.0.0.1:50123", "GET", "/health", "1.1", 200)
ACCESS_LINE_MARKER = '"GET /health HTTP/1.1" 200'
BANNER_LINE_MARKER = "Access URLs"


def _make_formatter() -> CenteredLevelFormatter:
    return CenteredLevelFormatter(
        APP_LOG_FORMAT,
        datefmt=DATE_FORMAT,
        log_colors=LOG_COLORS,
        defaults=COLOR_FORMAT_DEFAULTS,
    )


def _make_record(message: str, level: int = logging.INFO) -> logging.LogRecord:
    return logging.LogRecord(
        name="test",
        level=level,
        pathname="",
        lineno=0,
        msg=message,
        args=(),
        exc_info=None,
    )


class TestCenteredLevelFormatter:
    def test_formats_with_match(self):
        # Given
        formatter = _make_formatter()
        record = _make_record("hello")

        # When
        result = formatter.format(record)

        # Then
        assert "  INFO  " in result

    def test_no_match_returns_unchanged(self):
        # Given a formatter whose pattern won't match the centering regex
        plain = CenteredLevelFormatter("%(message)s", datefmt=DATE_FORMAT, log_colors=LOG_COLORS)
        record = _make_record("no level marker")

        # When
        result = plain.format(record)

        # Then. colorlog always appends a reset code; what matters is no centering happened.
        assert "no level marker" in result
        assert "  INFO  " not in result


@pytest.fixture
def restored_logging() -> Iterator[None]:
    root = logging.getLogger()
    routed_loggers = [logging.getLogger(name) for name in LOGGERS_ROUTED_THROUGH_ROOT]
    saved_root = (list(root.handlers), root.level)
    saved_routed = [(list(each.handlers), each.level, each.propagate) for each in routed_loggers]

    try:
        yield
    finally:
        root.handlers[:] = saved_root[0]
        root.setLevel(saved_root[1])
        for routed_logger, (handlers, level, propagate) in zip(routed_loggers, saved_routed, strict=True):
            routed_logger.handlers[:] = handlers
            routed_logger.setLevel(level)
            routed_logger.propagate = propagate


def _last_json_line(capsys: pytest.CaptureFixture[str]) -> dict[str, object]:
    captured = capsys.readouterr()
    parsed: dict[str, object] = json.loads((captured.err + captured.out).strip().splitlines()[-1])

    return parsed


class TestSetupLogging:
    def test_setup_logging_color_mode(self, monkeypatch):
        # Given
        monkeypatch.setattr(settings, "LOG_FORMAT", "color")

        # When
        setup_logging()

        # Then
        root = logging.getLogger()
        assert root.handlers

    def test_setup_logging_json_mode_emits_json(self, monkeypatch, capsys):
        # Given
        monkeypatch.setattr(settings, "LOG_FORMAT", "json")
        setup_logging()
        logger = logging.getLogger("test.json")

        # When
        logger.info("hello structured")
        captured = capsys.readouterr()

        # Then
        line = (captured.err + captured.out).strip().splitlines()[-1]
        parsed = json.loads(line)
        assert parsed["message"] == "hello structured"
        assert parsed["service"] == "ascend-ocr"
        assert "correlation_id" in parsed

    def test_json_line_names_the_session_digest_and_correlation_id_of_an_mcp_request(
        self, monkeypatch, capsys, restored_logging
    ):
        # Given
        monkeypatch.setattr(settings, "LOG_FORMAT", "json")
        setup_logging()

        # When
        with mcp_request_log_context(CORRELATION_ID, SESSION_DIGEST):
            logging.getLogger("test.json").info("inside a request")
        parsed = _last_json_line(capsys)

        # Then
        assert parsed["correlation_id"] == CORRELATION_ID
        assert parsed["mcp_session_id"] == SESSION_DIGEST

    def test_json_line_outside_an_mcp_request_names_the_session_field_as_null(
        self, monkeypatch, capsys, restored_logging
    ):
        # Given
        monkeypatch.setattr(settings, "LOG_FORMAT", "json")
        setup_logging()

        # When
        logging.getLogger("test.json").info("outside a request")
        parsed = _last_json_line(capsys)

        # Then
        assert "mcp_session_id" in parsed
        assert parsed["mcp_session_id"] is None

    @pytest.mark.parametrize("logger_name", [OTLP_EXPORTER_LOGGER, MCP_SESSION_MANAGER_LOGGER])
    def test_json_line_of_an_error_logged_with_exc_info_false_is_written(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        restored_logging: None,
        logger_name: str,
    ) -> None:
        # Given
        monkeypatch.setattr(settings, "LOG_FORMAT", "json")
        setup_logging()

        # When
        logging.getLogger(logger_name).error("Failed to export %s", "traces", exc_info=False)
        parsed = _last_json_line(capsys)

        # Then
        assert parsed["message"] == "Failed to export traces"
        assert parsed["correlation_id"] == ABSENT_FIELD
        assert "exc_info" not in parsed

    def test_color_line_carries_the_correlation_id_and_the_session_digest(self, monkeypatch, capsys, restored_logging):
        # Given
        monkeypatch.setattr(settings, "LOG_FORMAT", "color")
        setup_logging()

        # When
        with mcp_request_log_context(CORRELATION_ID, SESSION_DIGEST):
            logging.getLogger("test.color").info("inside a request")
        captured = capsys.readouterr()

        # Then
        assert f"[{CORRELATION_ID} {SESSION_DIGEST}]" in captured.err

    def test_color_line_outside_an_mcp_request_shows_a_dash_for_the_session(
        self, monkeypatch, capsys, restored_logging
    ):
        # Given
        monkeypatch.setattr(settings, "LOG_FORMAT", "color")
        setup_logging()

        # When
        logging.getLogger("test.color").info("outside a request")
        captured = capsys.readouterr()

        # Then
        assert f"[{ABSENT_FIELD} {ABSENT_FIELD}]" in captured.err

    @pytest.mark.parametrize("log_format", ["json", "color"])
    def test_fastmcp_lines_leave_their_own_handler_and_reach_the_root_handler(
        self, monkeypatch, capsys, restored_logging, log_format
    ):
        # Given
        monkeypatch.setattr(settings, "LOG_FORMAT", log_format)
        fastmcp_logger = logging.getLogger(FASTMCP_LOGGER)
        fastmcp_logger.addHandler(logging.NullHandler())
        fastmcp_logger.propagate = False

        # When
        setup_logging()
        with mcp_request_log_context(CORRELATION_ID, SESSION_DIGEST):
            logging.getLogger(f"{FASTMCP_LOGGER}.server.probe").warning("fastmcp probe line")
        captured = capsys.readouterr()

        # Then
        assert fastmcp_logger.handlers == []
        assert fastmcp_logger.propagate is True
        [line] = [line for line in captured.err.splitlines() if "fastmcp probe line" in line]
        assert CORRELATION_ID in line
        assert SESSION_DIGEST in line


class TestUvicornLinesAfterUvicornConfiguredLogging:
    @pytest.mark.usefixtures("restored_logging")
    def test_access_and_banner_lines_come_out_as_json_with_both_fields(self, monkeypatch, capsys):
        # Given
        monkeypatch.setattr(settings, "LOG_FORMAT", "json")
        monkeypatch.setattr(settings, "LOG_LEVEL", "INFO")
        logging.config.dictConfig(copy.deepcopy(UVICORN_DEFAULT_LOG_CONFIG))
        setup_logging()

        # When
        with mcp_request_log_context(CORRELATION_ID, SESSION_DIGEST):
            logging.getLogger("uvicorn.access").info(UVICORN_ACCESS_FORMAT, *UVICORN_ACCESS_ARGS)
            log_startup_banner()
        captured = capsys.readouterr()

        # Then
        assert captured.out == ""
        lines = [json.loads(line) for line in captured.err.splitlines() if line.strip()]
        [access_line] = [line for line in lines if ACCESS_LINE_MARKER in str(line["message"])]
        [banner_line] = [line for line in lines if BANNER_LINE_MARKER in str(line["message"])]
        for line in (access_line, banner_line):
            assert (line["correlation_id"], line["mcp_session_id"]) == (CORRELATION_ID, SESSION_DIGEST)

    @pytest.mark.usefixtures("restored_logging")
    def test_color_access_line_carries_both_ids(self, monkeypatch, capsys):
        # Given
        monkeypatch.setattr(settings, "LOG_FORMAT", "color")
        monkeypatch.setattr(settings, "LOG_LEVEL", "INFO")
        logging.config.dictConfig(copy.deepcopy(UVICORN_DEFAULT_LOG_CONFIG))
        setup_logging()

        # When
        with mcp_request_log_context(CORRELATION_ID, SESSION_DIGEST):
            logging.getLogger("uvicorn.access").info(UVICORN_ACCESS_FORMAT, *UVICORN_ACCESS_ARGS)
        captured = capsys.readouterr()

        # Then
        assert captured.out == ""
        [access_line] = [line for line in captured.err.splitlines() if ACCESS_LINE_MARKER in line]
        assert f"[{CORRELATION_ID} {SESSION_DIGEST}]" in access_line

    @pytest.mark.usefixtures("restored_logging")
    def test_uvicorn_loggers_keep_no_handler_of_their_own(self, monkeypatch):
        # Given
        monkeypatch.setattr(settings, "LOG_FORMAT", "json")
        logging.config.dictConfig(copy.deepcopy(UVICORN_DEFAULT_LOG_CONFIG))

        # When
        setup_logging()

        # Then
        routed = [logging.getLogger(name) for name in UVICORN_LOGGER_NAMES]
        assert [(each.handlers, each.level, each.propagate) for each in routed] == [([], logging.NOTSET, True)] * 3


class TestMcpTransportLoggerRedaction:
    @pytest.mark.usefixtures("restored_logging")
    def test_a_handler_added_after_setup_never_sees_the_raw_session_id(self, monkeypatch):
        # Given
        monkeypatch.setattr(settings, "LOG_LEVEL", "INFO")
        setup_logging()
        late_stream = io.StringIO()
        late_handler = logging.StreamHandler(late_stream)
        logging.getLogger().addHandler(late_handler)
        session_id = uuid.uuid4().hex

        # When
        logging.getLogger(MCP_SESSION_MANAGER_LOGGER).info("Created new transport with session ID: %s", session_id)

        # Then
        written = late_stream.getvalue()
        assert session_id not in written
        assert digest_of_mcp_session_id(session_id) in written

    @pytest.mark.usefixtures("restored_logging")
    def test_repeated_setup_attaches_the_logger_filter_once(self):
        # When
        setup_logging()
        setup_logging()

        # Then
        filter_counts = [
            sum(isinstance(each, McpSessionIdRedactionFilter) for each in logging.getLogger(name).filters)
            for name in MCP_TRANSPORT_LOGGER_NAMES
        ]
        assert filter_counts == [1, 1]


class TestColorFormatDefaults:
    def test_both_ids_default_to_a_dash(self):
        # Then
        assert COLOR_FORMAT_DEFAULTS == {"correlation_id": ABSENT_FIELD, "mcp_session_id": ABSENT_FIELD}


class TestGetLogger:
    def test_returns_logger_named_correctly(self):
        # When
        logger = get_logger("my.module")

        # Then
        assert logger.name == "my.module"


def teardown_module():
    sys.stdout.flush()
    sys.stderr.flush()

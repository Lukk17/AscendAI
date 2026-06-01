import json
import logging
import sys

from src.config.config import settings
from src.config.logging_config import (
    APP_LOG_FORMAT,
    DATE_FORMAT,
    LOG_COLORS,
    CenteredLevelFormatter,
    get_logger,
    get_uvicorn_log_config,
    setup_logging,
)


def _make_formatter() -> CenteredLevelFormatter:
    return CenteredLevelFormatter(
        APP_LOG_FORMAT,
        datefmt=DATE_FORMAT,
        log_colors=LOG_COLORS,
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
        assert parsed["service"] == "paddleocr"
        assert "correlation_id" in parsed


class TestUvicornLogConfig:
    def test_returns_json_config_when_format_json(self, monkeypatch):
        # Given
        monkeypatch.setattr(settings, "LOG_FORMAT", "json")

        # When
        config = get_uvicorn_log_config()

        # Then
        assert config["formatters"]["json"]["()"].endswith("JsonFormatter")

    def test_returns_color_config_when_format_color(self, monkeypatch):
        # Given
        monkeypatch.setattr(settings, "LOG_FORMAT", "color")

        # When
        config = get_uvicorn_log_config()

        # Then
        assert config["formatters"]["default"]["()"].endswith("CenteredLevelFormatter")


class TestGetLogger:
    def test_returns_logger_named_correctly(self):
        # When
        logger = get_logger("my.module")

        # Then
        assert logger.name == "my.module"


def teardown_module():
    sys.stdout.flush()
    sys.stderr.flush()

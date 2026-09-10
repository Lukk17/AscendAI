import logging

from src.config.logging_config import (
    _LOG_COLORS,
    CenteredLevelFormatter,
    CorrelationFilter,
    get_logger,
    get_uvicorn_log_config,
    setup_logging,
)
from src.observability.request_context import request_id_ctx


def _make_record(level: int = logging.INFO, msg: str = "hello") -> logging.LogRecord:
    return logging.LogRecord(
        name="test",
        level=level,
        pathname=__file__,
        lineno=1,
        msg=msg,
        args=None,
        exc_info=None,
    )


def test_centered_level_formatter_centres_level_token() -> None:
    fmt = CenteredLevelFormatter(
        "%(log_color)s - %(levelname)s - %(message)s", log_colors=_LOG_COLORS
    )
    record = _make_record(logging.INFO)
    formatted = fmt.format(record)
    assert "  INFO  " in formatted


def test_centered_level_formatter_passthrough_when_no_match() -> None:
    fmt = CenteredLevelFormatter("%(log_color)s%(message)s", log_colors=_LOG_COLORS)
    record = _make_record(msg="plain")
    formatted = fmt.format(record)
    assert "plain" in formatted


def test_correlation_filter_injects_request_id() -> None:
    token = request_id_ctx.set("req-abc")
    try:
        record = _make_record()
        accepted = CorrelationFilter().filter(record)
        assert accepted is True
        # CorrelationFilter injects request_id as a dynamic LogRecord attribute;
        # use getattr so static analysers don't complain about the unmodelled
        # field.
        assert getattr(record, "request_id", None) == "req-abc"
    finally:
        request_id_ctx.reset(token)


def test_setup_logging_attaches_correlation_filter() -> None:
    setup_logging()
    root = logging.getLogger()
    assert root.handlers
    assert any(
        isinstance(f, CorrelationFilter)
        for handler in root.handlers
        for f in handler.filters
    )


def test_uvicorn_log_config_shape_is_complete() -> None:
    cfg = get_uvicorn_log_config()
    assert cfg["version"] == 1
    assert "correlation" in cfg["filters"]
    assert {"default", "access"} <= set(cfg["formatters"].keys())
    assert "correlation" in cfg["handlers"]["default"]["filters"]


def test_get_logger_returns_logger_instance() -> None:
    log = get_logger("test.module")
    assert isinstance(log, logging.Logger)
    assert log.name == "test.module"

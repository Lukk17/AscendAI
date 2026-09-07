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


def _record(level: int = logging.INFO, msg: str = "hello") -> logging.LogRecord:
    return logging.LogRecord(
        name="test",
        level=level,
        pathname=__file__,
        lineno=1,
        msg=msg,
        args=None,
        exc_info=None,
    )


def test_centered_level_formatter_pads_level() -> None:
    fmt = CenteredLevelFormatter("%(log_color)s - %(levelname)s - %(message)s", log_colors=_LOG_COLORS)
    formatted = fmt.format(_record(logging.INFO))
    assert "  INFO  " in formatted


def test_centered_level_formatter_passthrough_when_no_match() -> None:
    fmt = CenteredLevelFormatter("%(log_color)s%(message)s", log_colors=_LOG_COLORS)
    formatted = fmt.format(_record(msg="plain"))
    assert "plain" in formatted


def test_correlation_filter_injects_request_id() -> None:
    token = request_id_ctx.set("req-x")
    try:
        record = _record()
        assert CorrelationFilter().filter(record) is True
        assert getattr(record, "request_id", None) == "req-x"
    finally:
        request_id_ctx.reset(token)


def test_setup_logging_installs_correlation_filter() -> None:
    setup_logging()
    root = logging.getLogger()
    assert any(
        isinstance(f, CorrelationFilter) for h in root.handlers for f in h.filters
    )


def test_uvicorn_log_config_shape() -> None:
    cfg = get_uvicorn_log_config()
    assert cfg["version"] == 1
    assert "correlation" in cfg["filters"]
    assert "default" in cfg["formatters"]
    assert "correlation" in cfg["handlers"]["default"]["filters"]


def test_get_logger() -> None:
    assert isinstance(get_logger("x"), logging.Logger)

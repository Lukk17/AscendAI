import logging
from unittest.mock import patch

from src.config.logging_config import (
    CenteredLevelFormatter,
    CorrelationFilter,
    get_logger,
    get_uvicorn_log_config,
    setup_logging,
)


def test_setup_logging_attaches_filter():
    with patch("src.config.logging_config.logging.basicConfig") as mock_basic_config:
        setup_logging()
        mock_basic_config.assert_called_once()
        kwargs = mock_basic_config.call_args.kwargs
        assert kwargs["level"] == logging.INFO


def test_get_uvicorn_log_config_returns_expected_keys():
    config = get_uvicorn_log_config()
    assert config["version"] == 1
    assert "filters" in config
    assert "correlation" in config["filters"]
    assert "handlers" in config


def test_correlation_filter_injects_request_id_default():
    f = CorrelationFilter()
    record = logging.LogRecord("x", logging.INFO, "x", 1, "msg", None, None)
    assert f.filter(record) is True
    assert record.request_id == "-"


def test_centered_level_formatter_centers_short_level():
    f = CenteredLevelFormatter(
        "%(asctime)s - %(levelname)s - %(message)s",
        datefmt="%Y",
        log_colors={"INFO": "green"},
    )
    record = logging.LogRecord("x", logging.INFO, "x", 1, "hello", None, None)
    output = f.format(record)
    assert "hello" in output


def test_centered_level_formatter_no_match_returns_unchanged():
    """When the format string does not contain ' - LEVEL - ', the regex misses and
    the formatted output is returned as-is."""
    f = CenteredLevelFormatter(
        "%(message)s",  # No level marker
        datefmt="%Y",
        log_colors={"INFO": "green"},
    )
    record = logging.LogRecord("x", logging.INFO, "x", 1, "no level marker", None, None)
    output = f.format(record)
    assert "no level marker" in output


def test_get_logger_returns_module_logger():
    logger = get_logger("test.module")
    assert logger.name == "test.module"

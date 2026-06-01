import logging
import re
from typing import Any

import colorlog

from src.observability.request_context import request_id_ctx

_LOG_COLORS = {
    "DEBUG": "cyan",
    "INFO": "green",
    "WARNING": "yellow",
    "ERROR": "red",
    "CRITICAL": "red",
}


class CenteredLevelFormatter(colorlog.ColoredFormatter):
    def format(self, record: logging.LogRecord) -> str:
        formatted = super().format(record)
        # Match " - LEVEL - " and centre the captured level inside an 8-char
        # column so vertical alignment survives across level names.
        level_match = re.search(r"(- )(\w+)( -)", formatted)
        if level_match:
            level_text = level_match.group(2)
            centered_level = level_text.center(8)
            formatted = (
                formatted[: level_match.start(2)]
                + centered_level
                + formatted[level_match.end(2) :]
            )
        return formatted


class CorrelationFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        # LogRecord allows dynamic attribute injection at runtime; use setattr
        # so static analysers don't complain about the unmodelled field.
        setattr(record, "request_id", request_id_ctx.get())  # noqa: B010
        return True


def setup_logging() -> None:
    """Configure application-wide logging with colors and correlation IDs."""

    log_format = (
        "%(log_color)s[AudioScribe] %(asctime)s - %(levelname)s - %(module)-18s "
        "[%(request_id)s]%(reset)s >> %(log_color)s%(message)s"
    )

    app_formatter = CenteredLevelFormatter(
        log_format,
        datefmt="%Y-%m-%d %H:%M:%S",
        log_colors=_LOG_COLORS,
    )

    handler = colorlog.StreamHandler()
    handler.setFormatter(app_formatter)
    handler.addFilter(CorrelationFilter())

    logging.basicConfig(level=logging.INFO, handlers=[handler], force=True)


def get_uvicorn_log_config() -> dict[str, Any]:
    """Generate a logging configuration dictionary for Uvicorn that uses
    CenteredLevelFormatter and the correlation filter."""

    log_format = (
        "%(log_color)s[AudioScribe] %(asctime)s - %(levelname)s - [%(request_id)s] - %(message)s"
    )

    return {
        "version": 1,
        "disable_existing_loggers": False,
        "filters": {
            "correlation": {
                "()": "src.config.logging_config.CorrelationFilter",
            },
        },
        "formatters": {
            "default": {
                "()": "src.config.logging_config.CenteredLevelFormatter",
                "fmt": log_format,
                "datefmt": "%Y-%m-%d %H:%M:%S",
                "log_colors": _LOG_COLORS,
            },
            "access": {
                "()": "src.config.logging_config.CenteredLevelFormatter",
                "fmt": log_format,
                "datefmt": "%Y-%m-%d %H:%M:%S",
                "log_colors": _LOG_COLORS,
            },
        },
        "handlers": {
            "default": {
                "formatter": "default",
                "class": "logging.StreamHandler",
                "stream": "ext://sys.stderr",
                "filters": ["correlation"],
            },
            "access": {
                "formatter": "access",
                "class": "logging.StreamHandler",
                "stream": "ext://sys.stdout",
                "filters": ["correlation"],
            },
        },
        "loggers": {
            "uvicorn": {"handlers": ["default"], "level": "INFO", "propagate": False},
            "uvicorn.error": {"level": "INFO"},
            "uvicorn.access": {"handlers": ["access"], "level": "INFO", "propagate": False},
        },
    }


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)

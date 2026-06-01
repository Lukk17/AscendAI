import logging
import re

import colorlog

from src.observability.request_context import request_id_ctx


class CenteredLevelFormatter(colorlog.ColoredFormatter):
    def format(self, record: logging.LogRecord) -> str:
        # Let the parent class handle the initial formatting and coloring
        s = super().format(record)

        # This regex looks for " - [LEVEL] - " and captures the level part.
        match = re.search(r"(- )(\w+)( -)", s)
        if match:
            level_text = match.group(2)
            # Center the original level text and replace it in the formatted string
            centered_level = level_text.center(8)
            s = s[: match.start(2)] + centered_level + s[match.end(2) :]
        return s


class CorrelationFilter(logging.Filter):
    # noinspection PyUnresolvedReferences
    def filter(self, record: logging.LogRecord) -> bool:
        # LogRecord accepts arbitrary attributes for log-format interpolation,
        # but mypy/PyCharm don't see request_id on the class itself.
        record.request_id = request_id_ctx.get()
        return True


def setup_logging() -> None:
    """Configure application-wide logging with colors."""

    custom_log_colors = {
        "DEBUG": "cyan",
        "INFO": "green",
        "WARNING": "yellow",
        "ERROR": "red",
        "CRITICAL": "red",
    }

    log_format = (
        "%(log_color)s[AscendSearch] %(asctime)s - %(levelname)s - %(module)-18s "
        "[%(request_id)s]%(reset)s >> %(log_color)s%(message)s"
    )

    app_formatter = CenteredLevelFormatter(
        log_format, datefmt="%Y-%m-%d %H:%M:%S", log_colors=custom_log_colors
    )

    handler = colorlog.StreamHandler()
    handler.setFormatter(app_formatter)
    handler.addFilter(CorrelationFilter())

    logging.basicConfig(level=logging.INFO, handlers=[handler], force=True)


def get_uvicorn_log_config() -> dict:
    """
    Generate a logging configuration dictionary for Uvicorn that uses
    CenteredLevelFormatter for consistent output with the application.
    """
    custom_log_colors = {
        "DEBUG": "cyan",
        "INFO": "green",
        "WARNING": "yellow",
        "ERROR": "red",
        "CRITICAL": "red",
    }

    log_format = "%(log_color)s[AscendSearch] %(asctime)s - %(levelname)s - [%(request_id)s] - %(message)s"

    return {
        "version": 1,
        "disable_existing_loggers": False,
        "filters": {
            "correlation": {
                "()": "src.config.logging_config.CorrelationFilter",
            }
        },
        "formatters": {
            "default": {
                "()": "src.config.logging_config.CenteredLevelFormatter",
                "fmt": log_format,
                "datefmt": "%Y-%m-%d %H:%M:%S",
                "log_colors": custom_log_colors,
            },
            "access": {
                "()": "src.config.logging_config.CenteredLevelFormatter",
                "fmt": log_format,
                "datefmt": "%Y-%m-%d %H:%M:%S",
                "log_colors": custom_log_colors,
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
    """Get a logger instance for the given module name."""
    return logging.getLogger(name)

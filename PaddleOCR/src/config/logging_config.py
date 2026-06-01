import logging
import re

import colorlog
from pythonjsonlogger.json import JsonFormatter

from src.api.middleware.correlation_id import CorrelationIdLogFilter
from src.config.config import settings


class CenteredLevelFormatter(colorlog.ColoredFormatter):
    def format(self, record: logging.LogRecord) -> str:
        formatted_string: str = super().format(record)
        match = re.search(r"(- )(\w+)( -)", formatted_string)
        if not match:
            return formatted_string

        level_text: str = match.group(2)
        centered_level: str = level_text.center(8)

        return formatted_string[: match.start(2)] + centered_level + formatted_string[match.end(2) :]


LOG_COLORS: dict[str, str] = {
    "DEBUG": "cyan",
    "INFO": "green",
    "WARNING": "yellow",
    "ERROR": "red",
    "CRITICAL": "red",
}

APP_LOG_FORMAT: str = (
    "%(log_color)s[PaddleOCR] %(asctime)s - %(levelname)s - %(module)-18s%(reset)s >> %(log_color)s%(message)s"
)

UVICORN_LOG_FORMAT: str = "%(log_color)s[PaddleOCR] %(asctime)s - %(levelname)s - %(message)s"

JSON_LOG_FIELDS: str = "%(asctime)s %(levelname)s %(name)s %(module)s %(message)s %(correlation_id)s"

DATE_FORMAT: str = "%Y-%m-%d %H:%M:%S"

_STREAM_HANDLER_CLASS: str = "logging.StreamHandler"
_CORRELATION_FILTER_CLASS: str = "src.api.middleware.correlation_id.CorrelationIdLogFilter"
_CENTERED_FORMATTER_CLASS: str = "src.config.logging_config.CenteredLevelFormatter"
_JSON_FORMATTER_CLASS: str = "pythonjsonlogger.json.JsonFormatter"


def _build_json_handler() -> logging.Handler:
    handler = logging.StreamHandler()
    handler.setFormatter(
        JsonFormatter(
            JSON_LOG_FIELDS,
            datefmt=DATE_FORMAT,
            rename_fields={"asctime": "timestamp", "levelname": "level"},
            static_fields={"service": "paddleocr"},
        )
    )
    handler.addFilter(CorrelationIdLogFilter())

    return handler


def _build_color_handler() -> logging.Handler:
    handler = colorlog.StreamHandler()
    handler.setFormatter(
        CenteredLevelFormatter(
            APP_LOG_FORMAT,
            datefmt=DATE_FORMAT,
            log_colors=LOG_COLORS,
        )
    )
    handler.addFilter(CorrelationIdLogFilter())

    return handler


def setup_logging() -> None:
    handler = _build_json_handler() if settings.LOG_FORMAT == "json" else _build_color_handler()

    logging.basicConfig(
        level=settings.LOG_LEVEL,
        handlers=[handler],
        force=True,
    )


def get_uvicorn_log_config() -> dict:
    if settings.LOG_FORMAT == "json":
        return _uvicorn_json_log_config()

    return _uvicorn_color_log_config()


def _uvicorn_json_log_config() -> dict:
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "json": {
                "()": _JSON_FORMATTER_CLASS,
                "fmt": JSON_LOG_FIELDS,
                "datefmt": DATE_FORMAT,
                "rename_fields": {"asctime": "timestamp", "levelname": "level"},
                "static_fields": {"service": "paddleocr"},
            },
        },
        "filters": {
            "correlation_id": {
                "()": _CORRELATION_FILTER_CLASS,
            },
        },
        "handlers": {
            "default": {
                "formatter": "json",
                "filters": ["correlation_id"],
                "class": _STREAM_HANDLER_CLASS,
                "stream": "ext://sys.stderr",
            },
            "access": {
                "formatter": "json",
                "filters": ["correlation_id"],
                "class": _STREAM_HANDLER_CLASS,
                "stream": "ext://sys.stdout",
            },
        },
        "loggers": {
            "uvicorn": {"handlers": ["default"], "level": "INFO", "propagate": False},
            "uvicorn.error": {"level": "INFO"},
            "uvicorn.access": {"handlers": ["access"], "level": "INFO", "propagate": False},
        },
    }


def _uvicorn_color_log_config() -> dict:
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "default": {
                "()": _CENTERED_FORMATTER_CLASS,
                "fmt": UVICORN_LOG_FORMAT,
                "datefmt": DATE_FORMAT,
                "log_colors": LOG_COLORS,
            },
            "access": {
                "()": _CENTERED_FORMATTER_CLASS,
                "fmt": UVICORN_LOG_FORMAT,
                "datefmt": DATE_FORMAT,
                "log_colors": LOG_COLORS,
            },
        },
        "filters": {
            "correlation_id": {
                "()": _CORRELATION_FILTER_CLASS,
            },
        },
        "handlers": {
            "default": {
                "formatter": "default",
                "filters": ["correlation_id"],
                "class": _STREAM_HANDLER_CLASS,
                "stream": "ext://sys.stderr",
            },
            "access": {
                "formatter": "access",
                "filters": ["correlation_id"],
                "class": _STREAM_HANDLER_CLASS,
                "stream": "ext://sys.stdout",
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

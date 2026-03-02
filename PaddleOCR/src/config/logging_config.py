import colorlog
import logging
import re


class CenteredLevelFormatter(colorlog.ColoredFormatter):
    def format(self, record: logging.LogRecord) -> str:
        formatted_string: str = super().format(record)
        match = re.search(r'(- )(\w+)( -)', formatted_string)
        if not match:
            return formatted_string
        level_text: str = match.group(2)
        centered_level: str = level_text.center(8)
        return formatted_string[:match.start(2)] + centered_level + formatted_string[match.end(2):]


LOG_COLORS: dict[str, str] = {
    "DEBUG": "cyan",
    "INFO": "green",
    "WARNING": "yellow",
    "ERROR": "red",
    "CRITICAL": "red",
}

APP_LOG_FORMAT: str = (
    "%(log_color)s[PaddleOCR] %(asctime)s - %(levelname)s - %(module)-18s%(reset)s >> "
    "%(log_color)s%(message)s"
)

UVICORN_LOG_FORMAT: str = (
    "%(log_color)s[PaddleOCR] %(asctime)s - %(levelname)s - %(message)s"
)

DATE_FORMAT: str = "%Y-%m-%d %H:%M:%S"


def setup_logging() -> None:
    app_formatter = CenteredLevelFormatter(
        APP_LOG_FORMAT,
        datefmt=DATE_FORMAT,
        log_colors=LOG_COLORS,
    )
    handler = colorlog.StreamHandler()
    handler.setFormatter(app_formatter)
    logging.basicConfig(
        level=logging.INFO,
        handlers=[handler],
        force=True,
    )


def get_uvicorn_log_config() -> dict:
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "default": {
                "()": "src.config.logging_config.CenteredLevelFormatter",
                "fmt": UVICORN_LOG_FORMAT,
                "datefmt": DATE_FORMAT,
                "log_colors": LOG_COLORS,
            },
            "access": {
                "()": "src.config.logging_config.CenteredLevelFormatter",
                "fmt": UVICORN_LOG_FORMAT,
                "datefmt": DATE_FORMAT,
                "log_colors": LOG_COLORS,
            },
        },
        "handlers": {
            "default": {
                "formatter": "default",
                "class": "logging.StreamHandler",
                "stream": "ext://sys.stderr",
            },
            "access": {
                "formatter": "access",
                "class": "logging.StreamHandler",
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

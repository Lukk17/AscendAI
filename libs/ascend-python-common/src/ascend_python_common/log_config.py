import logging
import re

import colorlog
from opentelemetry import trace
from pythonjsonlogger.json import JsonFormatter

from ascend_python_common.request_context import (
    CorrelationIdLogFilter,
    McpSessionIdRedactionFilter,
    _NeverRaisingLogFilter,
)
from ascend_python_common.settings import ServiceSettings


class CenteredLevelFormatter(colorlog.ColoredFormatter):
    def format(self, record: logging.LogRecord) -> str:
        formatted_string: str = super().format(record)
        match = re.search(r"(- )(\w+)( -)", formatted_string)
        if not match:
            return formatted_string

        level_text: str = match.group(2)
        centered_level: str = level_text.center(8)

        return formatted_string[: match.start(2)] + centered_level + formatted_string[match.end(2) :]


class TraceIdsLogFilter(_NeverRaisingLogFilter):
    def _apply(self, record: logging.LogRecord) -> None:
        span_context = trace.get_current_span().get_span_context()
        if span_context.is_valid:
            record.trace_id = f"{span_context.trace_id:032x}"
            record.span_id = f"{span_context.span_id:016x}"
        else:
            record.trace_id = ABSENT_LOG_FIELD
            record.span_id = ABSENT_LOG_FIELD


LOG_COLORS: dict[str, str] = {
    "DEBUG": "cyan",
    "INFO": "green",
    "WARNING": "yellow",
    "ERROR": "red",
    "CRITICAL": "red",
}


def _color_log_format(service_name: str) -> str:
    return (
        f"%(log_color)s[{service_name}] %(asctime)s - %(levelname)s - %(module)-18s"
        " [%(correlation_id)s %(mcp_session_id)s]%(reset)s >> %(log_color)s%(message)s"
    )


JSON_LOG_FIELDS: str = (
    "%(asctime)s %(levelname)s %(name)s %(module)s %(message)s"
    " %(correlation_id)s %(mcp_session_id)s %(trace_id)s %(span_id)s"
)

ABSENT_LOG_FIELD: str = "-"
COLOR_FORMAT_DEFAULTS: dict[str, str] = {
    "correlation_id": ABSENT_LOG_FIELD,
    "mcp_session_id": ABSENT_LOG_FIELD,
}

FASTMCP_LOGGER_NAME: str = "fastmcp"
UVICORN_LOGGER_NAMES: tuple[str, ...] = ("uvicorn", "uvicorn.error", "uvicorn.access")
LOGGERS_ROUTED_THROUGH_ROOT: tuple[str, ...] = (
    FASTMCP_LOGGER_NAME,
    *UVICORN_LOGGER_NAMES,
)
MCP_TRANSPORT_LOGGER_NAMES: tuple[str, ...] = (
    "mcp.server.streamable_http_manager",
    "mcp.server.streamable_http",
)

DATE_FORMAT: str = "%Y-%m-%d %H:%M:%S"

_MCP_TRANSPORT_REDACTION_FILTER: McpSessionIdRedactionFilter = McpSessionIdRedactionFilter()


def _build_json_handler(service_name: str) -> logging.Handler:
    handler = logging.StreamHandler()
    handler.setFormatter(
        JsonFormatter(
            JSON_LOG_FIELDS,
            datefmt=DATE_FORMAT,
            rename_fields={"asctime": "timestamp", "levelname": "level"},
            static_fields={"service": service_name},
        )
    )
    _add_handler_filters(handler)

    return handler


def _build_color_handler(service_name: str) -> logging.Handler:
    handler = colorlog.StreamHandler()
    handler.setFormatter(
        CenteredLevelFormatter(
            _color_log_format(service_name),
            datefmt=DATE_FORMAT,
            log_colors=LOG_COLORS,
            defaults=COLOR_FORMAT_DEFAULTS,
        )
    )
    _add_handler_filters(handler)

    return handler


def _add_handler_filters(handler: logging.Handler) -> None:
    handler.addFilter(CorrelationIdLogFilter())
    handler.addFilter(TraceIdsLogFilter())
    handler.addFilter(McpSessionIdRedactionFilter())


def _route_through_root(logger_name: str) -> None:
    routed_logger = logging.getLogger(logger_name)
    for own_handler in list(routed_logger.handlers):
        routed_logger.removeHandler(own_handler)

    routed_logger.setLevel(logging.NOTSET)
    routed_logger.propagate = True


def _redact_at_the_mcp_transport_loggers() -> None:
    for logger_name in MCP_TRANSPORT_LOGGER_NAMES:
        logging.getLogger(logger_name).addFilter(_MCP_TRANSPORT_REDACTION_FILTER)


def configure_logging(service_name: str, settings: ServiceSettings) -> None:
    handler = (
        _build_json_handler(service_name)
        if settings.LOG_FORMAT == "json"
        else _build_color_handler(service_name)
    )

    logging.basicConfig(
        level=settings.LOG_LEVEL,
        handlers=[handler],
        force=True,
    )
    for logger_name in LOGGERS_ROUTED_THROUGH_ROOT:
        _route_through_root(logger_name)
    _redact_at_the_mcp_transport_loggers()


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)

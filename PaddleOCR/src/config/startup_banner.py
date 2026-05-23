import logging
import socket

from src.config.config import settings

logger = logging.getLogger("uvicorn")

BANNER = (
    "██████╗  █████╗ ██████╗ ██████╗ ██╗     ███████╗     ██████╗  ██████╗██████╗ \n"
    "██╔══██╗██╔══██╗██╔══██╗██╔══██╗██║     ██╔════╝    ██╔═══██╗██╔════╝██╔══██╗\n"
    "██████╔╝███████║██║  ██║██║  ██║██║     █████╗      ██║   ██║██║     ██████╔╝\n"
    "██╔═══╝ ██╔══██║██║  ██║██║  ██║██║     ██╔══╝      ██║   ██║██║     ██╔══██╗\n"
    "██║     ██║  ██║██████╔╝██████╔╝███████╗███████╗    ╚██████╔╝╚██████╗██║  ██║\n"
    "╚═╝     ╚═╝  ╚═╝╚═════╝ ╚═════╝ ╚══════╝╚══════╝     ╚═════╝  ╚═════╝╚═╝  ╚═╝"
)

DIVIDER = "-" * 58
APP_NAME = "paddle-ocr"


def _resolve_host() -> str:
    try:
        return socket.gethostname()
    except OSError:
        return "localhost"


async def log_startup_banner() -> None:
    host = _resolve_host()
    port = settings.API_PORT
    local_url = f"http://localhost:{port}"
    hostname_url = f"http://{host}:{port}"

    block = "\n".join([
        "",
        BANNER,
        DIVIDER,
        f"    Application '{APP_NAME}' is running!",
        "",
        "    Access URLs:",
        f"      Local:     {local_url}",
        f"      Hostname:  {hostname_url}",
        "",
        f"    Profile(s): default (log level: {settings.LOG_LEVEL})",
        "",
        "    External services:",
        "      (none, PaddleOCR runs models locally; warm-up handled in lifespan)",
        "",
        "    Actuator:",
        f"      Health:    {local_url}/health",
        "",
        "    API documentation:",
        f"      OpenAPI:   {local_url}/openapi.json",
        f"      Swagger:   {local_url}/docs",
        f"      Redoc:     {local_url}/redoc",
        "",
        "    Observability:",
        "      Logging:   uvicorn formatter (src.config.logging_config)",
        "",
        "    MCP endpoint:",
        f"      HTTP:      POST {local_url}/mcp",
        "",
        "    Runtime config:",
        f"      Language:  {settings.DEFAULT_LANGUAGE}",
        f"      Max upload: {settings.MAX_FILE_SIZE_MB} MB",
        f"      Timeout:   {settings.OCR_REQUEST_TIMEOUT}s per request",
        DIVIDER,
    ])
    logger.info("\n%s", block)

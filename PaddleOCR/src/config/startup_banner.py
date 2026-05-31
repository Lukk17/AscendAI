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

DIVIDER = "-" * 80
APP_NAME = "paddle-ocr"


def _resolve_host() -> str:
    try:
        return socket.gethostname()
    except OSError:
        return "localhost"


def log_startup_banner() -> None:
    host = _resolve_host()
    port = settings.API_PORT
    local_url = f"http://localhost:{port}"
    hostname_url = f"http://{host}:{port}"

    file_uri_root = settings.MCP_FILE_URI_ROOT or "disabled"
    allowed_hosts = ", ".join(settings.MCP_ALLOWED_HOSTS) or "(none — public hosts only)"

    block = "\n".join(
        [
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
            f"      Ready:     {local_url}/ready",
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
            f"      file:// root:    {file_uri_root}",
            f"      Allowed hosts:   {allowed_hosts}",
            f"      Download timeout: {settings.MCP_DOWNLOAD_TIMEOUT_SECONDS}s",
            "",
            "    Runtime config:",
            f"      Language:  {settings.DEFAULT_LANGUAGE}",
            f"      Max upload: {settings.MAX_FILE_SIZE_MB} MB",
            f"      OCR timeout: {settings.OCR_REQUEST_TIMEOUT}s per request",
            f"      Engine cache cap: {settings.ENGINE_CACHE_MAX_SIZE} languages",
            DIVIDER,
        ]
    )
    logger.info("\n%s", block)

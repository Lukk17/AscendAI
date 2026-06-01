import asyncio
import logging
import socket
import urllib.error
import urllib.request
from urllib.parse import urlparse

from src.config.config import settings

logger = logging.getLogger("uvicorn")

BANNER = (
    " █████╗ ███████╗ ██████╗███████╗███╗   ██╗██████╗     ███████╗███████╗ █████╗ ██████╗  ██████╗██╗  ██╗\n"
    "██╔══██╗██╔════╝██╔════╝██╔════╝████╗  ██║██╔══██╗    ██╔════╝██╔════╝██╔══██╗██╔══██╗██╔════╝██║  ██║\n"
    "███████║███████╗██║     █████╗  ██╔██╗ ██║██║  ██║    ███████╗█████╗  ███████║██████╔╝██║     ███████║\n"
    "██╔══██║╚════██║██║     ██╔══╝  ██║╚██╗██║██║  ██║    ╚════██║██╔══╝  ██╔══██║██╔══██╗██║     ██╔══██║\n"
    "██║  ██║███████║╚██████╗███████╗██║ ╚████║██████╔╝    ███████║███████╗██║  ██║██║  ██║╚██████╗██║  ██║\n"
    "╚═╝  ╚═╝╚══════╝ ╚═════╝╚══════╝╚═╝  ╚═══╝╚═════╝     ╚══════╝╚══════╝╚═╝  ╚═╝╚═╝  ╚═╝ ╚═════╝╚═╝  ╚═╝"
)

DIVIDER = "-" * 58
PROBE_TIMEOUT_SECONDS = 2.0
APP_NAME = "ascend-web-search"


def _resolve_host() -> str:
    try:
        return socket.gethostname()
    except OSError:
        return "localhost"


def _probe_http_sync(url: str) -> str:
    try:
        # Probe URLs come from validated settings, not user input - S310 not applicable here.
        with urllib.request.urlopen(url, timeout=PROBE_TIMEOUT_SECONDS) as response:  # noqa: S310
            status = response.status
        if 200 <= status < 300:
            return f"{url} [Connected]"
        return f"{url} [Warning (status={status})]"
    except urllib.error.HTTPError as exc:
        return f"{url} [Warning (status={exc.code})]"
    except Exception as exc:
        logger.debug("Probe failed for %s: %s", url, exc)
        return f"{url} [FAILED]"


def _probe_tcp_sync(url: str) -> str:
    parsed = urlparse(url)
    host = parsed.hostname or "localhost"
    port = parsed.port or (6379 if parsed.scheme.startswith("redis") else 80)
    display = f"{parsed.scheme}://{host}:{port}"
    try:
        with socket.create_connection((host, port), timeout=PROBE_TIMEOUT_SECONDS):
            return f"{display} [Connected]"
    except Exception as exc:
        logger.debug("TCP probe failed for %s: %s", display, exc)
        return f"{display} [FAILED]"


async def log_startup_banner() -> None:
    host = _resolve_host()
    port = settings.API_PORT
    local_url = f"http://localhost:{port}"
    hostname_url = f"http://{host}:{port}"

    searxng_url = settings.SEARXNG_BASE_URL.rstrip("/") + "/healthz"
    flaresolverr_root = settings.FLARESOLVERR_URL.rsplit("/v1", 1)[0]

    searxng_status, flaresolverr_status, redis_status = await asyncio.gather(
        asyncio.to_thread(_probe_http_sync, searxng_url),
        asyncio.to_thread(_probe_http_sync, flaresolverr_root),
        asyncio.to_thread(_probe_tcp_sync, settings.REDIS_URL),
    )

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
            f"      SearXNG:      {searxng_status}",
            f"      FlareSolverr: {flaresolverr_status}",
            f"      Redis:        {redis_status}",
            f"      Blocklist:    {settings.BLOCKLIST_URL} [Loaded at startup]",
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
            "    REST endpoints:",
            f"      Search v1: GET  {local_url}/v1/search",
            f"      Read v1:   GET  {local_url}/v1/read",
            f"      Search v2: POST {local_url}/v2/search",
            DIVIDER,
        ]
    )
    logger.info("\n%s", block)

import asyncio
import logging
import socket
import urllib.error
import urllib.request

from src.config.config import PROVIDER_CONFIGS, settings

logger = logging.getLogger("uvicorn")

# ASCII banner art has fixed glyph width; wrapping or splitting would corrupt
# the figlet rendering. E501 silenced on the banner lines only.
BANNER = (
    " █████╗ ███████╗ ██████╗███████╗███╗   ██╗██████╗     ███╗   ███╗███████╗███╗   ███╗ ██████╗ ██████╗ ██╗   ██╗\n"  # noqa: E501
    "██╔══██╗██╔════╝██╔════╝██╔════╝████╗  ██║██╔══██╗    ████╗ ████║██╔════╝████╗ ████║██╔═══██╗██╔══██╗╚██╗ ██╔╝\n"  # noqa: E501
    "███████║███████╗██║     █████╗  ██╔██╗ ██║██║  ██║    ██╔████╔██║█████╗  ██╔████╔██║██║   ██║██████╔╝ ╚████╔╝ \n"  # noqa: E501
    "██╔══██║╚════██║██║     ██╔══╝  ██║╚██╗██║██║  ██║    ██║╚██╔╝██║██╔══╝  ██║╚██╔╝██║██║   ██║██╔══██╗  ╚██╔╝  \n"  # noqa: E501
    "██║  ██║███████║╚██████╗███████╗██║ ╚████║██████╔╝    ██║ ╚═╝ ██║███████╗██║ ╚═╝ ██║╚██████╔╝██║  ██║   ██║   \n"  # noqa: E501
    "╚═╝  ╚═╝╚══════╝ ╚═════╝╚══════╝╚═╝  ╚═══╝╚═════╝     ╚═╝     ╚═╝╚══════╝╚═╝     ╚═╝ ╚═════╝ ╚═╝  ╚═╝   ╚═╝   "  # noqa: E501
)

DIVIDER = "-" * 58
PROBE_TIMEOUT_SECONDS = 2.0
APP_NAME = "ascend-memory"


def _resolve_host() -> str:
    try:
        return socket.gethostname()
    except OSError:
        return "localhost"


_ALLOWED_PROBE_SCHEMES = ("http://", "https://")


def _probe_http_sync(url: str) -> str:
    # urlopen accepts file:// and other schemes by default; restrict to http(s)
    # so a misconfigured QDRANT_HOST cannot turn the startup probe into an
    # accidental local-file read.
    if not url.startswith(_ALLOWED_PROBE_SCHEMES):
        return f"{url} [FAILED (unsupported scheme)]"
    try:
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


def _describe_default_embedding() -> str:
    provider = settings.MEM0_DEFAULT_PROVIDER
    config = PROVIDER_CONFIGS.get(provider)
    if config is None:
        return f"{provider} [Warning (provider not in PROVIDER_CONFIGS)]"
    base_url = getattr(settings, config["base_url_setting"], "unknown")
    api_key = getattr(settings, config["api_key_setting"], "")
    key_state = "[Configured]" if api_key else "[Not configured]"
    model = config["embedding_model"]
    dims = config["embedding_dims"]

    return f"{base_url} ({provider}, model={model}, dims={dims}) {key_state}"


async def log_startup_banner() -> None:
    host = _resolve_host()
    port = settings.API_PORT
    local_url = f"http://localhost:{port}"
    hostname_url = f"http://{host}:{port}"

    qdrant_url = f"http://{settings.QDRANT_HOST}:{settings.QDRANT_PORT}/"
    qdrant_status = await asyncio.to_thread(_probe_http_sync, qdrant_url)

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
        f"      Qdrant:    {qdrant_status}",
        f"      Embedding: {_describe_default_embedding()}",
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
        f"      Insert:    POST   {local_url}/api/v1/memory/insert",
        f"      Search:    GET    {local_url}/api/v1/memory/search",
        f"      Delete:    DELETE {local_url}/api/v1/memory",
        f"      Wipe:      POST   {local_url}/api/v1/memory/wipe",
        DIVIDER,
    ])
    logger.info("\n%s", block)

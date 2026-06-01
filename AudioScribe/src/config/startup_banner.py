import asyncio
import logging
import socket
import urllib.error
import urllib.request

from src.config.config import settings

logger = logging.getLogger("AudioScribe")

# ASCII banner art has fixed glyph width; wrapping or splitting would corrupt
# the figlet rendering. E501 silenced on the banner lines only.
BANNER = (
    " █████╗ ██╗   ██╗██████╗ ██╗ ██████╗     ███████╗ ██████╗██████╗ ██╗██████╗ ███████╗\n"
    "██╔══██╗██║   ██║██╔══██╗██║██╔═══██╗    ██╔════╝██╔════╝██╔══██╗██║██╔══██╗██╔════╝\n"
    "███████║██║   ██║██║  ██║██║██║   ██║    ███████╗██║     ██████╔╝██║██████╔╝█████╗  \n"
    "██╔══██║██║   ██║██║  ██║██║██║   ██║    ╚════██║██║     ██╔══██╗██║██╔══██╗██╔══╝  \n"
    "██║  ██║╚██████╔╝██████╔╝██║╚██████╔╝    ███████║╚██████╗██║  ██║██║██████╔╝███████╗\n"
    "╚═╝  ╚═╝ ╚═════╝ ╚═════╝ ╚═╝ ╚═════╝     ╚══════╝ ╚═════╝╚═╝  ╚═╝╚═╝╚═════╝ ╚══════╝"
)

DIVIDER = "-" * 58
PROBE_TIMEOUT_SECONDS = 2.0
APP_NAME = "audio-scribe"

_ALLOWED_PROBE_SCHEMES = ("http://", "https://")


def _resolve_host() -> str:
    try:
        return socket.gethostname()
    except OSError:
        return "localhost"


def _key_state(key: str | None) -> str:
    return "[Configured]" if key else "[Not configured]"


def _probe_http_sync(url: str) -> str:
    # urlopen accepts file:// and other schemes by default; restrict to http(s)
    # so a misconfigured upstream URL cannot turn the startup probe into a
    # local-file read or arbitrary scheme handler.
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


async def log_startup_banner() -> None:
    host = _resolve_host()
    port = settings.MCP_PORT
    local_url = f"http://localhost:{port}"
    hostname_url = f"http://{host}:{port}"

    openai_state = _key_state(settings.OPENAI_API_KEY)
    hf_state = _key_state(settings.HF_TOKEN)

    openai_probe = await asyncio.to_thread(_probe_http_sync, "https://api.openai.com/v1/models")
    hf_probe = await asyncio.to_thread(_probe_http_sync, "https://huggingface.co")

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
        f"      OpenAI:    {openai_probe} {openai_state}",
        f"      HF API:    {hf_probe} {hf_state}",
        "",
        "    Actuator:",
        f"      Health:    {local_url}/health",
        f"      Ready:     {local_url}/ready",
        f"      Metrics:   {local_url}/metrics",
        "",
        "    API documentation:",
        f"      OpenAPI:   {local_url}/openapi.json",
        f"      Swagger:   {local_url}/docs",
        f"      Redoc:     {local_url}/redoc",
        "",
        "    Observability:",
        "      Logging:   [AudioScribe]-tagged formatter with X-Request-ID correlation",
        "",
        "    MCP endpoint:",
        f"      HTTP:      POST {local_url}/mcp",
        "",
        "    REST endpoints:",
        f"      Local:     POST {local_url}/api/v1/transcribe/local",
        f"      OpenAI:    POST {local_url}/api/v1/transcribe/openai",
        f"      HF:        POST {local_url}/api/v1/transcribe/hf",
        f"      Audacity:  POST {local_url}/api/v1/transcribe/audacity",
        DIVIDER,
    ])
    logger.info("\n%s", block)

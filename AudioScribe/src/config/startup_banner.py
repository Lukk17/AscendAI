import asyncio
import logging
import socket
import urllib.error
import urllib.request
from typing import Optional

from src.config.config import settings

logger = logging.getLogger("AudioScribe")

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


def _resolve_host() -> str:
    try:
        return socket.gethostname()
    except OSError:
        return "localhost"


def _key_state(key: Optional[str]) -> str:
    return "[Configured]" if key else "[Not configured]"


async def log_startup_banner() -> None:
    host = _resolve_host()
    port = settings.MCP_PORT
    local_url = f"http://localhost:{port}"
    hostname_url = f"http://{host}:{port}"

    openai_state = _key_state(settings.OPENAI_API_KEY)
    hf_state = _key_state(settings.HF_TOKEN)

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
        "    Profile(s): default",
        "",
        "    External services:",
        f"      OpenAI:    https://api.openai.com {openai_state}",
        f"      HF API:    https://api-inference.huggingface.co {hf_state}",
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
        "      Logging:   [AudioScribe]-tagged formatter (src.config.logging_config)",
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
    await asyncio.sleep(0)

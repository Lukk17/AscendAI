import logging
import socket
import urllib.error
import urllib.request
from urllib.parse import urlparse

from ascend_python_common.startup_banner import (
    CONNECTED,
    FAILED,
    BannerCheck,
    BannerLine,
    BannerSection,
    build_banner,
    warning,
)

from src.config.blocklist_loader import blocklist_loader
from src.config.config import settings

logger = logging.getLogger(__name__)

BANNER = (
    " █████╗ ███████╗ ██████╗███████╗███╗   ██╗██████╗ ██╗  ██╗██╗   ██╗███╗   ██╗████████╗███████╗██████╗ \n"
    "██╔══██╗██╔════╝██╔════╝██╔════╝████╗  ██║██╔══██╗██║  ██║██║   ██║████╗  ██║╚══██╔══╝██╔════╝██╔══██╗\n"
    "███████║███████╗██║     █████╗  ██╔██╗ ██║██║  ██║███████║██║   ██║██╔██╗ ██║   ██║   █████╗  ██████╔╝\n"
    "██╔══██║╚════██║██║     ██╔══╝  ██║╚██╗██║██║  ██║██╔══██║██║   ██║██║╚██╗██║   ██║   ██╔══╝  ██╔══██╗\n"
    "██║  ██║███████║╚██████╗███████╗██║ ╚████║██████╔╝██║  ██║╚██████╔╝██║ ╚████║   ██║   ███████╗██║  ██║\n"
    "╚═╝  ╚═╝╚══════╝ ╚═════╝╚══════╝╚═╝  ╚═══╝╚═════╝ ╚═╝  ╚═╝ ╚═════╝ ╚═╝  ╚═══╝   ╚═╝   ╚══════╝╚═╝  ╚═╝"
)

APP_NAME = "ascend-web-hunter"

_ALLOWED_PROBE_SCHEMES = ("http://", "https://")


def _probe_url_sync(label: str, url: str) -> BannerCheck:
    if not url.startswith(_ALLOWED_PROBE_SCHEMES):
        return BannerCheck(label=label, target=url, status=FAILED)
    try:
        with urllib.request.urlopen(url, timeout=settings.STARTUP_PROBE_TIMEOUT_SECONDS) as response:  # noqa: S310
            status = response.status
        if 200 <= status < 300:
            return BannerCheck(label=label, target=url, status=CONNECTED)
        return BannerCheck(label=label, target=url, status=warning(f"status={status}"))
    except urllib.error.HTTPError as exc:
        return BannerCheck(label=label, target=url, status=warning(f"status={exc.code}"))
    except Exception as exc:
        logger.debug("Probe failed for %s: %s", url, exc)
        return BannerCheck(label=label, target=url, status=FAILED)


def _searxng_check_sync() -> BannerCheck:
    return _probe_url_sync("SearXNG", settings.SEARXNG_BASE_URL.rstrip("/") + "/healthz")


def _flaresolverr_check_sync() -> BannerCheck:
    return _probe_url_sync("FlareSolverr", settings.FLARESOLVERR_URL.rsplit("/v1", 1)[0])


def _redis_check_sync() -> BannerCheck:
    parsed = urlparse(settings.REDIS_URL)
    host = parsed.hostname or "localhost"
    port = parsed.port or 6379
    try:
        with socket.create_connection((host, port), timeout=settings.STARTUP_PROBE_TIMEOUT_SECONDS):
            return BannerCheck(label="Redis", target=settings.REDIS_URL, status=CONNECTED)
    except Exception as exc:
        logger.debug("TCP probe failed for %s: %s", settings.REDIS_URL, exc)
        return BannerCheck(label="Redis", target=settings.REDIS_URL, status=FAILED)


def _blocklist_entry() -> BannerLine:
    state = blocklist_loader.state
    if state is None:
        return BannerLine(label="Blocklist", value=f"{blocklist_loader.blocklist_path} [not loaded]")
    return BannerLine(
        label="Blocklist",
        value=f"{blocklist_loader.blocklist_path} ({state.rule_count} rules)",
    )


def service_banner_sections() -> list[BannerSection]:
    local_url = f"http://localhost:{settings.API_PORT}"
    return [
        BannerSection(
            title="External services",
            entries=(
                _searxng_check_sync(),
                _flaresolverr_check_sync(),
                _redis_check_sync(),
                _blocklist_entry(),
            ),
        ),
        BannerSection(
            title="REST endpoints",
            entries=(
                BannerLine(label="Search v1", value=f"GET {local_url}/v1/search"),
                BannerLine(label="Read v1", value=f"GET {local_url}/v1/read"),
                BannerLine(label="Search v2", value=f"POST {local_url}/v2/search"),
            ),
        ),
        BannerSection(
            title="API documentation",
            entries=(
                BannerLine(label="OpenAPI", value=f"{local_url}/openapi.json"),
                BannerLine(label="Swagger", value=f"{local_url}/docs"),
                BannerLine(label="Redoc", value=f"{local_url}/redoc"),
            ),
        ),
    ]


def build_service_banner() -> list[str]:
    return build_banner(
        service_name=APP_NAME,
        api_port=settings.API_PORT,
        log_level=settings.LOG_LEVEL,
        art=BANNER,
        sections=service_banner_sections(),
    )

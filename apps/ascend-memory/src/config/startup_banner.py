import logging
import urllib.error
import urllib.request

from ascend_python_common.startup_banner import (
    CONFIGURED,
    CONNECTED,
    FAILED,
    NOT_CONFIGURED,
    BannerCheck,
    BannerLine,
    BannerSection,
    build_banner,
    warning,
)

from src.config.config import PROVIDER_CONFIGS, settings

logger = logging.getLogger(__name__)

BANNER = (
    " █████╗ ███████╗ ██████╗███████╗███╗   ██╗██████╗     ███╗   ███╗███████╗███╗   ███╗ ██████╗ ██████╗ ██╗   ██╗\n"  # noqa: E501
    "██╔══██╗██╔════╝██╔════╝██╔════╝████╗  ██║██╔══██╗    ████╗ ████║██╔════╝████╗ ████║██╔═══██╗██╔══██╗╚██╗ ██╔╝\n"  # noqa: E501
    "███████║███████╗██║     █████╗  ██╔██╗ ██║██║  ██║    ██╔████╔██║█████╗  ██╔████╔██║██║   ██║██████╔╝ ╚████╔╝ \n"  # noqa: E501
    "██╔══██║╚════██║██║     ██╔══╝  ██║╚██╗██║██║  ██║    ██║╚██╔╝██║██╔══╝  ██║╚██╔╝██║██║   ██║██╔══██╗  ╚██╔╝  \n"  # noqa: E501
    "██║  ██║███████║╚██████╗███████╗██║ ╚████║██████╔╝    ██║ ╚═╝ ██║███████╗██║ ╚═╝ ██║╚██████╔╝██║  ██║   ██║   \n"  # noqa: E501
    "╚═╝  ╚═╝╚══════╝ ╚═════╝╚══════╝╚═╝  ╚═══╝╚═════╝     ╚═╝     ╚═╝╚══════╝╚═╝     ╚═╝ ╚═════╝ ╚═╝  ╚═╝   ╚═╝   "  # noqa: E501
)

APP_NAME = "ascend-memory"

_ALLOWED_PROBE_SCHEMES = ("http://", "https://")


def _probe_qdrant_sync() -> BannerCheck:
    target = f"http://{settings.QDRANT_HOST}:{settings.QDRANT_PORT}/"
    if not target.startswith(_ALLOWED_PROBE_SCHEMES):
        return BannerCheck(label="Qdrant", target=target, status=FAILED)
    try:
        with urllib.request.urlopen(target, timeout=settings.STARTUP_PROBE_TIMEOUT_SECONDS) as response:  # noqa: S310
            status = response.status
        if 200 <= status < 300:
            return BannerCheck(label="Qdrant", target=target, status=CONNECTED)
        return BannerCheck(label="Qdrant", target=target, status=warning(f"status={status}"))
    except urllib.error.HTTPError as exc:
        return BannerCheck(label="Qdrant", target=target, status=warning(f"status={exc.code}"))
    except Exception as exc:
        logger.debug("Probe failed for %s: %s", target, exc)
        return BannerCheck(label="Qdrant", target=target, status=FAILED)


def _embedding_banner_entry() -> BannerLine | BannerCheck:
    provider = settings.MEM0_DEFAULT_PROVIDER
    config = PROVIDER_CONFIGS.get(provider)
    if config is None:
        return BannerCheck(label="Embedding", target=provider, status=warning("unknown provider"))
    base_url = str(getattr(settings, config["base_url_setting"], "unknown"))
    api_key = str(getattr(settings, config["api_key_setting"], ""))
    key_state = CONFIGURED if api_key else NOT_CONFIGURED
    model = config["embedding_model"]
    dims = config["embedding_dims"]
    return BannerLine(
        label="Embedding",
        value=f"{base_url} ({provider}, model={model}, dims={dims}) [{key_state}]",
    )


def service_banner_sections() -> list[BannerSection]:
    local_url = f"http://localhost:{settings.API_PORT}"
    return [
        BannerSection(
            title="External services",
            entries=(
                _probe_qdrant_sync(),
                _embedding_banner_entry(),
            ),
        ),
        BannerSection(
            title="REST endpoints",
            entries=(
                BannerLine(label="Insert", value=f"POST {local_url}/api/v1/memory/insert"),
                BannerLine(label="Search", value=f"GET {local_url}/api/v1/memory/search"),
                BannerLine(label="Delete", value=f"DELETE {local_url}/api/v1/memory"),
                BannerLine(label="Wipe", value=f"POST {local_url}/api/v1/memory/wipe"),
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

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

from src.config.config import settings

logger = logging.getLogger("ascend-audio-scribe")

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

APP_NAME = "ascend-audio-scribe"

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


def _openai_probe_sync() -> BannerCheck:
    return _probe_url_sync("OpenAI", "https://api.openai.com/v1/models")


def _hf_probe_sync() -> BannerCheck:
    return _probe_url_sync("HF API", "https://huggingface.co")


def _openai_key_entry() -> BannerLine:
    state = CONFIGURED if settings.OPENAI_API_KEY else NOT_CONFIGURED
    return BannerLine(label="OpenAI key", value=f"[{state}]")


def _hf_key_entry() -> BannerLine:
    state = CONFIGURED if settings.HF_TOKEN else NOT_CONFIGURED
    return BannerLine(label="HF key", value=f"[{state}]")


def service_banner_sections() -> list[BannerSection]:
    local_url = f"http://localhost:{settings.API_PORT}"
    return [
        BannerSection(
            title="External services",
            entries=(
                _openai_probe_sync(),
                _openai_key_entry(),
                _hf_probe_sync(),
                _hf_key_entry(),
            ),
        ),
        BannerSection(
            title="REST endpoints",
            entries=(
                BannerLine(label="Local", value=f"POST {local_url}/api/v1/transcribe/local"),
                BannerLine(label="OpenAI", value=f"POST {local_url}/api/v1/transcribe/openai"),
                BannerLine(label="HF", value=f"POST {local_url}/api/v1/transcribe/hf"),
                BannerLine(label="Audacity", value=f"POST {local_url}/api/v1/transcribe/audacity"),
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
        BannerSection(
            title="Observability",
            entries=(
                BannerLine(
                    label="Logging",
                    value="[ascend-audio-scribe]-tagged formatter with X-Request-ID correlation",
                ),
                BannerLine(label="Health", value=f"{local_url}/health"),
                BannerLine(label="Ready", value=f"{local_url}/ready"),
                BannerLine(label="Metrics", value=f"{local_url}/metrics"),
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

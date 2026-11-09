import logging
import socket
import urllib.error
import urllib.request
from collections.abc import Sequence
from urllib.parse import urlparse

from ascend_python_common.startup_banner import (
    CONFIGURED,
    CONNECTED,
    FAILED,
    NOT_CONFIGURED,
    BannerCheck,
    BannerLine,
    BannerSection,
    build_banner,
    strip_user_info,
    warning,
)
from fastapi import APIRouter
from fastapi.routing import APIRoute

from src.config.blocklist_loader import blocklist_loader
from src.config.config import settings
from src.crawl import result_store
from src.observability.safe_address import address_without_query

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
_HEALTH_PATH = "/health"
_ROUTE_OFF = "route off"


def _probe_url_sync(label: str, url: str) -> BannerCheck:
    safe_url = strip_user_info(url)
    if not safe_url.startswith(_ALLOWED_PROBE_SCHEMES):
        return BannerCheck(label=label, target=safe_url, status=FAILED)
    try:
        with urllib.request.urlopen(safe_url, timeout=settings.STARTUP_PROBE_TIMEOUT_SECONDS) as response:  # noqa: S310
            status = response.status
        if 200 <= status < 300:
            return BannerCheck(label=label, target=safe_url, status=CONNECTED)
        return BannerCheck(label=label, target=safe_url, status=warning(f"status={status}"))
    except urllib.error.HTTPError as exc:
        return BannerCheck(label=label, target=safe_url, status=warning(f"status={exc.code}"))
    except Exception as exc:
        logger.debug("Probe failed for %s: %s", safe_url, type(exc).__name__)
        return BannerCheck(label=label, target=safe_url, status=FAILED)


def _searxng_check_sync() -> BannerCheck:
    return _probe_url_sync("SearXNG", settings.SEARXNG_BASE_URL.rstrip("/") + "/healthz")


def _document_route_check_sync(label: str, base_url: str) -> BannerCheck:
    if not base_url.strip():
        return BannerCheck(label=label, target=_ROUTE_OFF, status=NOT_CONFIGURED)
    return _probe_url_sync(label, base_url.rstrip("/") + _HEALTH_PATH)


def _document_route_checks_sync() -> tuple[BannerCheck, ...]:
    return (
        _document_route_check_sync("Docling Serve (PDF route)", settings.DOCLING_SERVE_URL),
        _document_route_check_sync("ascend-ocr (image route)", settings.ASCEND_OCR_URL),
        _document_route_check_sync("ascend-audio-scribe (audio route)", settings.AUDIO_SCRIBE_URL),
    )


def _redis_check_sync() -> BannerCheck:
    parsed = urlparse(settings.REDIS_URL)
    host = parsed.hostname or "localhost"
    port = parsed.port or 6379
    target = address_without_query(settings.REDIS_URL)
    try:
        with socket.create_connection((host, port), timeout=settings.STARTUP_PROBE_TIMEOUT_SECONDS):
            return BannerCheck(label="Redis", target=target, status=CONNECTED)
    except Exception as exc:
        logger.debug("TCP probe failed for %s: %s", target, type(exc).__name__)
        return BannerCheck(label="Redis", target=target, status=FAILED)


def _blocklist_entry() -> BannerLine:
    state = blocklist_loader.state
    if state is None:
        return BannerLine(label="Blocklist", value=f"{blocklist_loader.blocklist_path} [not loaded]")
    return BannerLine(
        label="Blocklist",
        value=f"{blocklist_loader.blocklist_path} ({state.rule_count} rules)",
    )


def _crawl_result_expiry_entry() -> BannerCheck:
    target = (
        f"{settings.CRAWL_RESULT_S3_BUCKET}/{result_store.RESULT_KEY_ROOT} "
        f"after {result_store.retention_days()} days"
    )
    outcome = result_store.expiry_rule_status
    if outcome.applied is None:
        status = "not checked yet"
    elif outcome.applied:
        status = CONFIGURED
    else:
        status = warning(f"not set, results do not expire: {outcome.error}")
    return BannerCheck(label="Crawl result expiry", target=target, status=status)


def _rest_endpoint_entries(routers: Sequence[APIRouter], local_url: str) -> tuple[BannerLine, ...]:
    return tuple(
        BannerLine(
            label=route.summary or route.name.replace("_", " ").title(),
            value=f"{','.join(sorted(route.methods or ()))} {local_url}{route.path}",
        )
        for router in routers
        for route in router.routes
        if isinstance(route, APIRoute)
    )


def service_banner_sections(routers: Sequence[APIRouter]) -> list[BannerSection]:
    local_url = f"http://localhost:{settings.API_PORT}"
    return [
        BannerSection(
            title="External services",
            entries=(
                _searxng_check_sync(),
                _redis_check_sync(),
                *_document_route_checks_sync(),
                _crawl_result_expiry_entry(),
                _blocklist_entry(),
                BannerLine(label="NoVNC display", value=settings.NOVNC_DISPLAY_SIZE),
            ),
        ),
        BannerSection(
            title="REST endpoints",
            entries=_rest_endpoint_entries(routers, local_url),
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


def build_service_banner(routers: Sequence[APIRouter]) -> list[str]:
    return build_banner(
        service_name=APP_NAME,
        api_port=settings.API_PORT,
        log_level=settings.LOG_LEVEL,
        art=BANNER,
        sections=service_banner_sections(routers),
    )

import logging
import socket

from src.config.config import settings
from src.config.memory_limits import detect_memory_limit_mib

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
APP_NAME = "ascend-ocr"

# The measured memory model (see ascend-ocr/openspec/changes/stop-ocr-getting-stuck-on-
# large-jobs/design.md, "the measured memory model"): a process holding one warm
# engine plus every other cached language, detection scaled to at most the detector
# bound, everything else scaling with the input's own full resolution, plus one
# page's retained result.
_BASE_PROCESS_AND_ENGINE_MIB: float = 635.0
_PER_CACHED_LANGUAGE_MIB: float = 143.0
_DETECTION_MIB_PER_MEGAPIXEL: float = 4984.0
_OTHER_MIB_PER_MEGAPIXEL: float = 318.0
_PER_PAGE_RETAINED_MIB: float = 11.5


def _estimate_call_peak_mib() -> float:
    """Predict one call's peak resident memory at the worst input this configuration admits."""
    input_megapixels = settings.OCR_MAX_INFERENCE_PIXELS / 1_000_000
    detector_bound = settings.OCR_DETECTOR_MAX_SIDE

    if detector_bound is not None:
        detector_megapixels = min(input_megapixels, (detector_bound * detector_bound) / 1_000_000)
    else:
        detector_megapixels = input_megapixels

    cache_mib = _PER_CACHED_LANGUAGE_MIB * (settings.ENGINE_CACHE_MAX_SIZE - 1)

    return (
        _BASE_PROCESS_AND_ENGINE_MIB
        + cache_mib
        + _DETECTION_MIB_PER_MEGAPIXEL * detector_megapixels
        + _OTHER_MIB_PER_MEGAPIXEL * input_megapixels
        + _PER_PAGE_RETAINED_MIB
    )


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
    call_peak_mib = _estimate_call_peak_mib()
    service_peak_mib = call_peak_mib * settings.OCR_WORKER_COUNT

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
            "      (none, ascend-ocr runs models locally; warm-up handled in lifespan)",
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
            f"      Per-page allowance: {settings.OCR_PAGE_TIMEOUT_SECONDS}s, {settings.OCR_MAX_PAGES} page(s) max",
            f"      Detector max side: {settings.OCR_DETECTOR_MAX_SIDE or '(unbounded)'}",
            f"      Pixel ceiling per inference: {settings.OCR_MAX_INFERENCE_PIXELS}",
            f"      Engine cache cap: {settings.ENGINE_CACHE_MAX_SIZE} languages",
            f"      Worker count: {settings.OCR_WORKER_COUNT}",
            "    Memory ceiling (this configuration):",
            f"      One call: ~{call_peak_mib:.0f} MiB, x{settings.OCR_WORKER_COUNT} worker(s) "
            f"= ~{service_peak_mib:.0f} MiB service peak",
            DIVIDER,
        ]
    )
    logger.info("\n%s", block)
    _warn_if_service_peak_exceeds_container_limit(service_peak_mib)


def _warn_if_service_peak_exceeds_container_limit(service_peak_mib: float) -> None:
    """Warn, never refuse, when the worker count implies more memory than this container's own cgroup ceiling.

    Refusing to start was considered and rejected. The cgroup limit is unreadable
    (`None`) on a bare host process, in this module's own test suite, and on any
    deployment without a memory cgroup, so a hard refusal keyed on it would block
    every one of those outright, not only a genuinely oversized configuration — and a
    wrong refusal is worse than a warning that reaches an operator who can check the
    real constraint. Even a correctly-read limit is not the whole story: the incident
    that produced "Memory model and the single worker" in
    docs/architecture/arc42/07-deployment-view.md was a host-level kill with this
    container's own cgroup ceiling never reached, so refusing on a per-container
    number would not even have caught the failure this check exists to surface. A
    clear warning at the moment the risk becomes knowable is what this container's
    own visibility can honestly support; the decision is the operator's.
    """
    limit_mib = detect_memory_limit_mib()
    if limit_mib is None or service_peak_mib < limit_mib:
        return

    logger.warning(
        "OCR_WORKER_COUNT=%d implies a service memory peak of ~%.0f MiB, which meets or exceeds this "
        "container's own %.0f MiB cgroup limit. One worker at a time is the configuration this service's "
        "memory budget was measured against (see 'Memory model and the single worker' in "
        "docs/architecture/arc42/07-deployment-view.md) — raising the count is a memory decision, not a "
        "throughput one.",
        settings.OCR_WORKER_COUNT,
        service_peak_mib,
        limit_mib,
    )

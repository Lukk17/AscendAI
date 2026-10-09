import logging
from dataclasses import dataclass
from typing import get_args

from ascend_python_common.startup_banner import BannerLine, BannerSection, build_banner

from src.config.config import ModelPair, QualityMode, QualityProfile, settings
from src.config.memory_limits import detect_memory_limit_mib
from src.service.result_store import result_store

logger = logging.getLogger("uvicorn")

BANNER = (
    "██████╗  █████╗ ██████╗ ██████╗ ██╗     ███████╗     ██████╗  ██████╗██████╗ \n"
    "██╔══██╗██╔══██╗██╔══██╗██╔══██╗██║     ██╔════╝    ██╔═══██╗██╔════╝██╔══██╗\n"
    "██████╔╝███████║██║  ██║██║  ██║██║     █████╗      ██║   ██║██║     ██████╔╝\n"
    "██╔═══╝ ██╔══██║██║  ██║██║  ██║██║     ██╔══╝      ██║   ██║██║     ██╔══██╗\n"
    "██║     ██║  ██║██████╔╝██████╔╝███████╗███████╗    ╚██████╔╝╚██████╗██║  ██║\n"
    "╚═╝     ╚═╝  ╚═╝╚═════╝ ╚═════╝ ╚══════╝╚══════╝     ╚═════╝  ╚═════╝╚═╝  ╚═╝"
)

APP_NAME = "ascend-ocr"

_PIXELS_PER_MEGAPIXEL: float = 1_000_000

# The fitted memory model, fitted on PP-OCRv5_server_det under PaddleOCR 3.6.0. It runs 22 to
# 41 percent above the container measurement of that detector and far above the small pair,
# so it is kept only as an upper-bound price for a pair or an input nobody has measured.
_BASE_PROCESS_AND_ENGINE_MIB: float = 635.0
_DETECTION_MIB_PER_MEGAPIXEL: float = 4984.0
_OTHER_MIB_PER_MEGAPIXEL: float = 318.0
_PER_PAGE_RETAINED_MIB: float = 11.5

# Container cgroup peaks, the worst of three runs each. See "Memory model and the single
# worker" in docs/architecture/arc42/07-deployment-view.md.
MEASUREMENT_PROVENANCE: str = (
    "Measured in a Linux container, 2026-09-25, 4 CPUs, cgroup memory.peak, worst of 3 runs, "
    "image 7b2cb25e7360, PaddleOCR 3.7.0"
)
_A4_PIXELS_AT_300_DPI: int = 2480 * 3508
_A4_DETECTOR_PIXELS_BOUNDED_TO_1536: int = 1086 * 1536
_HIGH_MODE_SQUARE_PIXELS: int = 4200 * 4200
_DETECTOR_PIXELS_BOUNDED_TO_1536: int = 1536 * 1536
_NORMAL_MODE_SQUARE_PIXELS: int = 2100 * 2100
_DETECTOR_PIXELS_BOUNDED_TO_1024: int = 1024 * 1024

# One loaded engine's footprint, less the Python and Paddle runtime every process carries
# anyway, is what a further engine idling in the cache costs.
_LOADED_ENGINE_MIB: float = 333.0
_PYTHON_AND_PADDLE_MIB: float = 124.0
_IDLE_ENGINE_MIB: float = _LOADED_ENGINE_MIB - _PYTHON_AND_PADDLE_MIB
_API_PROCESS_AT_REST_MIB: float = 259.0


@dataclass(frozen=True, slots=True)
class _Measurement:
    input_pixels: int
    detector_pixels: int
    peak_mib: float


@dataclass(frozen=True, slots=True)
class _MeasuredEngine:
    pair: ModelPair
    measurements: tuple[_Measurement, ...]


@dataclass(frozen=True, slots=True)
class _StraightenMeasurement:
    """One 3162 x 4200 photo read in high mode twice, once as it is and once straightened."""

    plain_peak_mib: float
    straightened_peak_mib: float

    @property
    def overhead_mib(self) -> float:
        return self.straightened_peak_mib - self.plain_peak_mib


@dataclass(frozen=True, slots=True)
class _CallPeak:
    mib: float
    is_measured: bool


_MEASURED_ENGINES: tuple[_MeasuredEngine, ...] = (
    _MeasuredEngine(
        pair=ModelPair("PP-OCRv6_small_det", "PP-OCRv6_small_rec"),
        measurements=(
            _Measurement(_NORMAL_MODE_SQUARE_PIXELS, _DETECTOR_PIXELS_BOUNDED_TO_1024, 858.0),
            _Measurement(_A4_PIXELS_AT_300_DPI, _A4_DETECTOR_PIXELS_BOUNDED_TO_1536, 1016.0),
            _Measurement(_HIGH_MODE_SQUARE_PIXELS, _DETECTOR_PIXELS_BOUNDED_TO_1536, 1236.0),
        ),
    ),
)

# Flat, angled, bent, two crumpled and one rotated photo. The unwarping model is the same
# whichever pair reads the page, so its largest measured overhead prices every straightened call.
_STRAIGHTEN_MEASUREMENTS: tuple[_StraightenMeasurement, ...] = (
    _StraightenMeasurement(1161.0, 2651.0),
    _StraightenMeasurement(1125.0, 2682.0),
    _StraightenMeasurement(1097.0, 2666.0),
    _StraightenMeasurement(1125.0, 2655.0),
    _StraightenMeasurement(1137.0, 2735.0),
    _StraightenMeasurement(1148.0, 2771.0),
)
_STRAIGHTEN_OVERHEAD_MIB: float = max(measurement.overhead_mib for measurement in _STRAIGHTEN_MEASUREMENTS)


def _input_megapixels(profile: QualityProfile) -> float:
    return profile.max_inference_pixels / _PIXELS_PER_MEGAPIXEL


def _detector_megapixels(profile: QualityProfile) -> float:
    """The most detection can see at the mode's worst input, which the bound caps by its square."""
    bound_megapixels = profile.detector_max_side * profile.detector_max_side / _PIXELS_PER_MEGAPIXEL

    return min(_input_megapixels(profile), bound_megapixels)


def _fitted_call_peak_mib(profile: QualityProfile) -> float:
    return (
        _BASE_PROCESS_AND_ENGINE_MIB
        + _DETECTION_MIB_PER_MEGAPIXEL * _detector_megapixels(profile)
        + _OTHER_MIB_PER_MEGAPIXEL * _input_megapixels(profile)
        + _PER_PAGE_RETAINED_MIB
    )


def _measured_call_peak_mib(pair: ModelPair, profile: QualityProfile) -> float | None:
    """Price the mode's worst input from this engine's measurements, or None when none covers it.

    A measurement of that exact input is used as is. Otherwise the smallest measurement whose input
    and detection input are both at least as large is used, because peak memory was measured not to
    grow steadily with pixels.
    """
    measurements = [
        measurement
        for engine in _MEASURED_ENGINES
        if engine.pair == pair
        for measurement in engine.measurements
    ]
    input_pixels = profile.max_inference_pixels
    detector_pixels = min(input_pixels, profile.detector_max_side * profile.detector_max_side)

    exact_peaks = [
        measurement.peak_mib
        for measurement in measurements
        if measurement.input_pixels == input_pixels and measurement.detector_pixels == detector_pixels
    ]
    if exact_peaks:
        return max(exact_peaks)

    covering_peaks = [
        measurement.peak_mib
        for measurement in measurements
        if measurement.input_pixels >= input_pixels and measurement.detector_pixels >= detector_pixels
    ]

    return min(covering_peaks, default=None)


def _call_peak(pair: ModelPair, profile: QualityProfile, straighten: bool = False) -> _CallPeak:
    """Predict one call's peak on one engine in one mode, falling back to the fitted model."""
    overhead_mib = _STRAIGHTEN_OVERHEAD_MIB if straighten else 0.0
    measured_peak_mib = _measured_call_peak_mib(pair, profile)
    if measured_peak_mib is None:
        return _CallPeak(_fitted_call_peak_mib(profile) + overhead_mib, is_measured=False)

    return _CallPeak(measured_peak_mib + overhead_mib, is_measured=True)


def _quality_profiles() -> list[QualityProfile]:
    return [settings.quality_profile(mode) for mode in get_args(QualityMode)]


def _worst_call_peak(pair: ModelPair, straighten: bool) -> _CallPeak:
    """The costlier of the engine's quality modes, since a caller may ask for either."""
    return max(
        (_call_peak(pair, profile, straighten) for profile in _quality_profiles()), key=lambda peak: peak.mib
    )


def _reachable_model_pairs() -> list[ModelPair]:
    """Every engine the service can load, the same set the image preloads, in a stable order."""
    return sorted(settings.reachable_model_pairs(), key=str)


def _resident_engine_count(reachable_pairs: list[ModelPair]) -> int:
    return min(settings.ENGINE_CACHE_MAX_SIZE, len(reachable_pairs))


def _estimate_call_peak_mib() -> float:
    """Predict one straightened call's peak on the worst engine that can be resident."""
    reachable_pairs = _reachable_model_pairs()
    idle_engines = _resident_engine_count(reachable_pairs) - 1
    worst_call_mib = max(_worst_call_peak(pair, straighten=True).mib for pair in reachable_pairs)

    return worst_call_mib + _IDLE_ENGINE_MIB * idle_engines


def _result_store_entries() -> list[BannerLine]:
    """Describe the one external service this module has, and never its credentials."""
    reachable = result_store.bucket_reachable
    status = (
        "unknown (not checked yet)" if reachable is None else ("answered" if reachable else "did NOT answer")
    )
    entries = [
        BannerLine("Result store", f"{settings.OCR_RESULT_S3_ENDPOINT} [{status}]"),
        BannerLine("Result bucket", settings.OCR_RESULT_S3_BUCKET),
    ]

    if settings.OCR_RESULT_S3_PUBLIC_ENDPOINT != settings.OCR_RESULT_S3_ENDPOINT:
        entries.append(BannerLine("Result store (public)", settings.OCR_RESULT_S3_PUBLIC_ENDPOINT))

    return entries


def _runtime_entries() -> list[BannerLine]:
    return [
        BannerLine("Language", settings.DEFAULT_LANGUAGE),
        BannerLine("Max upload", f"{settings.MAX_FILE_SIZE_MB} MB"),
        *(
            BannerLine(f"Page allowance, {pair}", f"{settings.page_allowance_seconds(pair):.1f}s")
            for pair in _reachable_model_pairs()
        ),
        BannerLine("Page ceiling", f"{settings.OCR_JOB_MAX_PAGES} page(s) per document"),
        BannerLine("Reading ceiling", f"{settings.OCR_JOB_READING_CEILING_SECONDS}s per document"),
        BannerLine(
            "Queue bounds",
            f"{settings.OCR_JOB_QUEUE_MAX_DOCUMENTS} document(s), {settings.OCR_JOB_QUEUE_MAX_PAGES} page(s)",
        ),
        BannerLine(
            "Result retention",
            f"{settings.OCR_JOB_RETENTION_SECONDS}s, {settings.OCR_JOB_MAX_RETAINED} record(s) max",
        ),
        BannerLine("Jobs directory", settings.OCR_JOBS_DIR),
        *(
            BannerLine(
                f"Quality {mode}",
                f"{profile.render_dpi} dpi, detector max side {profile.detector_max_side}, "
                f"up to {profile.max_inference_pixels} pixels per inference",
            )
            for mode in get_args(QualityMode)
            for profile in (settings.quality_profile(mode),)
        ),
        BannerLine("Engine cache cap", f"{settings.ENGINE_CACHE_MAX_SIZE} engines"),
        BannerLine("Worker count", str(settings.OCR_WORKER_COUNT)),
    ]


def _memory_entries() -> list[BannerLine]:
    reachable_pairs = _reachable_model_pairs()
    worst_peaks = {pair: _worst_call_peak(pair, straighten=False) for pair in reachable_pairs}
    entries = [
        BannerLine(
            str(pair),
            f"~{peak.mib:.0f} MiB, ~{peak.mib + _STRAIGHTEN_OVERHEAD_MIB:.0f} MiB straightened "
            f"({'measured' if peak.is_measured else 'fitted'})",
        )
        for pair, peak in worst_peaks.items()
    ]
    entries.append(
        BannerLine(
            "Resident engines",
            f"up to {_resident_engine_count(reachable_pairs)} of {len(reachable_pairs)} reachable, "
            f"~{_IDLE_ENGINE_MIB:.0f} MiB per idle engine (measured)",
        )
    )
    entries.append(BannerLine("API process at rest", f"~{_API_PROCESS_AT_REST_MIB:.0f} MiB (measured)"))
    if any(peak.is_measured for peak in worst_peaks.values()):
        entries.append(BannerLine("Provenance", MEASUREMENT_PROVENANCE))
    call_peak_mib = _estimate_call_peak_mib()
    service_peak_mib = _API_PROCESS_AT_REST_MIB + call_peak_mib * settings.OCR_WORKER_COUNT
    entries.append(
        BannerLine(
            "One call, straightened",
            f"~{call_peak_mib:.0f} MiB, x{settings.OCR_WORKER_COUNT} worker(s) "
            f"+ ~{_API_PROCESS_AT_REST_MIB:.0f} MiB API process = ~{service_peak_mib:.0f} MiB service peak",
        )
    )

    return entries


def service_banner_sections() -> list[BannerSection]:
    return [
        BannerSection("External services", _result_store_entries()),
        BannerSection("Runtime config", _runtime_entries()),
        BannerSection("Memory ceiling (this configuration)", _memory_entries()),
    ]


def build_service_banner() -> list[str]:
    return build_banner(
        service_name=APP_NAME,
        api_port=settings.API_PORT,
        log_level=settings.LOG_LEVEL,
        art=BANNER,
        sections=service_banner_sections(),
    )


def _service_peak_mib() -> float:
    return _API_PROCESS_AT_REST_MIB + _estimate_call_peak_mib() * settings.OCR_WORKER_COUNT


def log_startup_warnings() -> None:
    _warn_if_result_store_unreachable()
    _warn_if_service_peak_exceeds_container_limit(_service_peak_mib())


def _warn_if_result_store_unreachable() -> None:
    """Warn, never refuse, when the result bucket did not answer at boot.

    The same posture the cgroup check takes below, and for the same reason: the service
    can still accept work, read it and record what happened, because the job record is
    local. What a missing bucket stops is delivery, which is worth an operator's
    attention and is not worth refusing to start over.
    """
    if result_store.bucket_reachable is not False:
        return

    logger.warning(
        "Result store %s did not answer for bucket '%s'. The service will accept and read documents, "
        "and every job will finish with the RESULT_STORE_UNAVAILABLE reason until the store is reachable.",
        settings.OCR_RESULT_S3_ENDPOINT,
        settings.OCR_RESULT_S3_BUCKET,
    )


def _warn_if_service_peak_exceeds_container_limit(service_peak_mib: float) -> None:
    """Warn, never refuse, when the worker count implies more memory than this container's own cgroup ceiling.

    Refusing to start was considered and rejected. The cgroup limit is unreadable
    (`None`) on a bare host process, in this module's own test suite, and on any
    deployment without a memory cgroup, so a hard refusal keyed on it would block
    every one of those outright, not only a genuinely oversized configuration - and a
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
        "docs/architecture/arc42/07-deployment-view.md) - raising the count is a memory decision, not a "
        "throughput one.",
        settings.OCR_WORKER_COUNT,
        service_peak_mib,
        limit_mib,
    )

from unittest.mock import patch

import pytest

from src.config.config import ModelPair, QualityProfile, settings
from src.config.startup_banner import _call_peak, _estimate_call_peak_mib, _resolve_host, log_startup_banner
from src.service.result_store import result_store
from tests.conftest import OFF_FAMILY_PAIR


@pytest.fixture(autouse=True)
def forget_the_bucket_probe():
    """Each case decides for itself what the result store answered at boot."""
    previous = result_store.bucket_reachable
    result_store.bucket_reachable = None

    yield

    result_store.bucket_reachable = previous


class TestResolveHost:
    def test_returns_hostname_on_success(self):
        # Given
        with patch(
            "src.config.startup_banner.socket.gethostname",
            return_value="ocr-host",
        ):
            # When
            host = _resolve_host()

        # Then
        assert host == "ocr-host"

    def test_falls_back_to_localhost_on_os_error(self):
        # Given
        with patch(
            "src.config.startup_banner.socket.gethostname",
            side_effect=OSError("no hostname"),
        ):
            # When
            host = _resolve_host()

        # Then
        assert host == "localhost"


class TestLogStartupBanner:
    def test_emits_log_record(self, caplog):
        # Given
        caplog.set_level("INFO", logger="uvicorn")

        # When
        log_startup_banner()

        # Then
        joined = "\n".join(record.message for record in caplog.records)
        assert "ascend-ocr" in joined
        assert "Access URLs" in joined
        assert "Memory ceiling" in joined

    @pytest.mark.usefixtures("shipped_memory_settings")
    def test_reports_each_engines_allowance_the_page_ceiling_and_the_derived_reading_ceiling(self, caplog, monkeypatch):
        # Given
        monkeypatch.setattr(settings, "OCR_PAGE_ALLOWANCE_HEADROOM", 10.0)
        monkeypatch.setattr(settings, "OCR_JOB_MAX_PAGES", 100)
        caplog.set_level("INFO", logger="uvicorn")

        # When
        log_startup_banner()

        # Then
        joined = "\n".join(record.message for record in caplog.records)
        assert f"Page allowance, {SMALL_PAIR}: 251.0s" in joined
        assert "Page allowance, PP-OCRv5" not in joined
        assert "Per-page allowance:" not in joined
        assert "Page ceiling: 100 page(s) per document" in joined
        assert f"Reading ceiling: {settings.OCR_JOB_READING_CEILING_SECONDS}s per document" in joined
        assert "Queue bounds:" in joined
        assert "Result retention:" in joined

    def test_no_longer_reports_a_request_timeout(self, caplog):
        # Given
        caplog.set_level("INFO", logger="uvicorn")

        # When
        log_startup_banner()

        # Then - the setting is gone, so the line that printed it has to be gone too
        joined = "\n".join(record.message for record in caplog.records)
        assert "OCR timeout" not in joined
        assert "per request" not in joined


class TestResultStoreLine:
    def test_reports_the_endpoint_and_the_bucket(self, caplog, monkeypatch):
        # Given
        monkeypatch.setattr(settings, "OCR_RESULT_S3_ENDPOINT", "http://host.docker.internal:9070")
        monkeypatch.setattr(settings, "OCR_RESULT_S3_PUBLIC_ENDPOINT", "http://host.docker.internal:9070")
        monkeypatch.setattr(settings, "OCR_RESULT_S3_BUCKET", "ocr-results")
        caplog.set_level("INFO", logger="uvicorn")

        # When
        log_startup_banner()

        # Then
        joined = "\n".join(record.message for record in caplog.records)
        assert "Result store: http://host.docker.internal:9070" in joined
        assert "Result bucket: ocr-results" in joined
        assert "Result store (public)" not in joined
        assert "none, ascend-ocr runs models locally" not in joined

    def test_reports_the_public_endpoint_only_when_it_differs(self, caplog, monkeypatch):
        # Given
        monkeypatch.setattr(settings, "OCR_RESULT_S3_ENDPOINT", "http://host.docker.internal:9070")
        monkeypatch.setattr(settings, "OCR_RESULT_S3_PUBLIC_ENDPOINT", "http://localhost:9070")
        caplog.set_level("INFO", logger="uvicorn")

        # When
        log_startup_banner()

        # Then
        joined = "\n".join(record.message for record in caplog.records)
        assert "Result store (public): http://localhost:9070" in joined

    def test_never_prints_the_credentials(self, caplog, monkeypatch):
        # Given
        monkeypatch.setattr(settings, "OCR_RESULT_S3_ACCESS_KEY", "admin-key")
        monkeypatch.setattr(settings, "OCR_RESULT_S3_SECRET_KEY", "super-secret")
        caplog.set_level("INFO", logger="uvicorn")

        # When
        log_startup_banner()

        # Then
        joined = "\n".join(record.message for record in caplog.records)
        assert "admin-key" not in joined
        assert "super-secret" not in joined

    def test_reports_that_the_bucket_answered(self, caplog):
        # Given
        result_store.bucket_reachable = True
        caplog.set_level("INFO", logger="uvicorn")

        # When
        log_startup_banner()

        # Then
        joined = "\n".join(record.message for record in caplog.records)
        assert "[answered]" in joined
        assert not [record for record in caplog.records if record.levelname == "WARNING"]

    def test_an_unreachable_store_is_a_warning_rather_than_a_refusal(self, caplog, monkeypatch):
        # Given
        monkeypatch.setattr("src.config.startup_banner.detect_memory_limit_mib", lambda: None)
        result_store.bucket_reachable = False
        caplog.set_level("INFO", logger="uvicorn")

        # When - no exception: the service still boots
        log_startup_banner()

        # Then
        joined = "\n".join(record.message for record in caplog.records)
        assert "[did NOT answer]" in joined
        warnings = [record for record in caplog.records if record.levelname == "WARNING"]
        assert len(warnings) == 1
        assert "RESULT_STORE_UNAVAILABLE" in warnings[0].message
        assert not [record for record in caplog.records if record.levelname == "ERROR"]

    def test_reports_each_quality_mode_with_its_render_resolution_bound_and_pixel_ceiling(self, caplog, monkeypatch):
        # Given
        monkeypatch.setattr(settings, "OCR_QUALITY_NORMAL", QualityProfile(render_dpi=150, detector_max_side=1024))
        monkeypatch.setattr(settings, "OCR_QUALITY_HIGH", QualityProfile(render_dpi=300, detector_max_side=1536))
        caplog.set_level("INFO", logger="uvicorn")

        # When
        log_startup_banner()

        # Then
        joined = "\n".join(record.message for record in caplog.records)
        assert "Quality normal: 150 dpi, detector max side 1024, up to 4410000 pixels per inference" in joined
        assert "Quality high: 300 dpi, detector max side 1536, up to 17640000 pixels per inference" in joined
        assert "Detector max side:" not in joined
        assert "Pixel ceiling per inference:" not in joined


SMALL_PAIR = ModelPair("PP-OCRv6_small_det", "PP-OCRv6_small_rec")
UNMEASURED_PAIR = ModelPair("PP-OCRv6_medium_det", "PP-OCRv6_medium_rec")
SHIPPED_LANGUAGES = ("en", "pl", "de", "fr", "es", "it", "pt", "nl", "ch", "japan")
SHIPPED_NORMAL = QualityProfile(render_dpi=150, detector_max_side=1024)
SHIPPED_HIGH = QualityProfile(render_dpi=300, detector_max_side=1536)
BETWEEN_THE_MEASURED_MODES = QualityProfile(render_dpi=120, detector_max_side=1024)
BETWEEN_NORMAL_AND_A4 = QualityProfile(render_dpi=200, detector_max_side=1024)
DETECTION_PAST_THE_HIGH_MEASUREMENT = QualityProfile(render_dpi=200, detector_max_side=2000)
PAST_EVERY_MEASURED_INPUT = QualityProfile(render_dpi=400, detector_max_side=1700)
STRAIGHTEN_OVERHEAD_MIB = 2771.0 - 1148.0
IDLE_ENGINE_MIB = 333.0 - 124.0
API_PROCESS_MIB = 259.0
CONTAINER_LIMIT_MIB = 4 * 1024


def fitted_peak_mib(profile: QualityProfile) -> float:
    """The fitted model, restated here so a test fails if the code's own constants drift."""
    input_megapixels = profile.max_inference_pixels / 1_000_000
    detector_megapixels = min(input_megapixels, profile.detector_max_side**2 / 1_000_000)

    return 635.0 + 4984.0 * detector_megapixels + 318.0 * input_megapixels + 11.5


@pytest.fixture
def shipped_memory_settings(monkeypatch):
    """Pin every input of the estimate to the shipped defaults, whatever the environment says."""
    monkeypatch.setattr(settings, "OCR_TEXT_DETECTION_MODEL", SMALL_PAIR.detection)
    monkeypatch.setattr(settings, "OCR_TEXT_RECOGNITION_MODEL", SMALL_PAIR.recognition)
    monkeypatch.setattr(settings, "OCR_QUALITY_NORMAL", SHIPPED_NORMAL)
    monkeypatch.setattr(settings, "OCR_QUALITY_HIGH", SHIPPED_HIGH)
    monkeypatch.setattr(settings, "ENGINE_CACHE_MAX_SIZE", 2)
    monkeypatch.setattr(settings, "OCR_WORKER_COUNT", 1)
    monkeypatch.setattr(settings, "SUPPORTED_LANGUAGES", SHIPPED_LANGUAGES)


@pytest.fixture
def two_reachable_engines(shipped_memory_settings: None, off_family_language: str) -> None:
    """The shipped settings with one language opted back in on a pair nobody measured for memory."""
    _ = shipped_memory_settings, off_family_language


class TestCallPeakPerModelPair:
    @pytest.mark.parametrize(
        ("profile", "expected_mib"),
        [(SHIPPED_NORMAL, 858.0), (SHIPPED_HIGH, 1236.0)],
    )
    def test_a_mode_whose_exact_worst_input_was_measured_is_priced_by_that_measurement(self, profile, expected_mib):
        # When
        peak = _call_peak(SMALL_PAIR, profile)

        # Then
        assert peak.mib == pytest.approx(expected_mib)
        assert peak.is_measured is True

    @pytest.mark.parametrize(
        ("profile", "expected_mib"),
        [(BETWEEN_THE_MEASURED_MODES, 858.0), (BETWEEN_NORMAL_AND_A4, 1016.0)],
    )
    def test_a_mode_with_no_exact_measurement_is_priced_by_the_smallest_measurement_covering_it(
        self, profile, expected_mib
    ):
        # When
        peak = _call_peak(SMALL_PAIR, profile)

        # Then
        assert peak.mib == pytest.approx(expected_mib)
        assert peak.is_measured is True

    @pytest.mark.parametrize("profile", [DETECTION_PAST_THE_HIGH_MEASUREMENT, PAST_EVERY_MEASURED_INPUT])
    def test_a_mode_past_every_measured_input_falls_back_to_the_fitted_model(self, profile):
        # When
        peak = _call_peak(SMALL_PAIR, profile)

        # Then
        assert peak.mib == pytest.approx(fitted_peak_mib(profile))
        assert peak.is_measured is False

    @pytest.mark.parametrize(
        "pair", [UNMEASURED_PAIR, ModelPair("PP-OCRv6_small_det", "latin_PP-OCRv5_mobile_rec"), OFF_FAMILY_PAIR]
    )
    def test_an_unmeasured_pair_is_priced_by_the_fitted_model(self, pair):
        # When
        peak = _call_peak(pair, SHIPPED_HIGH)

        # Then
        assert peak.mib == pytest.approx(fitted_peak_mib(SHIPPED_HIGH))
        assert peak.is_measured is False

    @pytest.mark.parametrize(
        ("profile", "expected_mib"),
        [(SHIPPED_NORMAL, 858.0 + STRAIGHTEN_OVERHEAD_MIB), (SHIPPED_HIGH, 1236.0 + STRAIGHTEN_OVERHEAD_MIB)],
    )
    def test_a_straightened_call_adds_the_largest_straighten_overhead_measured_on_one_photo(
        self, profile, expected_mib
    ):
        # When
        peak = _call_peak(SMALL_PAIR, profile, straighten=True)

        # Then: 2771 MiB straightened against 1148 MiB plain on the rotated photo
        assert peak.mib == pytest.approx(expected_mib)
        assert peak.is_measured is True

    def test_a_straightened_call_on_an_unmeasured_pair_stays_labelled_fitted(self):
        # When
        peak = _call_peak(UNMEASURED_PAIR, SHIPPED_HIGH, straighten=True)

        # Then
        assert peak.mib == pytest.approx(fitted_peak_mib(SHIPPED_HIGH) + STRAIGHTEN_OVERHEAD_MIB)
        assert peak.is_measured is False

    def test_the_fitted_model_charges_detection_only_up_to_the_detector_bound(self):
        # Given: the same input, once with detection seeing all of it and once bounded below it
        whole_page = QualityProfile(render_dpi=400, detector_max_side=5600)

        # When
        unbounded_peak = _call_peak(UNMEASURED_PAIR, whole_page).mib
        bounded_peak = _call_peak(UNMEASURED_PAIR, PAST_EVERY_MEASURED_INPUT).mib

        # Then
        assert bounded_peak < unbounded_peak


@pytest.mark.usefixtures("shipped_memory_settings")
class TestEstimateAcrossResidentEngines:
    def test_shipped_defaults_cost_a_straightened_page_in_high_mode_with_no_idle_engine(self):
        # When: one reachable pair, so the cache's second slot never fills
        estimate = _estimate_call_peak_mib()

        # Then
        assert estimate == pytest.approx(1236.0 + STRAIGHTEN_OVERHEAD_MIB)

    def test_the_mode_that_costs_more_decides_the_estimate(self, monkeypatch):
        # Given: normal mode now lets detection see more than any measurement covers
        monkeypatch.setattr(settings, "OCR_QUALITY_NORMAL", DETECTION_PAST_THE_HIGH_MEASUREMENT)

        # When
        estimate = _estimate_call_peak_mib()

        # Then
        assert estimate == pytest.approx(fitted_peak_mib(DETECTION_PAST_THE_HIGH_MEASUREMENT) + STRAIGHTEN_OVERHEAD_MIB)

    @pytest.mark.usefixtures("two_reachable_engines")
    def test_a_second_reachable_engine_is_priced_as_one_idle_engine(self):
        # When
        estimate = _estimate_call_peak_mib()

        # Then: the worst engine reads, the other sits in the cache
        assert estimate == pytest.approx(fitted_peak_mib(SHIPPED_HIGH) + STRAIGHTEN_OVERHEAD_MIB + IDLE_ENGINE_MIB)

    @pytest.mark.usefixtures("two_reachable_engines")
    def test_a_cache_of_one_holds_no_idle_engine(self, monkeypatch):
        # Given
        monkeypatch.setattr(settings, "ENGINE_CACHE_MAX_SIZE", 1)

        # When
        estimate = _estimate_call_peak_mib()

        # Then
        assert estimate == pytest.approx(fitted_peak_mib(SHIPPED_HIGH) + STRAIGHTEN_OVERHEAD_MIB)

    @pytest.mark.usefixtures("two_reachable_engines")
    def test_a_cache_larger_than_the_reachable_pairs_counts_only_the_pairs_that_exist(self, monkeypatch):
        # Given: two reachable pairs, so a cap of five can never fill
        monkeypatch.setattr(settings, "ENGINE_CACHE_MAX_SIZE", 5)

        # When
        estimate = _estimate_call_peak_mib()

        # Then
        assert estimate == pytest.approx(fitted_peak_mib(SHIPPED_HIGH) + STRAIGHTEN_OVERHEAD_MIB + IDLE_ENGINE_MIB)

    def test_an_empty_allowlist_still_prices_the_default_languages_engine(self, monkeypatch):
        # Given: an operator can set SUPPORTED_LANGUAGES to nothing, and the default language is still warmed
        monkeypatch.setattr(settings, "SUPPORTED_LANGUAGES", ())

        # When
        estimate = _estimate_call_peak_mib()

        # Then
        assert estimate == pytest.approx(1236.0 + STRAIGHTEN_OVERHEAD_MIB)

    @pytest.mark.usefixtures("off_family_language")
    def test_the_default_languages_own_engine_is_priced_beside_the_supported_ones(self, monkeypatch):
        # Given: the default language reads on a pair no supported language loads
        monkeypatch.setattr(settings, "SUPPORTED_LANGUAGES", SHIPPED_LANGUAGES)
        monkeypatch.setattr(settings, "DEFAULT_LANGUAGE", "ru")

        # When
        estimate = _estimate_call_peak_mib()

        # Then: the engine settings.reachable_model_pairs() names, the same set the image preloads
        assert estimate == pytest.approx(fitted_peak_mib(SHIPPED_HIGH) + STRAIGHTEN_OVERHEAD_MIB + IDLE_ENGINE_MIB)

    def test_the_banner_prices_the_plain_and_the_straightened_call_the_idle_engine_and_the_api_process(self, caplog):
        # Given
        caplog.set_level("INFO", logger="uvicorn")

        # When
        log_startup_banner()

        # Then
        joined = "\n".join(record.message for record in caplog.records)
        assert "PP-OCRv6_small_det/PP-OCRv6_small_rec: ~1236 MiB, ~2859 MiB straightened (measured)" in joined
        assert "Resident engines: up to 1 of 1 reachable, ~209 MiB per idle engine (measured)" in joined
        assert "API process at rest: ~259 MiB (measured)" in joined
        assert "One call, straightened: ~2859 MiB, x1 worker(s) + ~259 MiB API process = ~3118 MiB service peak" in (
            joined
        )
        assert "PP-OCRv5" not in joined

    def test_the_banner_states_where_the_measured_figures_come_from(self, caplog):
        # Given
        caplog.set_level("INFO", logger="uvicorn")

        # When
        log_startup_banner()

        # Then
        joined = "\n".join(record.message for record in caplog.records)
        assert (
            "Measured in a Linux container, 2026-09-25, 4 CPUs, cgroup memory.peak, worst of 3 runs, "
            "image 7b2cb25e7360, PaddleOCR 3.7.0" in joined
        )

    def test_banner_labels_every_pair_fitted_once_no_measurement_covers_either_mode(self, caplog, monkeypatch):
        # Given
        monkeypatch.setattr(settings, "OCR_QUALITY_NORMAL", PAST_EVERY_MEASURED_INPUT)
        monkeypatch.setattr(settings, "OCR_QUALITY_HIGH", PAST_EVERY_MEASURED_INPUT)
        caplog.set_level("INFO", logger="uvicorn")

        # When
        log_startup_banner()

        # Then
        joined = "\n".join(record.message for record in caplog.records)
        fitted = fitted_peak_mib(PAST_EVERY_MEASURED_INPUT)
        straightened = fitted + STRAIGHTEN_OVERHEAD_MIB
        assert f"{SMALL_PAIR}: ~{fitted:.0f} MiB, ~{straightened:.0f} MiB straightened (fitted)" in joined
        assert f"{SMALL_PAIR}: ~1236 MiB" not in joined
        assert "Measured in a Linux container" not in joined

    def test_a_pair_is_labelled_fitted_when_its_costlier_mode_is_fitted(self, caplog, monkeypatch):
        # Given: normal is measured, high is past every measurement
        monkeypatch.setattr(settings, "OCR_QUALITY_HIGH", PAST_EVERY_MEASURED_INPUT)
        caplog.set_level("INFO", logger="uvicorn")

        # When
        log_startup_banner()

        # Then
        joined = "\n".join(record.message for record in caplog.records)
        assert f"{SMALL_PAIR}: ~{fitted_peak_mib(PAST_EVERY_MEASURED_INPUT):.0f} MiB" in joined
        assert "straightened (fitted)" in joined

    def test_shipped_defaults_do_not_warn_against_the_4_gib_container(self, caplog, monkeypatch):
        # Given
        monkeypatch.setattr("src.config.startup_banner.detect_memory_limit_mib", lambda: CONTAINER_LIMIT_MIB)
        caplog.set_level("WARNING", logger="uvicorn")

        # When
        log_startup_banner()

        # Then
        assert not any(record.levelname == "WARNING" for record in caplog.records)


class TestWarnIfServicePeakExceedsContainerLimit:
    def test_no_warning_when_limit_unreadable(self, caplog, monkeypatch):
        # Given
        monkeypatch.setattr("src.config.startup_banner.detect_memory_limit_mib", lambda: None)
        caplog.set_level("WARNING", logger="uvicorn")

        # When
        log_startup_banner()

        # Then
        assert not any(record.levelname == "WARNING" for record in caplog.records)

    def test_no_warning_when_service_peak_fits(self, caplog, monkeypatch):
        # Given: a limit comfortably above whatever one worker and the API process are estimated to cost
        monkeypatch.setattr(settings, "OCR_WORKER_COUNT", 1)
        monkeypatch.setattr(
            "src.config.startup_banner.detect_memory_limit_mib",
            lambda: (_estimate_call_peak_mib() + API_PROCESS_MIB) * 10,
        )
        caplog.set_level("WARNING", logger="uvicorn")

        # When
        log_startup_banner()

        # Then
        assert not any(record.levelname == "WARNING" for record in caplog.records)

    def test_the_api_process_counts_toward_the_service_peak(self, caplog, monkeypatch):
        # Given: a limit the worker alone fits under, and the worker plus the API process does not
        monkeypatch.setattr(settings, "OCR_WORKER_COUNT", 1)
        one_call_peak = _estimate_call_peak_mib()
        monkeypatch.setattr(
            "src.config.startup_banner.detect_memory_limit_mib",
            lambda: one_call_peak + API_PROCESS_MIB / 2,
        )
        caplog.set_level("WARNING", logger="uvicorn")

        # When
        log_startup_banner()

        # Then
        warnings = [record for record in caplog.records if record.levelname == "WARNING"]
        assert len(warnings) == 1
        assert "OCR_WORKER_COUNT=1" in warnings[0].message

    def test_warns_when_service_peak_meets_or_exceeds_limit(self, caplog, monkeypatch):
        # Given: two workers and the API process, deliberately set at the limit
        monkeypatch.setattr(settings, "OCR_WORKER_COUNT", 2)
        one_call_peak = _estimate_call_peak_mib()
        monkeypatch.setattr(
            "src.config.startup_banner.detect_memory_limit_mib",
            lambda: one_call_peak * 2 + API_PROCESS_MIB,
        )
        caplog.set_level("WARNING", logger="uvicorn")

        # When
        log_startup_banner()

        # Then
        warnings = [record for record in caplog.records if record.levelname == "WARNING"]
        assert len(warnings) == 1
        assert "OCR_WORKER_COUNT=2" in warnings[0].message
        assert "cgroup limit" in warnings[0].message

    def test_never_raises_or_blocks_startup(self, caplog, monkeypatch):
        # Given: a configuration that would never fit, still must not raise
        monkeypatch.setattr(settings, "OCR_WORKER_COUNT", 100)
        monkeypatch.setattr("src.config.startup_banner.detect_memory_limit_mib", lambda: 1.0)
        caplog.set_level("WARNING", logger="uvicorn")

        # When / Then: no exception
        log_startup_banner()

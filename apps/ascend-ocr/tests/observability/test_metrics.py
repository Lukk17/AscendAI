import os

from prometheus_client import values as prometheus_values

from src.observability.metrics import (
    ENGINE_CACHE_EVICTIONS_TOTAL,
    ENGINE_WARMUP_DURATION_SECONDS,
    MCP_DOWNLOAD_DURATION_SECONDS,
    OCR_DURATION_SECONDS,
    OCR_ERRORS_TOTAL,
    OCR_REQUESTS_TOTAL,
    is_engine_warm,
)


class TestMetricRegistration:
    def test_ocr_duration_has_expected_labels(self):
        # Then
        assert OCR_DURATION_SECONDS._labelnames == ("surface", "language")

    def test_ocr_requests_has_expected_labels(self):
        # Then
        assert OCR_REQUESTS_TOTAL._labelnames == ("surface", "language")

    def test_ocr_errors_has_expected_labels(self):
        # Then
        assert OCR_ERRORS_TOTAL._labelnames == ("error_code", "surface")

    def test_engine_cache_evictions_has_expected_labels(self):
        # Then
        assert ENGINE_CACHE_EVICTIONS_TOTAL._labelnames == ("language",)

    def test_engine_warmup_has_expected_labels(self):
        # Then
        assert ENGINE_WARMUP_DURATION_SECONDS._labelnames == ("language",)

    def test_mcp_download_has_expected_labels(self):
        # Then
        assert MCP_DOWNLOAD_DURATION_SECONDS._labelnames == ("outcome",)


class TestMetricRecording:
    def test_counter_inc_does_not_raise(self):
        # When / Then
        OCR_REQUESTS_TOTAL.labels(surface="rest", language="en").inc()

    def test_histogram_observe_does_not_raise(self):
        # When / Then
        OCR_DURATION_SECONDS.labels(surface="rest", language="en").observe(0.123)
        MCP_DOWNLOAD_DURATION_SECONDS.labels(outcome="ok").observe(0.456)
        ENGINE_WARMUP_DURATION_SECONDS.labels(language="en").observe(1.0)

    def test_eviction_counter_increments(self):
        # When
        before = ENGINE_CACHE_EVICTIONS_TOTAL.labels(language="xx")._value.get()
        ENGINE_CACHE_EVICTIONS_TOTAL.labels(language="xx").inc()
        after = ENGINE_CACHE_EVICTIONS_TOTAL.labels(language="xx")._value.get()

        # Then
        assert after == before + 1


class TestPrometheusMultiprocessMode:
    def test_multiproc_dir_env_var_points_to_existing_directory(self):
        # Then. src/__init__.py must set this, and create the directory, before
        # prometheus_client is imported anywhere in the process: otherwise counters
        # incremented in the OCR worker process never reach the main process's own
        # /metrics scrape (see src/__init__.py for the full rationale).
        multiproc_dir = os.environ["PROMETHEUS_MULTIPROC_DIR"]
        assert os.path.isdir(multiproc_dir)

    def test_value_class_is_multiprocess_backed(self):
        # Then. Confirms the env var above was set before prometheus_client.values was
        # first imported, since ValueClass is chosen once, at that import time.
        assert prometheus_values.ValueClass._multiprocess is True


class TestIsEngineWarm:
    def test_false_for_language_never_observed(self):
        # Then — no worker has ever called warm_up_engine for this language, so its
        # count sample doesn't exist in any multiprocess file yet.
        assert is_engine_warm("cold-probe-never-observed") is False

    def test_true_after_a_successful_warm_up_observation(self):
        # Given. Simulates what the OCR worker's warm_up_engine() does on success: it
        # only calls .observe() after _get_engine() returns without raising.
        ENGINE_WARMUP_DURATION_SECONDS.labels(language="warm-probe").observe(1.0)

        # Then
        assert is_engine_warm("warm-probe") is True

    def test_false_when_only_a_different_language_warmed_up(self):
        # Given
        ENGINE_WARMUP_DURATION_SECONDS.labels(language="warm-probe-pl").observe(1.0)

        # Then — the default language never warmed, so it stays not-ready even though
        # some other language did
        assert is_engine_warm("cold-probe-different-language") is False

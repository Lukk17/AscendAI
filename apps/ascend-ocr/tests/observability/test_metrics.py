import os

import pytest
from prometheus_client import values as prometheus_values
from prometheus_client.metrics import MetricWrapperBase

from src.observability import metrics as metrics_module
from src.observability.metrics import (
    ENGINE_CACHE_EVICTIONS_TOTAL,
    ENGINE_WARMUP_DURATION_SECONDS,
    JOB_DURATION_SECONDS,
    JOB_QUEUE_DOCUMENTS,
    JOB_QUEUE_PAGES,
    JOB_QUEUE_WAIT_SECONDS,
    JOBS_RETAINED,
    JOBS_TOTAL,
    MCP_DOWNLOAD_DURATION_SECONDS,
    OCR_DURATION_SECONDS,
    OCR_ERRORS_TOTAL,
    OCR_REQUESTS_TOTAL,
    RESULT_UPLOAD_ATTEMPTS_TOTAL,
    RESULT_UPLOAD_FAILURES_TOTAL,
    UNSUPPORTED_LANGUAGE_LABEL,
    is_engine_warm,
    request_language_label,
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
        # Then - the cache is keyed by the model pair, so the label names the engine
        assert ENGINE_CACHE_EVICTIONS_TOTAL._labelnames == ("engine",)

    def test_engine_warmup_has_expected_labels(self):
        # Then
        assert ENGINE_WARMUP_DURATION_SECONDS._labelnames == ("language",)

    def test_mcp_download_has_expected_labels(self):
        # Then
        assert MCP_DOWNLOAD_DURATION_SECONDS._labelnames == ("outcome",)


class TestRequestLanguageLabel:
    @pytest.mark.parametrize("language", ["en", "pl", "japan"])
    def test_a_supported_language_is_its_own_label(self, language):
        # Then
        assert request_language_label(language) == language

    @pytest.mark.parametrize("language", ["korean", "ru", "xx", "not-a-language-at-all"])
    def test_anything_refused_shares_one_fixed_label(self, language):
        # Then: a caller cannot mint label values
        assert request_language_label(language) == UNSUPPORTED_LANGUAGE_LABEL == "unsupported"


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
        before = ENGINE_CACHE_EVICTIONS_TOTAL.labels(engine="xx")._value.get()
        ENGINE_CACHE_EVICTIONS_TOTAL.labels(engine="xx").inc()
        after = ENGINE_CACHE_EVICTIONS_TOTAL.labels(engine="xx")._value.get()

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
        # Then - no worker has ever called warm_up_engine for this language, so its
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

        # Then - the default language never warmed, so it stays not-ready even though
        # some other language did
        assert is_engine_warm("cold-probe-different-language") is False


class TestJobMetrics:
    def test_job_outcomes_are_counted_by_terminal_state(self):
        # Then
        assert JOBS_TOTAL._labelnames == ("outcome",)

    @pytest.mark.parametrize("outcome", ["succeeded", "failed", "cancelled"])
    def test_each_terminal_state_can_be_counted(self, outcome):
        # When
        before = JOBS_TOTAL.labels(outcome=outcome)._value.get()
        JOBS_TOTAL.labels(outcome=outcome).inc()

        # Then
        assert JOBS_TOTAL.labels(outcome=outcome)._value.get() == before + 1

    def test_the_queue_is_measured_in_documents_and_in_pages(self):
        # When
        JOB_QUEUE_DOCUMENTS.set(3)
        JOB_QUEUE_PAGES.set(42)

        # Then
        assert JOB_QUEUE_DOCUMENTS._value.get() == 3
        assert JOB_QUEUE_PAGES._value.get() == 42

    def test_the_queue_gauges_return_to_zero_when_the_queue_drains(self):
        # Given
        JOB_QUEUE_DOCUMENTS.set(3)
        JOB_QUEUE_PAGES.set(42)

        # When
        JOB_QUEUE_DOCUMENTS.set(0)
        JOB_QUEUE_PAGES.set(0)

        # Then
        assert JOB_QUEUE_DOCUMENTS._value.get() == 0
        assert JOB_QUEUE_PAGES._value.get() == 0

    def test_waiting_work_is_reported_only_by_the_job_queue_gauges(self):
        # Given
        declared = _declared_metric_names()

        # Then: nothing counts waiters on the admission gate, whose only client is the job runner
        assert "ascendocr_ocr_queue_depth" not in declared
        assert {"ascendocr_job_queue_documents", "ascendocr_job_queue_pages"} <= declared

    def test_the_wait_is_measured_only_in_the_job_queue(self):
        # Given
        declared = _declared_metric_names()

        # Then: the admission gate's wait is not timed, because the runner never waits on it
        assert "ascendocr_ocr_queue_wait_seconds" not in declared
        assert "ascendocr_job_queue_wait_seconds" in declared

    def test_the_wait_and_the_reading_are_measured_separately(self):
        # When / Then - no raise
        JOB_QUEUE_WAIT_SECONDS.observe(12.0)
        JOB_DURATION_SECONDS.observe(240.0)

    def test_retained_records_are_reported(self):
        # When
        JOBS_RETAINED.set(7)

        # Then
        assert JOBS_RETAINED._value.get() == 7

    def test_result_uploads_are_counted_by_attempt_and_by_failure(self):
        # Given
        attempts_before = RESULT_UPLOAD_ATTEMPTS_TOTAL._value.get()
        failures_before = RESULT_UPLOAD_FAILURES_TOTAL._value.get()

        # When
        RESULT_UPLOAD_ATTEMPTS_TOTAL.inc()
        RESULT_UPLOAD_FAILURES_TOTAL.inc()

        # Then
        assert RESULT_UPLOAD_ATTEMPTS_TOTAL._value.get() == attempts_before + 1
        assert RESULT_UPLOAD_FAILURES_TOTAL._value.get() == failures_before + 1


def _declared_metric_names() -> set[str]:
    return {
        family.name
        for value in vars(metrics_module).values()
        if isinstance(value, MetricWrapperBase)
        for family in value.describe()
    }

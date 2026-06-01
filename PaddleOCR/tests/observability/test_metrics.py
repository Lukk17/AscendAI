from src.observability.metrics import (
    ENGINE_CACHE_EVICTIONS_TOTAL,
    ENGINE_WARMUP_DURATION_SECONDS,
    MCP_DOWNLOAD_DURATION_SECONDS,
    OCR_DURATION_SECONDS,
    OCR_ERRORS_TOTAL,
    OCR_REQUESTS_TOTAL,
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

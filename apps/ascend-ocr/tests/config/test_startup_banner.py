from unittest.mock import patch

from src.config.config import settings
from src.config.startup_banner import _estimate_call_peak_mib, _resolve_host, log_startup_banner


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

    def test_emits_memory_ceiling_line_with_detector_bound_configured(self, caplog, monkeypatch):
        # Given
        monkeypatch.setattr(settings, "OCR_DETECTOR_MAX_SIDE", 1536)
        caplog.set_level("INFO", logger="uvicorn")

        # When
        log_startup_banner()

        # Then
        joined = "\n".join(record.message for record in caplog.records)
        assert "Detector max side: 1536" in joined

    def test_emits_memory_ceiling_line_with_detector_bound_unset(self, caplog, monkeypatch):
        # Given
        monkeypatch.setattr(settings, "OCR_DETECTOR_MAX_SIDE", None)
        caplog.set_level("INFO", logger="uvicorn")

        # When
        log_startup_banner()

        # Then
        joined = "\n".join(record.message for record in caplog.records)
        assert "Detector max side: (unbounded)" in joined


class TestEstimateCallPeakMib:
    def test_unbounded_detector_uses_full_input_resolution(self, monkeypatch):
        # Given — with no detector bound, the whole input megapixel count reaches
        # detection, so the estimate must not clamp it to a detector-side term.
        monkeypatch.setattr(settings, "OCR_DETECTOR_MAX_SIDE", None)
        monkeypatch.setattr(settings, "OCR_MAX_INFERENCE_PIXELS", 1_000_000)

        # When
        unbounded_peak = _estimate_call_peak_mib()

        monkeypatch.setattr(settings, "OCR_DETECTOR_MAX_SIDE", 500)
        bounded_peak = _estimate_call_peak_mib()

        # Then — the same input costs less once detection is bounded below it
        assert bounded_peak < unbounded_peak


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
        # Given — a limit comfortably above whatever one worker is estimated to cost
        monkeypatch.setattr(settings, "OCR_WORKER_COUNT", 1)
        monkeypatch.setattr(
            "src.config.startup_banner.detect_memory_limit_mib",
            lambda: _estimate_call_peak_mib() * 10,
        )
        caplog.set_level("WARNING", logger="uvicorn")

        # When
        log_startup_banner()

        # Then
        assert not any(record.levelname == "WARNING" for record in caplog.records)

    def test_warns_when_service_peak_meets_or_exceeds_limit(self, caplog, monkeypatch):
        # Given — two workers cost twice one worker's peak, deliberately set at the limit
        monkeypatch.setattr(settings, "OCR_WORKER_COUNT", 2)
        one_call_peak = _estimate_call_peak_mib()
        monkeypatch.setattr(
            "src.config.startup_banner.detect_memory_limit_mib",
            lambda: one_call_peak * 2,
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
        # Given — a configuration that would never fit, still must not raise
        monkeypatch.setattr(settings, "OCR_WORKER_COUNT", 100)
        monkeypatch.setattr("src.config.startup_banner.detect_memory_limit_mib", lambda: 1.0)
        caplog.set_level("WARNING", logger="uvicorn")

        # When / Then — no exception
        log_startup_banner()

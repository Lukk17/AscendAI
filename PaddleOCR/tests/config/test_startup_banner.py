from unittest.mock import patch

from src.config.config import settings
from src.config.startup_banner import _estimate_call_peak_mib, _resolve_host, log_startup_banner


class TestResolveHost:
    def test_returns_hostname_on_success(self):
        # Given
        with patch(
            "src.config.startup_banner.socket.gethostname",
            return_value="paddle-host",
        ):
            # When
            host = _resolve_host()

        # Then
        assert host == "paddle-host"

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
        assert "paddle-ocr" in joined
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

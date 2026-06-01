from unittest.mock import patch

from src.config.startup_banner import _resolve_host, log_startup_banner


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

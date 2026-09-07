import pytest

from src.config.config import Settings


class TestSettingsDefaults:
    def test_default_api_host(self):
        # Then
        assert Settings().API_HOST == "0.0.0.0"  # noqa: S104

    def test_default_api_port(self):
        # Then
        assert Settings().API_PORT == 7022

    def test_default_log_level(self):
        # Then
        assert Settings().LOG_LEVEL == "INFO"

    def test_default_language(self):
        # Then
        assert Settings().DEFAULT_LANGUAGE == "en"

    def test_default_max_file_size(self):
        # Then
        assert Settings().MAX_FILE_SIZE_MB == 50

    def test_default_ocr_timeout(self):
        # Then
        assert pytest.approx(120.0) == Settings().OCR_REQUEST_TIMEOUT

    def test_default_engine_cache_max_size(self):
        # Then
        assert Settings().ENGINE_CACHE_MAX_SIZE == 8

    def test_default_supported_languages_uses_paddleocr_native_codes(self):
        # Then. "japan"/"korean" are PaddleOCR's own codes for those languages. The
        # ISO two-letter "ja"/"ko" resolve to no model in the engine's own lookup table.
        languages = Settings().SUPPORTED_LANGUAGES
        assert "japan" in languages
        assert "korean" in languages
        assert "ja" not in languages
        assert "ko" not in languages

    def test_default_mcp_file_uri_root_unset(self):
        # Then
        assert Settings().MCP_FILE_URI_ROOT is None

    def test_default_mcp_allowed_hosts_empty(self):
        # Then
        assert Settings().MCP_ALLOWED_HOSTS == ()

    def test_default_mcp_download_timeout(self):
        # Then
        assert pytest.approx(30.0) == Settings().MCP_DOWNLOAD_TIMEOUT_SECONDS


class TestSettingsEnvOverride:
    def test_override_api_port(self, monkeypatch):
        # Given
        monkeypatch.setenv("API_PORT", "9999")

        # Then
        assert Settings().API_PORT == 9999

    def test_override_default_language(self, monkeypatch):
        # Given
        monkeypatch.setenv("DEFAULT_LANGUAGE", "pl")

        # Then
        assert Settings().DEFAULT_LANGUAGE == "pl"

    def test_override_max_file_size(self, monkeypatch):
        # Given
        monkeypatch.setenv("MAX_FILE_SIZE_MB", "100")

        # Then
        assert Settings().MAX_FILE_SIZE_MB == 100

    def test_override_log_level(self, monkeypatch):
        # Given
        monkeypatch.setenv("LOG_LEVEL", "DEBUG")

        # Then
        assert Settings().LOG_LEVEL == "DEBUG"

    def test_override_mcp_file_uri_root(self, monkeypatch):
        # Given
        monkeypatch.setenv("MCP_FILE_URI_ROOT", "/var/lib/paddle-ocr/uploads")

        # Then
        assert Settings().MCP_FILE_URI_ROOT == "/var/lib/paddle-ocr/uploads"

    def test_override_mcp_allowed_hosts_csv(self, monkeypatch):
        # Given
        monkeypatch.setenv("MCP_ALLOWED_HOSTS", "host.docker.internal,localhost,127.0.0.1")

        # Then
        assert Settings().MCP_ALLOWED_HOSTS == ("host.docker.internal", "localhost", "127.0.0.1")

    def test_override_mcp_allowed_hosts_csv_strips_whitespace(self, monkeypatch):
        # Given
        monkeypatch.setenv("MCP_ALLOWED_HOSTS", "  host.docker.internal , localhost  , ,127.0.0.1 ")

        # Then. Empty entries dropped, whitespace stripped from each.
        assert Settings().MCP_ALLOWED_HOSTS == ("host.docker.internal", "localhost", "127.0.0.1")

    def test_override_supported_languages_csv(self, monkeypatch):
        # Given
        monkeypatch.setenv("SUPPORTED_LANGUAGES", "en,pl,fr")

        # Then
        assert Settings().SUPPORTED_LANGUAGES == ("en", "pl", "fr")


class TestSettingsValidation:
    def test_invalid_log_level_rejected(self, monkeypatch):
        # Given
        monkeypatch.setenv("LOG_LEVEL", "TRACE")

        # Then
        with pytest.raises(ValueError):
            Settings()

    def test_invalid_language_pattern_rejected(self, monkeypatch):
        # Given
        monkeypatch.setenv("DEFAULT_LANGUAGE", "../etc")

        # Then
        with pytest.raises(ValueError):
            Settings()

    def test_six_letter_default_language_accepted(self, monkeypatch):
        # Given. "korean" is the longest PaddleOCR-native code this service supports.
        monkeypatch.setenv("DEFAULT_LANGUAGE", "korean")

        # Then
        assert Settings().DEFAULT_LANGUAGE == "korean"

    def test_seven_letter_default_language_rejected(self, monkeypatch):
        # Given
        monkeypatch.setenv("DEFAULT_LANGUAGE", "abcdefg")

        # Then
        with pytest.raises(ValueError):
            Settings()

    def test_zero_max_file_size_rejected(self, monkeypatch):
        # Given
        monkeypatch.setenv("MAX_FILE_SIZE_MB", "0")

        # Then
        with pytest.raises(ValueError):
            Settings()

    def test_negative_ocr_timeout_rejected(self, monkeypatch):
        # Given
        monkeypatch.setenv("OCR_REQUEST_TIMEOUT", "-1")

        # Then
        with pytest.raises(ValueError):
            Settings()


class TestNewLimitsSettingsDefaults:
    def test_default_worker_count(self):
        # Then
        assert Settings().OCR_WORKER_COUNT == 1

    def test_default_page_timeout(self):
        # Then
        assert pytest.approx(120.0) == Settings().OCR_PAGE_TIMEOUT_SECONDS

    def test_default_dispatch_margin(self):
        # Then
        assert pytest.approx(5.0) == Settings().OCR_DISPATCH_MARGIN_SECONDS

    def test_default_max_inference_pixels(self):
        # Then
        assert Settings().OCR_MAX_INFERENCE_PIXELS == 2_500_000

    def test_default_detector_max_side(self):
        # Then. The owner's settled decision: text_det_limit_type="max" at 1536 (see
        # design.md Decision 11), against the 960/1280 alternatives measured there.
        assert Settings().OCR_DETECTOR_MAX_SIDE == 1536

    def test_default_pool_rebuild_max_consecutive(self):
        # Then
        assert Settings().OCR_POOL_REBUILD_MAX_CONSECUTIVE == 3

    def test_default_scratch_dir_is_under_system_temp(self):
        # Then
        assert "paddle-ocr-scratch" in Settings().OCR_SCRATCH_DIR


class TestNewLimitsSettingsOverrides:
    def test_override_worker_count(self, monkeypatch):
        # Given
        monkeypatch.setenv("OCR_WORKER_COUNT", "2")

        # Then
        assert Settings().OCR_WORKER_COUNT == 2

    def test_override_page_timeout(self, monkeypatch):
        # Given
        monkeypatch.setenv("OCR_PAGE_TIMEOUT_SECONDS", "60")

        # Then
        assert pytest.approx(60.0) == Settings().OCR_PAGE_TIMEOUT_SECONDS

    def test_override_dispatch_margin(self, monkeypatch):
        # Given
        monkeypatch.setenv("OCR_DISPATCH_MARGIN_SECONDS", "10")

        # Then
        assert pytest.approx(10.0) == Settings().OCR_DISPATCH_MARGIN_SECONDS

    def test_override_max_inference_pixels(self, monkeypatch):
        # Given
        monkeypatch.setenv("OCR_MAX_INFERENCE_PIXELS", "1000000")

        # Then
        assert Settings().OCR_MAX_INFERENCE_PIXELS == 1_000_000

    def test_override_detector_max_side(self, monkeypatch):
        # Given
        monkeypatch.setenv("OCR_DETECTOR_MAX_SIDE", "960")

        # Then
        assert Settings().OCR_DETECTOR_MAX_SIDE == 960

    def test_override_detector_max_side_unset_disables_bound(self, monkeypatch):
        # Given — unset keeps today's detection behaviour (design.md Decision 11)
        monkeypatch.setenv("OCR_DETECTOR_MAX_SIDE", "")

        # Then
        assert Settings().OCR_DETECTOR_MAX_SIDE is None

    def test_override_pool_rebuild_max_consecutive(self, monkeypatch):
        # Given
        monkeypatch.setenv("OCR_POOL_REBUILD_MAX_CONSECUTIVE", "5")

        # Then
        assert Settings().OCR_POOL_REBUILD_MAX_CONSECUTIVE == 5

    def test_override_scratch_dir(self, monkeypatch, tmp_path):
        # Given
        monkeypatch.setenv("OCR_SCRATCH_DIR", str(tmp_path))

        # Then
        assert str(tmp_path) == Settings().OCR_SCRATCH_DIR


class TestNewLimitsSettingsValidation:
    def test_zero_worker_count_rejected(self, monkeypatch):
        # Given
        monkeypatch.setenv("OCR_WORKER_COUNT", "0")

        # Then
        with pytest.raises(ValueError):
            Settings()

    def test_zero_page_timeout_rejected(self, monkeypatch):
        # Given
        monkeypatch.setenv("OCR_PAGE_TIMEOUT_SECONDS", "0")

        # Then
        with pytest.raises(ValueError):
            Settings()

    def test_zero_dispatch_margin_rejected(self, monkeypatch):
        # Given
        monkeypatch.setenv("OCR_DISPATCH_MARGIN_SECONDS", "0")

        # Then
        with pytest.raises(ValueError):
            Settings()

    def test_zero_max_inference_pixels_rejected(self, monkeypatch):
        # Given
        monkeypatch.setenv("OCR_MAX_INFERENCE_PIXELS", "0")

        # Then
        with pytest.raises(ValueError):
            Settings()

    def test_zero_detector_max_side_rejected(self, monkeypatch):
        # Given
        monkeypatch.setenv("OCR_DETECTOR_MAX_SIDE", "0")

        # Then
        with pytest.raises(ValueError):
            Settings()

    def test_zero_pool_rebuild_max_consecutive_rejected(self, monkeypatch):
        # Given
        monkeypatch.setenv("OCR_POOL_REBUILD_MAX_CONSECUTIVE", "0")

        # Then
        with pytest.raises(ValueError):
            Settings()

    def test_page_timeout_exceeding_request_timeout_rejected(self, monkeypatch):
        # Given — the derived page limit (floor(ceiling / per-page)) would be zero,
        # refusing every document regardless of size
        monkeypatch.setenv("OCR_REQUEST_TIMEOUT", "100")
        monkeypatch.setenv("OCR_PAGE_TIMEOUT_SECONDS", "150")

        # Then
        with pytest.raises(ValueError, match="OCR_PAGE_TIMEOUT_SECONDS"):
            Settings()

    def test_page_timeout_equal_to_request_timeout_accepted(self, monkeypatch):
        # Given — floor(100 / 100) == 1, a legitimate one-page limit
        monkeypatch.setenv("OCR_REQUEST_TIMEOUT", "100")
        monkeypatch.setenv("OCR_PAGE_TIMEOUT_SECONDS", "100")

        # Then
        assert Settings().OCR_MAX_PAGES == 1


class TestDerivedProperties:
    def test_max_pages_recomputes_when_inputs_change(self, monkeypatch):
        # Given
        monkeypatch.setenv("OCR_REQUEST_TIMEOUT", "300")
        monkeypatch.setenv("OCR_PAGE_TIMEOUT_SECONDS", "100")
        settings_a = Settings()
        assert settings_a.OCR_MAX_PAGES == 3

        # When
        monkeypatch.setenv("OCR_PAGE_TIMEOUT_SECONDS", "150")
        settings_b = Settings()

        # Then
        assert settings_b.OCR_MAX_PAGES == 2

    def test_max_pages_is_not_settable_from_the_environment(self, monkeypatch):
        # Given
        monkeypatch.setenv("OCR_MAX_PAGES", "999")

        # Then — unknown env vars are ignored (extra="ignore"); it stays derived
        monkeypatch.setenv("OCR_REQUEST_TIMEOUT", "300")
        monkeypatch.setenv("OCR_PAGE_TIMEOUT_SECONDS", "100")
        assert Settings().OCR_MAX_PAGES == 3

    def test_reclamation_grace_recomputes_when_inputs_change(self, monkeypatch):
        # Given
        monkeypatch.setenv("OCR_PAGE_TIMEOUT_SECONDS", "100")
        monkeypatch.setenv("OCR_DISPATCH_MARGIN_SECONDS", "5")
        settings_a = Settings()
        assert pytest.approx(105.0) == settings_a.OCR_RECLAMATION_GRACE_SECONDS

        # When
        monkeypatch.setenv("OCR_DISPATCH_MARGIN_SECONDS", "10")
        settings_b = Settings()

        # Then
        assert pytest.approx(110.0) == settings_b.OCR_RECLAMATION_GRACE_SECONDS

    def test_reclamation_grace_is_not_settable_from_the_environment(self, monkeypatch):
        # Given
        monkeypatch.setenv("OCR_RECLAMATION_GRACE_SECONDS", "999")

        # Then — unknown env vars are ignored (extra="ignore"); it stays derived
        monkeypatch.setenv("OCR_PAGE_TIMEOUT_SECONDS", "100")
        monkeypatch.setenv("OCR_DISPATCH_MARGIN_SECONDS", "5")
        assert pytest.approx(105.0) == Settings().OCR_RECLAMATION_GRACE_SECONDS

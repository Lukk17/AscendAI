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

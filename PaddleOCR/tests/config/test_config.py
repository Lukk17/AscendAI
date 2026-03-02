import os

import pytest

from src.config.config import Settings


class TestSettingsDefaults:
    def test_default_api_host(self):
        # Arrange / Act
        test_settings = Settings()

        # Assert
        assert test_settings.API_HOST == "0.0.0.0"

    def test_default_api_port(self):
        # Arrange / Act
        test_settings = Settings()

        # Assert
        assert test_settings.API_PORT == 7022

    def test_default_log_level(self):
        # Arrange / Act
        test_settings = Settings()

        # Assert
        assert test_settings.LOG_LEVEL == "INFO"

    def test_default_language(self):
        # Arrange / Act
        test_settings = Settings()

        # Assert
        assert test_settings.DEFAULT_LANGUAGE == "en"

    def test_default_output_format(self):
        # Arrange / Act
        test_settings = Settings()

        # Assert
        assert test_settings.DEFAULT_OUTPUT_FORMAT == "json"

    def test_default_max_file_size(self):
        # Arrange / Act
        test_settings = Settings()

        # Assert
        assert test_settings.MAX_FILE_SIZE_MB == 50

    def test_default_ocr_timeout(self):
        # Arrange / Act
        test_settings = Settings()

        # Assert
        assert test_settings.OCR_REQUEST_TIMEOUT == 120.0


class TestSettingsEnvOverride:
    def test_override_api_port(self, monkeypatch):
        # Arrange
        monkeypatch.setenv("API_PORT", "9999")

        # Act
        test_settings = Settings()

        # Assert
        assert test_settings.API_PORT == 9999

    def test_override_default_language(self, monkeypatch):
        # Arrange
        monkeypatch.setenv("DEFAULT_LANGUAGE", "pl")

        # Act
        test_settings = Settings()

        # Assert
        assert test_settings.DEFAULT_LANGUAGE == "pl"

    def test_override_max_file_size(self, monkeypatch):
        # Arrange
        monkeypatch.setenv("MAX_FILE_SIZE_MB", "100")

        # Act
        test_settings = Settings()

        # Assert
        assert test_settings.MAX_FILE_SIZE_MB == 100

    def test_override_log_level(self, monkeypatch):
        # Arrange
        monkeypatch.setenv("LOG_LEVEL", "DEBUG")

        # Act
        test_settings = Settings()

        # Assert
        assert test_settings.LOG_LEVEL == "DEBUG"

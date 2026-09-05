import os
from unittest.mock import patch

from src.config.config import Settings


def test_settings_defaults():
    # given
    # When initializing settings without env vars
    settings = Settings()

    # then
    assert settings.API_PORT == 7021
    assert settings.API_HOST == "0.0.0.0"
    assert settings.SEARXNG_BASE_URL == "http://localhost:9020"


def test_settings_env_override():
    # given
    # Mocking environment variables
    with patch.dict(os.environ, {"API_PORT": "9000"}):
        # when
        settings = Settings()

        # then
        assert settings.API_PORT == 9000


def test_blocklist_path_defaults_to_vendored_asset():
    # given
    # When initializing settings without env vars
    settings = Settings()

    # then
    assert settings.BLOCKLIST_PATH == "src/assets/fanboy-annoyance.txt"


def test_blocklist_path_env_override(tmp_path):
    # given
    # Mocking environment variables
    override = str(tmp_path / "custom-blocklist.txt")
    with patch.dict(os.environ, {"BLOCKLIST_PATH": override}):
        # when
        settings = Settings()

        # then
        assert override == settings.BLOCKLIST_PATH


def test_blocklist_refresh_min_interval_default():
    # given
    settings = Settings()

    # then
    assert settings.BLOCKLIST_REFRESH_MIN_INTERVAL_SECONDS == 60.0

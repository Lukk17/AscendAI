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

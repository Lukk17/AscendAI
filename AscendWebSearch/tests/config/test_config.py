import os
import tempfile
from pathlib import Path
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


def test_blocklist_cache_dir_defaults_outside_repo():
    # given
    # When initializing settings without env vars
    settings = Settings()

    # then
    expected = Path(tempfile.gettempdir()) / "ascend-web-search" / "blocklist"
    assert Path(settings.BLOCKLIST_CACHE_DIR) == expected


def test_blocklist_cache_dir_env_override(tmp_path):
    # given
    # Mocking environment variables
    with patch.dict(os.environ, {"BLOCKLIST_CACHE_DIR": str(tmp_path)}):
        # when
        settings = Settings()

        # then
        assert str(tmp_path) == settings.BLOCKLIST_CACHE_DIR

import os
from unittest.mock import patch

from src.config.config import Settings, settings


def test_settings_defaults() -> None:
    # when
    fresh = Settings()

    # then
    assert fresh.MCP_PORT == 7017
    assert fresh.MCP_HOST == "0.0.0.0"
    assert fresh.MAX_UPLOAD_BYTES == 5 * 1024 * 1024 * 1024
    assert fresh.MAX_DOWNLOAD_BYTES == 5 * 1024 * 1024 * 1024
    assert fresh.MCP_FILE_URI_ROOT is None
    assert fresh.MCP_ALLOWED_HOSTS == []
    assert fresh.FFMPEG_PATH == "ffmpeg"
    assert fresh.FFPROBE_PATH == "ffprobe"


def test_settings_env_override() -> None:
    # when
    with patch.dict(os.environ, {"MCP_PORT": "9999", "FFMPEG_PATH": "/usr/bin/ffmpeg"}):
        fresh = Settings()

    # then
    assert fresh.MCP_PORT == 9999
    assert fresh.FFMPEG_PATH == "/usr/bin/ffmpeg"


def test_module_level_singleton_exists() -> None:
    # when / then
    assert settings.MCP_PORT == 7017


def test_allowed_hosts_csv_env_var_splits_into_list() -> None:
    # when
    with patch.dict(os.environ, {"MCP_ALLOWED_HOSTS": "host.docker.internal,localhost, internal-store"}):
        fresh = Settings()

    # then
    assert fresh.MCP_ALLOWED_HOSTS == ["host.docker.internal", "localhost", "internal-store"]


def test_allowed_hosts_native_list_form_passes_through() -> None:
    # when
    fresh = Settings(MCP_ALLOWED_HOSTS=["a", "b"])

    # then
    assert fresh.MCP_ALLOWED_HOSTS == ["a", "b"]


def test_allowed_hosts_empty_csv_env_var_yields_empty_list() -> None:
    # when
    with patch.dict(os.environ, {"MCP_ALLOWED_HOSTS": " , , "}):
        fresh = Settings()

    # then
    assert fresh.MCP_ALLOWED_HOSTS == []

import os
from unittest.mock import patch

from src.config.config import Settings, settings


def test_settings_defaults() -> None:
    fresh = Settings()
    assert fresh.MCP_PORT == 7017
    assert fresh.MCP_HOST == "0.0.0.0"
    assert fresh.MAX_UPLOAD_BYTES == 5 * 1024 * 1024 * 1024
    assert fresh.MAX_DOWNLOAD_BYTES == 5 * 1024 * 1024 * 1024
    assert fresh.MCP_FILE_URI_ROOT is None
    assert fresh.MCP_ALLOWED_HOSTS == []
    assert fresh.FFMPEG_PATH == "ffmpeg"
    assert fresh.FFPROBE_PATH == "ffprobe"


def test_settings_env_override() -> None:
    with patch.dict(os.environ, {"MCP_PORT": "9999", "FFMPEG_PATH": "/usr/bin/ffmpeg"}):
        fresh = Settings()
    assert fresh.MCP_PORT == 9999
    assert fresh.FFMPEG_PATH == "/usr/bin/ffmpeg"


def test_module_level_singleton_exists() -> None:
    assert settings.MCP_PORT == 7017


def test_allowed_hosts_csv_env_var_splits_into_list() -> None:
    with patch.dict(os.environ, {"MCP_ALLOWED_HOSTS": "host.docker.internal,localhost, minio"}):
        fresh = Settings()
    assert fresh.MCP_ALLOWED_HOSTS == ["host.docker.internal", "localhost", "minio"]


def test_allowed_hosts_native_list_form_passes_through() -> None:
    fresh = Settings(MCP_ALLOWED_HOSTS=["a", "b"])
    assert fresh.MCP_ALLOWED_HOSTS == ["a", "b"]


def test_allowed_hosts_empty_csv_env_var_yields_empty_list() -> None:
    with patch.dict(os.environ, {"MCP_ALLOWED_HOSTS": " , , "}):
        fresh = Settings()
    assert fresh.MCP_ALLOWED_HOSTS == []

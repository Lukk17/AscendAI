import os
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from src.config.config import Settings, settings


def test_settings_defaults() -> None:
    # given
    fresh = Settings()
    # when
    host = fresh.API_HOST
    port = fresh.API_PORT
    # then
    assert port == 7017
    assert host == "0.0.0.0"
    assert fresh.MAX_UPLOAD_BYTES == 5 * 1024 * 1024 * 1024
    assert fresh.MAX_DOWNLOAD_BYTES == 5 * 1024 * 1024 * 1024
    assert fresh.MCP_FILE_URI_ROOT is None
    assert fresh.ALLOWED_PRIVATE_HOSTS == ()
    assert fresh.FFMPEG_PATH == "ffmpeg"
    assert fresh.FFPROBE_PATH == "ffprobe"


def test_settings_env_override() -> None:
    # given
    env = {"API_PORT": "9999", "FFMPEG_PATH": "/usr/bin/ffmpeg"}
    # when
    with patch.dict(os.environ, env):
        fresh = Settings()
    # then
    assert fresh.API_PORT == 9999
    assert fresh.FFMPEG_PATH == "/usr/bin/ffmpeg"


def test_api_port_7117_is_read() -> None:
    # given
    env = {"API_PORT": "7117"}
    # when
    with patch.dict(os.environ, env):
        fresh = Settings()
    # then
    assert fresh.API_PORT == 7117


def test_module_level_singleton_exists() -> None:
    # given
    port = settings.API_PORT
    # when / then
    assert port == 7017


def test_allowed_hosts_csv_env_var_splits_into_list() -> None:
    # given
    env = {"ALLOWED_PRIVATE_HOSTS": "host.docker.internal,localhost, internal-store"}
    # when
    with patch.dict(os.environ, env):
        fresh = Settings()
    # then
    assert fresh.ALLOWED_PRIVATE_HOSTS == ("host.docker.internal", "localhost", "internal-store")


def test_allowed_hosts_native_list_form_passes_through() -> None:
    # given
    hosts = ["a", "b"]
    # when
    fresh = Settings.model_validate({"ALLOWED_PRIVATE_HOSTS": hosts})
    # then
    assert fresh.ALLOWED_PRIVATE_HOSTS == ("a", "b")


def test_allowed_hosts_empty_csv_env_var_yields_empty_list() -> None:
    # given
    env = {"ALLOWED_PRIVATE_HOSTS": " , , "}
    # when
    with patch.dict(os.environ, env):
        fresh = Settings()
    # then
    assert fresh.ALLOWED_PRIVATE_HOSTS == ()


def test_legacy_allow_list_name_refuses_startup() -> None:
    # given
    env = {"MCP_ALLOWED_HOSTS": "host.docker.internal"}
    # when
    with patch.dict(os.environ, env):
        with pytest.raises(ValidationError) as exc_info:
            Settings()
    # then
    assert "MCP_ALLOWED_HOSTS" in str(exc_info.value)
    assert "ALLOWED_PRIVATE_HOSTS" in str(exc_info.value)


def test_redis_url_default_is_loopback(monkeypatch: pytest.MonkeyPatch) -> None:
    # given
    monkeypatch.delenv("REDIS_URL", raising=False)
    # when
    default = Settings().REDIS_URL
    # then
    assert default == "redis://127.0.0.1:6379/0"


def test_fetch_max_redirect_hops_default_is_10() -> None:
    # given
    fresh = Settings()
    # when
    hops = fresh.FETCH_MAX_REDIRECT_HOPS
    # then
    assert hops == 10

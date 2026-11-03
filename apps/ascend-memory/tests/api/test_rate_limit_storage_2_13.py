from collections.abc import Callable

import pytest
from ascend_python_common import app as app_module
from ascend_python_common.rate_limit import DEFAULT_STORAGE_URI, build_limiter
from fastapi import FastAPI, Request
from limits.storage import RedisStorage
from slowapi import Limiter
from slowapi.util import get_remote_address

from src.config.config import Settings
from src.config.config import settings as service_settings
from src.main import create_app


def test_redis_url_default_is_loopback(monkeypatch: pytest.MonkeyPatch) -> None:
    # given
    monkeypatch.delenv("REDIS_URL", raising=False)
    # when
    default = Settings().REDIS_URL
    # then
    assert default == "redis://127.0.0.1:6379/0"


def test_limiter_storage_uri_equals_redis_url_with_service_prefix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # given
    monkeypatch.setattr(service_settings, "REDIS_URL", "redis://127.0.0.1:6379/0")
    seen: dict[str, str] = {}
    real_build_limiter = build_limiter

    def spy_limiter(
        default_limit: str,
        storage_uri: str = DEFAULT_STORAGE_URI,
        key_prefix: str = "",
        key_func: Callable[[Request], str] = get_remote_address,
    ) -> Limiter:
        seen["storage_uri"] = storage_uri
        seen["key_prefix"] = key_prefix
        return real_build_limiter(default_limit, storage_uri, key_prefix, key_func)

    monkeypatch.setattr(app_module, "build_limiter", spy_limiter)
    # when
    wired_app: FastAPI = create_app()
    # then
    assert seen["storage_uri"] == service_settings.REDIS_URL
    assert seen["storage_uri"] == "redis://127.0.0.1:6379/0"
    assert seen["key_prefix"] == "ascend-memory"
    assert wired_app.state.limiter._key_prefix == "ascend-memory"
    assert isinstance(wired_app.state.limiter._storage, RedisStorage)

from collections.abc import Callable

import pytest
from ascend_python_common import app as app_module
from ascend_python_common.rate_limit import DEFAULT_STORAGE_URI, build_limiter
from fastapi import Request
from limits.storage import RedisStorage
from slowapi import Limiter
from slowapi.util import get_remote_address

from src.api.rest import rest_endpoints
from src.config.config import Settings
from src.config.config import settings as service_settings
from src.main import _service_definition, create_app


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
    built: list[Limiter] = []
    real_build_limiter = build_limiter

    def spy_limiter(
        default_limit: str,
        storage_uri: str = DEFAULT_STORAGE_URI,
        key_prefix: str = "",
        key_func: Callable[[Request], str] = get_remote_address,
    ) -> Limiter:
        fresh = real_build_limiter(default_limit, storage_uri, key_prefix, key_func)
        built.append(fresh)
        return fresh

    monkeypatch.setattr(app_module, "build_limiter", spy_limiter)
    # when
    create_app()
    # then - the factory limiter carries the service storage and key prefix
    assert len(built) == 1
    assert built[0]._storage_uri == service_settings.REDIS_URL
    assert built[0]._storage_uri == "redis://127.0.0.1:6379/0"
    assert built[0]._key_prefix == "ascend-ocr"
    assert isinstance(built[0]._storage, RedisStorage)
    # then - the service definition hands the factory that storage URI
    assert _service_definition().rate_limit_storage_uri == service_settings.REDIS_URL
    # then - the limiter the REST decorators use carries the same prefix
    assert rest_endpoints.limiter._key_prefix == "ascend-ocr"
    assert rest_endpoints.limiter._storage_uri == service_settings.REDIS_URL

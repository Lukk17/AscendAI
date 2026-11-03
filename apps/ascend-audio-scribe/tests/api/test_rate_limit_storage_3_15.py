from collections.abc import Callable

import pytest
from ascend_python_common import app as app_module
from ascend_python_common.errors import ErrorRegistry, install_error_handlers
from ascend_python_common.rate_limit import (
    DEFAULT_STORAGE_URI,
    build_limiter,
    install_rate_limiting,
)
from fastapi import FastAPI, Request, Response
from httpx import ASGITransport, AsyncClient
from limits.storage import MemoryStorage, RedisStorage
from slowapi import Limiter
from slowapi.util import get_remote_address

from src.api.middleware import rate_limit as rate_limit_module
from src.config.config import Settings
from src.config.config import settings as service_settings
from src.main import create_app


def test_redis_url_default_is_loopback_service(monkeypatch: pytest.MonkeyPatch) -> None:
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
    assert seen["key_prefix"] == "ascend-audio-scribe"
    assert wired_app.state.limiter._key_prefix == "ascend-audio-scribe"
    assert isinstance(wired_app.state.limiter._storage, RedisStorage)


class _RecordingStorage(MemoryStorage):
    def __init__(self) -> None:
        super().__init__()
        self.keys: list[str] = []

    def incr(self, key: str, expiry: float, amount: int = 1) -> int:
        self.keys.append(key)
        return super().incr(key, expiry, amount)


TRANSCRIBE_ROUTES = [
    "src.api.rest.rest_endpoints.transcribe_local_endpoint",
    "src.api.rest.rest_endpoints.transcribe_openai_endpoint",
    "src.api.rest.rest_endpoints.transcribe_hf_endpoint",
    "src.api.rest.rest_endpoints.transcribe_audacity_endpoint",
]


@pytest.mark.parametrize("route_name", TRANSCRIBE_ROUTES)
def test_transcription_routes_are_decorated_with_the_module_limiter(route_name: str) -> None:
    # given
    limiter = rate_limit_module.limiter
    # when
    registered = route_name in limiter._route_limits
    # then
    assert registered


@rate_limit_module.limiter.limit(service_settings.RATE_LIMIT_TRANSCRIBE)
async def _transcribe_probe_endpoint(request: Request, response: Response) -> dict[str, str]:
    assert request.url.path == "/transcribe-probe"
    assert response is not None
    return {"status": "ok"}


def _transcribe_probe_app() -> FastAPI:
    probe = FastAPI()
    install_rate_limiting(probe, rate_limit_module.limiter)
    install_error_handlers(probe, ErrorRegistry())
    probe.get("/transcribe-probe")(_transcribe_probe_endpoint)
    return probe


@pytest.mark.asyncio
async def test_two_apps_on_shared_storage_refuse_transcription_over_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # given
    monkeypatch.setattr(service_settings, "RATE_LIMIT_DEFAULT", "1000/minute")
    monkeypatch.setattr(service_settings, "REDIS_URL", "memory://")
    allowed = int(service_settings.RATE_LIMIT_TRANSCRIBE.split("/")[0])
    storage = _RecordingStorage()
    module_limiter = rate_limit_module.limiter
    original_storage = module_limiter._storage
    original_inner = module_limiter._limiter.storage
    module_limiter._storage = storage
    module_limiter._limiter.storage = storage
    try:
        first_app = _transcribe_probe_app()
        second_app = _transcribe_probe_app()
        first_transport = ASGITransport(app=first_app, raise_app_exceptions=False)
        second_transport = ASGITransport(app=second_app, raise_app_exceptions=False)
        # when
        async with AsyncClient(transport=first_transport, base_url="http://testserver") as first:
            statuses: list[int] = []
            for _ in range(allowed):
                response = await first.get("/transcribe-probe")
                statuses.append(response.status_code)
        async with AsyncClient(transport=second_transport, base_url="http://testserver") as second:
            refused = await second.get("/transcribe-probe")
    finally:
        module_limiter._storage = original_storage
        module_limiter._limiter.storage = original_inner
    # then
    assert all(status == 200 for status in statuses)
    assert refused.status_code == 429
    assert refused.json()["code"] == "rate_limited"
    assert "retry-after" in {key.lower() for key in refused.headers}
    assert len(storage.keys) > 0
    assert all("ascend-audio-scribe" in key for key in storage.keys)

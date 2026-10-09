from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from ascend_python_common.readiness import ProbeResult
from ascend_python_common.uri_guard import HopAnswer, check_fetch_uri, follow_guarded_redirects
from httpx import AsyncClient

from src.api.readiness import probe_searxng
from src.config.config import Settings
from src.config.config import settings as service_settings
from src.config.startup_banner import _probe_url_sync, _redis_check_sync
from src.reader.strategies import curl_cffi_fetcher


@pytest.mark.asyncio
async def test_slow_readiness_probe_reports_error(monkeypatch: pytest.MonkeyPatch) -> None:
    # given
    monkeypatch.setattr(service_settings, "READINESS_PROBE_TIMEOUT_SECONDS", 0.1)
    seen: dict[str, Any] = {}

    def capture_client(**kwargs: Any) -> MagicMock:
        seen.update(kwargs)
        mock_client = MagicMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.get = AsyncMock(side_effect=RuntimeError("timed out after 0.1"))
        return mock_client

    # when
    with patch("src.api.readiness.httpx.AsyncClient", side_effect=capture_client):
        result = await probe_searxng()
    # then
    assert seen["timeout"] == 0.1
    assert result == ProbeResult(status="error")


@pytest.mark.asyncio
async def test_ready_answers_503_when_probe_times_out(client: AsyncClient) -> None:
    # given
    ok_redis = patch("src.api.readiness.probe_redis", new=AsyncMock(return_value=ProbeResult(status="ok")))
    timed_out = patch(
        "src.api.readiness.probe_searxng",
        new=AsyncMock(return_value=ProbeResult(status="error")),
    )
    ok_flare = patch(
        "src.api.readiness.probe_flaresolverr",
        new=AsyncMock(return_value=ProbeResult(status="ok")),
    )
    ok_searxng_breaker = patch(
        "src.api.readiness.probe_searxng_breaker",
        return_value=ProbeResult(status="ok", details={"breaker": "closed"}),
    )
    ok_flare_breaker = patch(
        "src.api.readiness.probe_flaresolverr_breaker",
        return_value=ProbeResult(status="ok", details={"breaker": "closed"}),
    )
    # when
    with ok_redis, timed_out, ok_flare, ok_searxng_breaker, ok_flare_breaker:
        response = await client.get("/ready")
    # then
    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "not-ready"
    assert body["checks"]["searxng"]["status"] == "error"


def test_fetch_max_redirect_hops_default_is_10(monkeypatch: pytest.MonkeyPatch) -> None:
    # given
    monkeypatch.delenv("FETCH_MAX_REDIRECT_HOPS", raising=False)
    # when
    default = Settings().FETCH_MAX_REDIRECT_HOPS
    # then
    assert default == 10


def test_readiness_probe_timeout_default_is_3(monkeypatch: pytest.MonkeyPatch) -> None:
    # given
    monkeypatch.delenv("READINESS_PROBE_TIMEOUT_SECONDS", raising=False)
    # when
    default = Settings().READINESS_PROBE_TIMEOUT_SECONDS
    # then
    assert default == 3.0


def test_startup_probe_timeout_default_is_2(monkeypatch: pytest.MonkeyPatch) -> None:
    # given
    monkeypatch.delenv("STARTUP_PROBE_TIMEOUT_SECONDS", raising=False)
    # when
    default = Settings().STARTUP_PROBE_TIMEOUT_SECONDS
    # then
    assert default == 2.0


def test_banner_url_probe_uses_configured_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    # given
    monkeypatch.setattr(service_settings, "STARTUP_PROBE_TIMEOUT_SECONDS", 7.5)
    seen: dict[str, Any] = {}
    import urllib.request

    real_urlopen = urllib.request.urlopen

    def capture(url: str, timeout: float | None = None) -> Any:
        seen["timeout"] = timeout
        return real_urlopen("http://127.0.0.1:9/", timeout=0.01)

    # when
    with patch("src.config.startup_banner.urllib.request.urlopen", side_effect=capture):
        _probe_url_sync("SearXNG", "http://127.0.0.1:9/healthz")
    # then
    assert seen["timeout"] == 7.5


def test_banner_redis_probe_uses_configured_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    # given
    monkeypatch.setattr(service_settings, "STARTUP_PROBE_TIMEOUT_SECONDS", 7.5)
    monkeypatch.setattr(service_settings, "REDIS_URL", "redis://127.0.0.1:6379/0")
    seen: dict[str, Any] = {}

    def capture(address: tuple[str, int], timeout: float | None = None) -> Any:
        seen["timeout"] = timeout
        raise TimeoutError("too slow")

    # when
    with patch("src.config.startup_banner.socket.create_connection", side_effect=capture):
        _redis_check_sync()
    # then
    assert seen["timeout"] == 7.5


@pytest.mark.asyncio
async def test_curl_cffi_tier_stops_after_second_redirect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # given
    monkeypatch.setattr(service_settings, "FETCH_MAX_REDIRECT_HOPS", 2)
    policy = curl_cffi_fetcher._fetch_policy()
    calls: list[str] = []

    async def send_hop(target: Any) -> HopAnswer[str]:
        calls.append(target.url)
        return HopAnswer(status=302, location="/next", answer="hop")

    first = await check_fetch_uri("http://93.184.216.34/start", policy)
    # when
    final = await follow_guarded_redirects(first, policy, send_hop)
    # then
    assert policy.max_redirect_hops == 2
    assert len(calls) == 3
    assert final.status == 302

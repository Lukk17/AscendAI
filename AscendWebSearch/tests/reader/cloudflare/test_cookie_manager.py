from unittest.mock import AsyncMock, patch

import pytest

from src.reader.cloudflare.cookie_manager import CookieManager


def _fresh_manager() -> CookieManager:
    CookieManager._instance = None
    manager = CookieManager()
    manager._memory_store = {}
    manager.redis_client = None

    return manager


@pytest.mark.asyncio
async def test_cookie_manager_save_and_get_via_memory():
    manager = _fresh_manager()
    url = "https://www.linkedin.com/jobs"
    await manager.save_session_data(url, {"cf_clearance": "abc"}, "UA")

    data = await manager.get_session_data("https://login.linkedin.com/uas")
    assert data is not None
    assert data["cookies"]["cf_clearance"] == "abc"


@pytest.mark.asyncio
async def test_apex_extraction_treats_cctlds_separately():
    manager = _fresh_manager()
    await manager.save_session_data("https://attacker.co.uk/path", {"k": "atk"}, "UA")
    await manager.save_session_data("https://victim.co.uk/path", {"k": "vct"}, "UA")

    victim = await manager.get_session_data("https://victim.co.uk/x")
    attacker = await manager.get_session_data("https://attacker.co.uk/x")
    assert victim is not None
    assert attacker is not None
    assert victim["cookies"]["k"] == "vct"
    assert attacker["cookies"]["k"] == "atk"


@pytest.mark.asyncio
async def test_get_domain_strips_subdomain_and_port():
    manager = _fresh_manager()
    await manager.save_session_data("https://www.example.com:8443/path", {"k": "v"}, "UA")

    data = await manager.get_session_data("https://api.example.com/x")
    assert data is not None
    assert data["cookies"]["k"] == "v"


@pytest.mark.asyncio
async def test_redis_get_returns_parsed_payload():
    manager = _fresh_manager()
    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value='{"cookies": {"cf_clearance": "z"}, "user_agent": "UA"}')
    manager.redis_client = mock_redis

    data = await manager.get_session_data("https://example.com")
    assert data is not None
    assert data["cookies"]["cf_clearance"] == "z"


@pytest.mark.asyncio
async def test_redis_get_miss_falls_through_to_memory():
    manager = _fresh_manager()
    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value=None)
    manager.redis_client = mock_redis
    manager._memory_store["example.com"] = {"cookies": {"k": "m"}, "user_agent": "UA"}

    data = await manager.get_session_data("https://example.com")
    assert data is not None
    assert data["cookies"]["k"] == "m"


@pytest.mark.asyncio
async def test_redis_get_error_falls_back_to_memory():
    manager = _fresh_manager()
    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(side_effect=RuntimeError("down"))
    manager.redis_client = mock_redis
    manager._memory_store["example.com"] = {"cookies": {"k": "m"}, "user_agent": "UA"}

    data = await manager.get_session_data("https://example.com")
    assert data is not None
    assert data["cookies"]["k"] == "m"


@pytest.mark.asyncio
async def test_save_via_redis_success():
    manager = _fresh_manager()
    mock_redis = AsyncMock()
    mock_redis.setex = AsyncMock()
    manager.redis_client = mock_redis

    await manager.save_session_data("https://example.com", {"k": "v"}, "UA")
    mock_redis.setex.assert_awaited_once()


@pytest.mark.asyncio
async def test_save_via_redis_error_falls_back_to_memory():
    manager = _fresh_manager()
    mock_redis = AsyncMock()
    mock_redis.setex = AsyncMock(side_effect=RuntimeError("down"))
    manager.redis_client = mock_redis

    await manager.save_session_data("https://example.com", {"k": "v"}, "UA")
    assert manager._memory_store["example.com"]["cookies"]["k"] == "v"


@pytest.mark.asyncio
async def test_init_with_no_redis_url_leaves_client_none():
    CookieManager._instance = None
    with patch("src.reader.cloudflare.cookie_manager.settings.REDIS_URL", ""):
        manager = CookieManager()
    assert manager.redis_client is None


@pytest.mark.asyncio
async def test_init_with_redis_failure_keeps_initialized():
    CookieManager._instance = None
    with patch(
        "src.reader.cloudflare.cookie_manager.redis.from_url",
        side_effect=RuntimeError("nope"),
    ):
        manager = CookieManager()
    assert manager._initialized is True


@pytest.mark.asyncio
async def test_init_reentry_returns_existing_singleton():
    manager_a = _fresh_manager()
    manager_b = CookieManager()
    assert manager_a is manager_b


@pytest.mark.asyncio
async def test_get_domain_handles_bare_host_without_scheme():
    manager = _fresh_manager()
    manager._memory_store["example.com"] = {"cookies": {"k": "v"}, "user_agent": "UA"}
    data = await manager.get_session_data("example.com/path")
    assert data is not None
    assert data["cookies"]["k"] == "v"


@pytest.mark.asyncio
async def test_get_domain_returns_empty_for_empty_url():
    manager = _fresh_manager()
    manager._memory_store[""] = {"cookies": {"k": "v"}, "user_agent": "UA"}
    data = await manager.get_session_data("")
    assert data is not None
    assert data["cookies"]["k"] == "v"


@pytest.mark.asyncio
async def test_get_domain_returns_host_when_no_psl_suffix():
    """tldextract cannot recognise non-PSL hosts (intranet, localhost). The fallback
    is to keep the host as-is so internal addresses still get a unique key."""
    manager = _fresh_manager()
    manager._memory_store["intranet-host"] = {"cookies": {"k": "v"}, "user_agent": "UA"}
    data = await manager.get_session_data("http://intranet-host/path")
    assert data is not None
    assert data["cookies"]["k"] == "v"


@pytest.mark.asyncio
async def test_schemeless_url_resolves_to_same_apex_as_scheme_qualified():
    """Security: `evil.com/path` (no scheme) must produce the same key as
    `https://evil.com/path` — otherwise an attacker can poison a parallel bucket
    with a literal `evil.com/path` key that the legitimate `evil.com` lookup
    will never read back, creating a confused-deputy."""
    manager = _fresh_manager()
    await manager.save_session_data("https://evil.com/path", {"k": "v"}, "UA")
    data = await manager.get_session_data("evil.com/other")
    assert data is not None
    assert data["cookies"]["k"] == "v"

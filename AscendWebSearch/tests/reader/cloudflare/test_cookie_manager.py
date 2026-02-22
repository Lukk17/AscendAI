from unittest.mock import AsyncMock

import pytest

from src.reader.cloudflare.cookie_manager import CookieManager


@pytest.fixture
def clean_cookie_manager():
    # Force initialize a fresh instance for testing
    CookieManager._instance = None
    manager = CookieManager()
    manager._memory_store = {}
    return manager


@pytest.mark.asyncio
async def test_cookie_manager_memory_fallback(clean_cookie_manager):
    clean_cookie_manager.redis_client = None

    url = "https://example.com/path"
    cookies = {"cf_clearance": "abc1234"}
    user_agent = "Mozilla/5.0"

    await clean_cookie_manager.save_clearance_data(url, cookies, user_agent)
    data = await clean_cookie_manager.get_clearance_data("https://example.com/other")

    assert data is not None
    assert data["cookies"]["cf_clearance"] == "abc1234"
    assert data["user_agent"] == "Mozilla/5.0"


@pytest.mark.asyncio
async def test_cookie_manager_redis_success(clean_cookie_manager):
    url = "https://example.com/path"
    cookies = {"cf_clearance": "abc1234"}
    user_agent = "Mozilla/5.0"

    mock_redis = AsyncMock()
    clean_cookie_manager.redis_client = mock_redis

    await clean_cookie_manager.save_clearance_data(url, cookies, user_agent)
    mock_redis.setex.assert_called_once()

    # Mock retrieval
    mock_redis.get.return_value = '{"cookies": {"cf_clearance": "abc1234"}, "user_agent": "Mozilla/5.0"}'

    data = await clean_cookie_manager.get_clearance_data(url)
    assert data is not None
    assert data["cookies"]["cf_clearance"] == "abc1234"
    assert data["user_agent"] == "Mozilla/5.0"
    mock_redis.get.assert_called_once()

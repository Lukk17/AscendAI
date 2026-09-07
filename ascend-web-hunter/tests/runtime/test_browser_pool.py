from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.runtime.browser_pool import BrowserPool


def _make_playwright_factory(mock_browser):
    pw = MagicMock()
    pw.stop = AsyncMock()
    pw.chromium.launch = AsyncMock(return_value=mock_browser)
    pw_starter = AsyncMock(return_value=pw)
    factory = MagicMock()
    factory.start = pw_starter

    return factory, pw


@pytest.mark.asyncio
async def test_start_launches_chromium_once():
    browser = MagicMock()
    browser.is_connected = MagicMock(return_value=True)
    browser.close = AsyncMock()
    factory, pw = _make_playwright_factory(browser)

    pool = BrowserPool()
    with patch("src.runtime.browser_pool.async_playwright", return_value=factory):
        await pool.start()
        await pool.start()  # second call short-circuits
    assert pw.chromium.launch.await_count == 1


@pytest.mark.asyncio
async def test_get_browser_returns_existing_when_connected():
    browser = MagicMock()
    browser.is_connected = MagicMock(return_value=True)
    browser.close = AsyncMock()
    factory, _ = _make_playwright_factory(browser)

    pool = BrowserPool()
    with patch("src.runtime.browser_pool.async_playwright", return_value=factory):
        await pool.start()
        returned = await pool.get_browser()
    assert returned is browser


@pytest.mark.asyncio
async def test_get_browser_relaunches_when_disconnected():
    disconnected = MagicMock()
    disconnected.is_connected = MagicMock(return_value=False)
    disconnected.close = AsyncMock()
    fresh = MagicMock()
    fresh.is_connected = MagicMock(return_value=True)
    fresh.close = AsyncMock()
    factory1, _pw1 = _make_playwright_factory(disconnected)
    factory2, _pw2 = _make_playwright_factory(fresh)

    pool = BrowserPool()
    with patch("src.runtime.browser_pool.async_playwright", return_value=factory1):
        await pool.start()
    # Replace the global on second relaunch
    with patch("src.runtime.browser_pool.async_playwright", return_value=factory2):
        returned = await pool.get_browser()
    assert returned is fresh


@pytest.mark.asyncio
async def test_get_browser_relaunches_when_browser_is_none():
    fresh = MagicMock()
    fresh.is_connected = MagicMock(return_value=True)
    fresh.close = AsyncMock()
    factory, _ = _make_playwright_factory(fresh)

    pool = BrowserPool()
    with patch("src.runtime.browser_pool.async_playwright", return_value=factory):
        returned = await pool.get_browser()
    assert returned is fresh


@pytest.mark.asyncio
async def test_stop_is_noop_when_never_started():
    pool = BrowserPool()
    await pool.stop()


@pytest.mark.asyncio
async def test_stop_closes_browser_and_playwright():
    browser = MagicMock()
    browser.is_connected = MagicMock(return_value=True)
    browser.close = AsyncMock()
    factory, pw = _make_playwright_factory(browser)

    pool = BrowserPool()
    with patch("src.runtime.browser_pool.async_playwright", return_value=factory):
        await pool.start()
    await pool.stop()
    browser.close.assert_awaited()
    pw.stop.assert_awaited()


@pytest.mark.asyncio
async def test_stop_tolerates_browser_close_error():
    browser = MagicMock()
    browser.is_connected = MagicMock(return_value=True)
    browser.close = AsyncMock(side_effect=RuntimeError("close failed"))
    factory, pw = _make_playwright_factory(browser)
    pw.stop = AsyncMock(side_effect=RuntimeError("stop failed"))

    pool = BrowserPool()
    with patch("src.runtime.browser_pool.async_playwright", return_value=factory):
        await pool.start()
    await pool.stop()  # must not raise


@pytest.mark.asyncio
async def test_relaunch_tolerates_prior_playwright_stop_failure():
    """When a relaunch happens, the prior playwright instance is stopped. If that
    stop raises, the relaunch must still succeed."""
    first_browser = MagicMock()
    first_browser.is_connected = MagicMock(return_value=False)
    first_browser.close = AsyncMock()
    second_browser = MagicMock()
    second_browser.is_connected = MagicMock(return_value=True)
    second_browser.close = AsyncMock()

    first_pw = MagicMock()
    first_pw.stop = AsyncMock(side_effect=RuntimeError("stop failed"))
    first_pw.chromium.launch = AsyncMock(return_value=first_browser)
    second_pw = MagicMock()
    second_pw.stop = AsyncMock()
    second_pw.chromium.launch = AsyncMock(return_value=second_browser)

    first_factory = MagicMock()
    first_factory.start = AsyncMock(return_value=first_pw)
    second_factory = MagicMock()
    second_factory.start = AsyncMock(return_value=second_pw)

    pool = BrowserPool()
    with patch("src.runtime.browser_pool.async_playwright", return_value=first_factory):
        await pool.start()
    with patch("src.runtime.browser_pool.async_playwright", return_value=second_factory):
        returned = await pool.get_browser()
    assert returned is second_browser


@pytest.mark.asyncio
async def test_get_browser_double_check_inside_lock():
    """First caller acquires the lock and relaunches; the second caller (also
    inside the lock) sees a now-connected browser and short-circuits without
    calling _launch_locked. We simulate this by populating self._browser inside
    a custom lock's __aenter__."""
    pool = BrowserPool()

    connected_after_lock = MagicMock()
    connected_after_lock.is_connected = MagicMock(return_value=True)

    class _SeedingLock:
        async def __aenter__(self):
            pool._browser = connected_after_lock
            return

        async def __aexit__(self, exc_type, exc, tb):
            return False

    pool._lock = _SeedingLock()
    pool._browser = None  # outer check fails → fall through to lock
    result = await pool.get_browser()
    assert result is connected_after_lock

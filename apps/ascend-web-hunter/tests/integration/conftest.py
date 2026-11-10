"""Fixtures every live-browser integration test shares."""

from collections.abc import AsyncIterator

import pytest


@pytest.fixture(autouse=True)
def _reset_crawlee_globals() -> None:
    """Crawlee's global service locator caches a storage client and an event
    manager bound to the first test's event loop; a later test reusing them
    fails with "bound to a different event loop". Drop the cached instances so
    each test builds its own. (conftest's function-scoped async fixture keeps
    every test on its own loop, so sharing is not an option.)"""
    from crawlee import service_locator

    service_locator._storage_client = None
    service_locator._event_manager = None
    service_locator._configuration = None


@pytest.fixture
def stub_page_measure() -> None:
    """A real page is measured for real, in place of the unit-suite stub."""


@pytest.fixture(autouse=True)
async def _real_browser_pool(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[None]:
    """Undo the unit-suite browser-pool and tunnel stubs: these tests drive the real browsers.

    The stubbed `stop` is a no-op, so close the real browser after each test
    through the real `stop`, or leaked driver sockets fail the suite.
    """
    from src.reader.browser_guard import browser_tunnel
    from src.runtime.browser_pool import BrowserPool, browser_pool

    monkeypatch.setattr(
        browser_pool, "get_browser", BrowserPool.get_browser.__get__(browser_pool, BrowserPool)
    )
    monkeypatch.setattr(browser_tunnel, "_port", None)
    monkeypatch.delattr(browser_tunnel, "chained_proxy")
    await browser_tunnel.start()
    yield
    await BrowserPool.stop(browser_pool)
    await browser_tunnel.stop()

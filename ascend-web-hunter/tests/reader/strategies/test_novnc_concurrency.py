"""Integration-level proof that two NoVNC intervention flows in flight at
once do not collide: the second is rejected immediately, and once the first
finishes and releases the shared lock, a new flow proceeds normally."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.api.exceptions import HumanInterventionRequiredException, NoVNCFlowBusyException
from src.config.config import settings
from src.reader.strategies.novnc_strategy import (
    _NOVNC_LOCK_LEASE_GRACE_SECONDS,
    NoVNCStrategy,
    _novnc_flow_lock,
)


def _build_playwright_factory():
    """A captcha-branch Playwright double whose page never looks solved, so
    the monitor runs out its (short, patched) NOVNC_TIMEOUT_SECONDS and exits
    through the ordinary timeout path -- exercising the same finally/release
    every real flow goes through, without launching a real browser."""
    page = MagicMock()
    page.goto = AsyncMock()
    page.content = AsyncMock(return_value="<html><body>ordinary page</body></html>")
    page.evaluate = AsyncMock(return_value="UA")
    context = MagicMock()
    context.storage_state = AsyncMock(return_value={"cookies": [], "origins": []})
    context.new_page = AsyncMock(return_value=page)
    browser = MagicMock()
    browser.new_context = AsyncMock(return_value=context)
    browser.close = AsyncMock()
    pw = MagicMock()
    pw.chromium.launch = AsyncMock(return_value=browser)
    factory = MagicMock()
    factory.__aenter__ = AsyncMock(return_value=pw)
    factory.__aexit__ = AsyncMock(return_value=False)

    return factory


@pytest.fixture(autouse=True)
def _reset_novnc_flow_lock():
    _novnc_flow_lock.release(_novnc_flow_lock._holder_url, _novnc_flow_lock._holder_profile)
    yield
    _novnc_flow_lock.release(_novnc_flow_lock._holder_url, _novnc_flow_lock._holder_profile)


@pytest.mark.asyncio
async def test_second_concurrent_flow_is_rejected_then_a_new_flow_succeeds_after_release():
    factory = _build_playwright_factory()

    with (
        patch("src.reader.strategies.novnc_strategy.settings.PUBLIC_VNC_URL", "http://vnc"),
        patch("src.reader.strategies.novnc_strategy.async_playwright", return_value=factory),
        patch("src.reader.strategies.novnc_strategy.settings.NOVNC_TIMEOUT_SECONDS", 0.2),
        patch("src.reader.strategies.novnc_strategy.settings.NOVNC_COOKIE_SYNC_POLL_SECONDS", 0.05),
    ):
        first = NoVNCStrategy("default")
        with pytest.raises(HumanInterventionRequiredException):
            await first.get_html("http://site-a.example")

        # The first flow's background monitor is now in flight, holding the
        # shared browser/display/CDP port -- a second caller, even for a
        # different site, must be rejected immediately, not queued or
        # silently collided with.
        second = NoVNCStrategy("default")
        with pytest.raises(NoVNCFlowBusyException) as exc:
            await second.get_html("http://site-b.example")
        assert exc.value.holder_url == "http://site-a.example"
        assert exc.value.holder_profile == "default"

        # Give the background monitor time to run out its (patched, short)
        # timeout and release the lock in its finally block.
        await asyncio.sleep(0.4)

        third = NoVNCStrategy("default")
        with pytest.raises(HumanInterventionRequiredException):
            await third.get_html("http://site-c.example")


@pytest.mark.asyncio
async def test_leaked_lock_self_heals_after_its_lease_expires():
    """A flow that wedges and never reaches its finally block (a hung
    browser subprocess, no exception raised) must not make the endpoint
    permanently unavailable: once the lease elapses, a new flow proceeds."""
    hang_forever = asyncio.Event()

    async def wedged_monitor(url, intervention_type, profile=None):
        await hang_forever.wait()  # never completes; finally/release never runs

    with (
        patch("src.reader.strategies.novnc_strategy.settings.PUBLIC_VNC_URL", "http://vnc"),
        patch("src.reader.strategies.novnc_strategy._monitor_for_cookies", side_effect=wedged_monitor),
    ):
        wedged = NoVNCStrategy("default")
        with pytest.raises(HumanInterventionRequiredException):
            await wedged.get_html("http://wedged-site.example")

        # A second caller is correctly rejected while the wedged flow holds the lock.
        blocked = NoVNCStrategy("default")
        with pytest.raises(NoVNCFlowBusyException):
            await blocked.get_html("http://someone-else.example")

        # Simulate the lease elapsing without waiting NOVNC_TIMEOUT_SECONDS in real time.
        _novnc_flow_lock._acquired_at -= settings.NOVNC_TIMEOUT_SECONDS + _NOVNC_LOCK_LEASE_GRACE_SECONDS + 1

        recovered = NoVNCStrategy("default")
        with pytest.raises(HumanInterventionRequiredException):
            await recovered.get_html("http://recovered-site.example")

    # Let the two wedged monitor tasks (from `wedged` and `recovered`) exit
    # cleanly instead of leaking pending tasks past the end of the test.
    hang_forever.set()
    await asyncio.sleep(0)

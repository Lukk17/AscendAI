"""Tests for NoVNC monitor using context.storage_state() (task 1.5)."""

import contextlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.reader.cloudflare.cookie_manager import PRODUCED_BY_NOVNC


@pytest.mark.asyncio
async def test_novnc_monitor_saves_storage_state_not_cookies():
    """
    The background monitor must call save_storage_state (not save_session_data/cookies).
    We verify by checking that save_storage_state is awaited and that context.storage_state()
    is called instead of context.cookies().
    """
    from src.reader.strategies import novnc_strategy as ns

    mock_storage_state = {"cookies": [{"name": "li_at", "value": "TOKEN"}], "origins": []}

    page = MagicMock()
    page.goto = AsyncMock()
    page.evaluate = AsyncMock(return_value="Mozilla/5.0")
    page.url = "https://linkedin.com/feed"

    context = MagicMock()
    context.new_page = AsyncMock(return_value=page)
    context.storage_state = AsyncMock(return_value=mock_storage_state)
    # cookies() should NOT be called
    context.cookies = AsyncMock(side_effect=AssertionError("cookies() must not be called"))

    browser = MagicMock()
    browser.new_context = AsyncMock(return_value=context)
    browser.close = AsyncMock()

    mock_p = MagicMock()
    mock_p.__aenter__ = AsyncMock(return_value=mock_p)
    mock_p.__aexit__ = AsyncMock(return_value=False)
    mock_p.chromium.launch = AsyncMock(return_value=browser)

    with (
        patch("src.reader.strategies.novnc_strategy.async_playwright", return_value=mock_p),
        patch(
            "src.reader.strategies.novnc_strategy.cookie_manager.save_storage_state",
            new=AsyncMock(),
        ) as mock_save,
        patch("src.reader.strategies.novnc_strategy.settings.NOVNC_TIMEOUT_SECONDS", 1),
        patch(
            "src.reader.strategies.novnc_strategy.ChallengeDetector.is_login_redirect_url",
            return_value=True,
        ),
        patch("asyncio.sleep", new=AsyncMock(side_effect=StopAsyncIteration)),
    ):
        with contextlib.suppress(StopAsyncIteration):
            await ns._monitor_for_cookies("https://linkedin.com/login", "login")

    mock_save.assert_awaited()
    # Confirm storage_state was called, not cookies
    context.storage_state.assert_awaited()
    assert mock_save.call_args.args[-1] == PRODUCED_BY_NOVNC


@pytest.mark.asyncio
async def test_novnc_captcha_monitor_saves_once_when_clearance_appears():
    """The captcha monitor must persist the session only after a cf_clearance cookie
    appears, then stop — never overwrite a good clearance on later polls."""
    from src.reader.strategies import novnc_strategy as ns

    page = MagicMock()
    page.goto = AsyncMock()
    page.evaluate = AsyncMock(return_value="Mozilla/5.0")
    page.url = "https://nowsecure.nl/"
    # Page stays a challenge wall throughout, so cf_clearance (not "cleared") is the trigger.
    page.content = AsyncMock(return_value="<html><title>Just a moment...</title></html>")

    context = MagicMock()
    context.new_page = AsyncMock(return_value=page)
    # First poll: still challenged (no clearance). Second poll: clearance issued.
    context.storage_state = AsyncMock(
        side_effect=[
            {"cookies": [{"name": "__cf_bm", "value": "x"}], "origins": []},
            {"cookies": [{"name": "cf_clearance", "value": "GRANTED"}], "origins": []},
        ]
    )

    browser = MagicMock()
    browser.new_context = AsyncMock(return_value=context)
    browser.close = AsyncMock()

    mock_p = MagicMock()
    mock_p.__aenter__ = AsyncMock(return_value=mock_p)
    mock_p.__aexit__ = AsyncMock(return_value=False)
    mock_p.chromium.launch = AsyncMock(return_value=browser)

    with (
        patch("src.reader.strategies.novnc_strategy.async_playwright", return_value=mock_p),
        patch(
            "src.reader.strategies.novnc_strategy.cookie_manager.save_storage_state",
            new=AsyncMock(),
        ) as mock_save,
        patch("src.reader.strategies.novnc_strategy.settings.NOVNC_TIMEOUT_SECONDS", 60),
        patch("src.reader.strategies.novnc_strategy.asyncio.sleep", new=AsyncMock()),
    ):
        await ns._monitor_for_cookies("https://nowsecure.nl/", "captcha")

    # Saved exactly once — on the poll where cf_clearance appeared — then broke out.
    mock_save.assert_awaited_once()
    saved_state = mock_save.await_args.args[1]
    assert any(c["name"] == "cf_clearance" for c in saved_state["cookies"])
    assert mock_save.await_args.args[-1] == PRODUCED_BY_NOVNC


@pytest.mark.asyncio
async def test_novnc_captcha_monitor_rejects_allegro_style_block_never_writes_session():
    """The reported bug: an Allegro-style DataDome block page (no cf_clearance,
    no literal 'datadome' string) must never be declared cleared, and no
    session may be written for it."""
    from src.reader.strategies import novnc_strategy as ns

    page = MagicMock()
    page.goto = AsyncMock()
    page.evaluate = AsyncMock(return_value="Mozilla/5.0")
    page.url = "https://allegro.pl/oferta/example"
    page.content = AsyncMock(
        return_value=(
            "<html><body><p id='cmsg'>Please enable JS and disable any ad blocker</p>"
            "<script>var dd={'host':'geo.captcha-delivery.com'}</script></body></html>"
        )
    )

    context = MagicMock()
    context.new_page = AsyncMock(return_value=page)
    context.storage_state = AsyncMock(return_value={"cookies": [], "origins": []})

    browser = MagicMock()
    browser.new_context = AsyncMock(return_value=context)
    browser.close = AsyncMock()

    mock_p = MagicMock()
    mock_p.__aenter__ = AsyncMock(return_value=mock_p)
    mock_p.__aexit__ = AsyncMock(return_value=False)
    mock_p.chromium.launch = AsyncMock(return_value=browser)

    with (
        patch("src.reader.strategies.novnc_strategy.async_playwright", return_value=mock_p),
        patch(
            "src.reader.strategies.novnc_strategy.cookie_manager.save_storage_state",
            new=AsyncMock(),
        ) as mock_save,
        patch("src.reader.strategies.novnc_strategy.settings.NOVNC_TIMEOUT_SECONDS", 0),
    ):
        await ns._monitor_for_cookies("https://allegro.pl/oferta/example", "captcha")

    mock_save.assert_not_awaited()


@pytest.mark.asyncio
async def test_novnc_captcha_monitor_writes_session_for_never_challenged_page():
    """establish() is the proactive counterpart to passive capture: a call
    against an ordinary page that already shows real content on the very
    first poll, with no block ever observed, must still persist a session
    record on that first poll -- not only once a captcha is solved. See
    e2e/testing/10-session-establish-test.md, "Two behaviours this spec
    found live, not assumed"."""
    from src.reader.strategies import novnc_strategy as ns

    page = MagicMock()
    page.goto = AsyncMock()
    page.evaluate = AsyncMock(return_value="Mozilla/5.0")
    page.url = "https://ordinary-site.example/"
    page.content = AsyncMock(return_value="<html><body>" + "genuine article text " * 50 + "</body></html>")

    context = MagicMock()
    context.new_page = AsyncMock(return_value=page)
    context.storage_state = AsyncMock(return_value={"cookies": [], "origins": []})

    browser = MagicMock()
    browser.new_context = AsyncMock(return_value=context)
    browser.close = AsyncMock()

    mock_p = MagicMock()
    mock_p.__aenter__ = AsyncMock(return_value=mock_p)
    mock_p.__aexit__ = AsyncMock(return_value=False)
    mock_p.chromium.launch = AsyncMock(return_value=browser)

    with (
        patch("src.reader.strategies.novnc_strategy.async_playwright", return_value=mock_p),
        patch(
            "src.reader.strategies.novnc_strategy.cookie_manager.save_storage_state",
            new=AsyncMock(),
        ) as mock_save,
        patch("src.reader.strategies.novnc_strategy.settings.NOVNC_TIMEOUT_SECONDS", 60),
    ):
        await ns._monitor_for_cookies("https://ordinary-site.example/", "captcha")

    mock_save.assert_awaited_once()


@pytest.mark.asyncio
async def test_novnc_captcha_monitor_saves_when_wall_clears_without_cf_clearance():
    """For non-Cloudflare captchas (e.g. DataDome) there is no cf_clearance cookie; the
    monitor must capture once the challenge wall is gone."""
    from src.reader.strategies import novnc_strategy as ns

    page = MagicMock()
    page.goto = AsyncMock()
    page.evaluate = AsyncMock(return_value="Mozilla/5.0")
    page.url = "https://www.indeed.com/jobs"
    # First poll: still on the DataDome wall. Second poll: the real page (no block markers).
    page.content = AsyncMock(
        side_effect=[
            "<html><body>Pardon Our Interruption datadome</body></html>",
            "<html><body>" + "real job listings " * 50 + "</body></html>",
        ]
    )

    context = MagicMock()
    context.new_page = AsyncMock(return_value=page)
    context.storage_state = AsyncMock(
        return_value={"cookies": [{"name": "datadome", "value": "SOLVED"}], "origins": []}
    )

    browser = MagicMock()
    browser.new_context = AsyncMock(return_value=context)
    browser.close = AsyncMock()

    mock_p = MagicMock()
    mock_p.__aenter__ = AsyncMock(return_value=mock_p)
    mock_p.__aexit__ = AsyncMock(return_value=False)
    mock_p.chromium.launch = AsyncMock(return_value=browser)

    with (
        patch("src.reader.strategies.novnc_strategy.async_playwright", return_value=mock_p),
        patch(
            "src.reader.strategies.novnc_strategy.cookie_manager.save_storage_state",
            new=AsyncMock(),
        ) as mock_save,
        patch("src.reader.strategies.novnc_strategy.settings.NOVNC_TIMEOUT_SECONDS", 60),
        patch("src.reader.strategies.novnc_strategy.asyncio.sleep", new=AsyncMock()),
    ):
        await ns._monitor_for_cookies("https://www.indeed.com/jobs", "captcha")

    mock_save.assert_awaited_once()
    saved_state = mock_save.await_args.args[1]
    assert any(c["name"] == "datadome" for c in saved_state["cookies"])

"""Tests for what the NoVNC monitor polls and saves (task 1.5)."""

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.config.config import settings
from src.reader.cloudflare.challenge_signals import ChallengeVerdict
from src.reader.cloudflare.cookie_manager import PRODUCED_BY_NOVNC
from src.reader.novnc.flow_registry import NoVNCFlow, flow_key_for
from src.reader.novnc.window_layout import rect_for_slot
from src.reader.strategies.main_frame_response import MainFrameResponses


def _verdict(*, wall: bool, accepted: bool) -> ChallengeVerdict:
    return ChallengeVerdict(
        score=200 if wall else 0,
        threshold=100,
        signals=(),
        vendor=None,
        wall=wall,
        has_content=accepted,
        intervention_type="captcha",
    )


def _make_flow(url: str, intervention_type: str, profile: str = "default") -> NoVNCFlow:
    window = rect_for_slot(
        0,
        settings.NOVNC_DISPLAY_SIZE,
        (settings.NOVNC_WINDOW_WIDTH_PX, settings.NOVNC_WINDOW_HEIGHT_PX),
        settings.NOVNC_WINDOW_CASCADE_OFFSET_PX,
    )

    return NoVNCFlow(
        flow_id="c3d4e5f6a7b8",
        key=flow_key_for(url, profile),
        url=url,
        profile=profile,
        intervention_type=intervention_type,
        window=window,
        vnc_url="http://vnc/vnc.html?autoconnect=true",
        started_at=time.time(),
        request_id="test-request",
        lease_started=time.monotonic(),
    )


@pytest.mark.asyncio
async def test_novnc_monitor_saves_the_whole_storage_state() -> None:
    """The background monitor polls cookies and saves the result of context.storage_state()."""
    # given
    from src.reader.strategies import novnc_strategy as ns

    mock_storage_state = {
        "cookies": [{"name": "li_at", "value": "TOKEN", "domain": ".www.linkedin.com"}],
        "origins": [],
    }

    page = MagicMock()
    page.goto = AsyncMock(return_value=None)
    page.evaluate = AsyncMock(return_value="Mozilla/5.0")
    page.url = "https://linkedin.com/feed"
    page.content = AsyncMock(return_value="<html><body>feed</body></html>")
    page.locator = MagicMock(return_value=MagicMock(count=AsyncMock(return_value=0)))

    context = MagicMock()
    context.route = AsyncMock()
    context.route_web_socket = None
    context.new_page = AsyncMock(return_value=page)
    context.storage_state = AsyncMock(side_effect=[{"cookies": [], "origins": []}, mock_storage_state])
    context.cookies = AsyncMock(side_effect=[[], mock_storage_state["cookies"]])

    browser = MagicMock()
    browser.new_context = AsyncMock(return_value=context)
    browser.close = AsyncMock()

    mock_p = MagicMock()
    mock_p.__aenter__ = AsyncMock(return_value=mock_p)
    mock_p.__aexit__ = AsyncMock(return_value=False)
    mock_p.chromium.launch = AsyncMock(return_value=browser)

    # when
    with (
        patch("src.reader.strategies.novnc_strategy.async_playwright", return_value=mock_p),
        patch(
            "src.reader.strategies.novnc_strategy.cookie_manager.save_storage_state",
            new=AsyncMock(),
        ) as mock_save,
        patch("src.reader.strategies.novnc_strategy.settings.NOVNC_TIMEOUT_SECONDS", 1),
        patch(
            "src.reader.strategies.novnc_strategy.ChallengeDetector.is_login_redirect_url",
            side_effect=[True, False],
        ),
        patch("asyncio.sleep", new=AsyncMock()),
    ):
        await ns._monitor_for_cookies(_make_flow("https://linkedin.com/login", "login"))

    # then
    mock_save.assert_awaited()
    assert mock_save.call_args.args[1] == mock_storage_state
    assert mock_save.call_args.args[-1] == PRODUCED_BY_NOVNC


@pytest.mark.asyncio
async def test_novnc_captcha_monitor_saves_nothing_when_clearance_appears_on_a_wall() -> None:
    """Cloudflare can set cf_clearance while the page is still its challenge, and
    that cookie opens nothing, so the window stays open and saves no session."""
    # given
    from src.reader.strategies import novnc_strategy as ns

    page = MagicMock()
    page.goto = AsyncMock(return_value=None)
    page.evaluate = AsyncMock(return_value="Mozilla/5.0")
    page.url = "https://nowsecure.nl/"
    page.content = AsyncMock(return_value="<html><title>Just a moment...</title></html>")

    context = MagicMock()
    context.route = AsyncMock()
    context.route_web_socket = None
    context.new_page = AsyncMock(return_value=page)
    cleared_cookies = [{"name": "cf_clearance", "value": "GRANTED", "domain": ".nowsecure.nl"}]
    context.cookies = AsyncMock(return_value=cleared_cookies)
    context.storage_state = AsyncMock(return_value={"cookies": cleared_cookies, "origins": []})

    browser = MagicMock()
    browser.new_context = AsyncMock(return_value=context)
    browser.close = AsyncMock()

    mock_p = MagicMock()
    mock_p.__aenter__ = AsyncMock(return_value=mock_p)
    mock_p.__aexit__ = AsyncMock(return_value=False)
    mock_p.chromium.launch = AsyncMock(return_value=browser)

    # when
    with (
        patch("src.reader.strategies.novnc_strategy.async_playwright", return_value=mock_p),
        patch(
            "src.reader.strategies.novnc_strategy.cookie_manager.save_storage_state",
            new=AsyncMock(),
        ) as mock_save,
        patch("src.reader.strategies.novnc_strategy.settings.NOVNC_TIMEOUT_SECONDS", 0.05),
        patch("src.reader.strategies.novnc_strategy.settings.NOVNC_COOKIE_SYNC_POLL_SECONDS", 0.01),
        patch(
            "src.reader.strategies.novnc_strategy.assess",
            return_value=_verdict(wall=True, accepted=False),
        ),
    ):
        await ns._monitor_for_cookies(_make_flow("https://nowsecure.nl/", "captcha"))

    # then
    assert page.content.await_count >= 2
    mock_save.assert_not_awaited()


@pytest.mark.asyncio
async def test_novnc_captcha_monitor_rejects_allegro_style_block_never_writes_session() -> None:
    """The reported bug: an Allegro-style DataDome block page (no cf_clearance,
    no literal 'datadome' string) must never be declared cleared, and no
    session may be written for it."""
    # given
    from src.reader.strategies import novnc_strategy as ns

    page = MagicMock()
    page.goto = AsyncMock(return_value=None)
    page.evaluate = AsyncMock(return_value="Mozilla/5.0")
    page.url = "https://allegro.pl/oferta/example"
    page.content = AsyncMock(
        return_value=(
            "<html><body><p id='cmsg'>Please enable JS and disable any ad blocker</p>"
            "<script>var dd={'host':'geo.captcha-delivery.com'}</script></body></html>"
        )
    )

    context = MagicMock()
    context.route = AsyncMock()
    context.route_web_socket = None
    context.new_page = AsyncMock(return_value=page)
    context.storage_state = AsyncMock(return_value={"cookies": [], "origins": []})
    context.cookies = AsyncMock(return_value=context.storage_state.return_value["cookies"])

    browser = MagicMock()
    browser.new_context = AsyncMock(return_value=context)
    browser.close = AsyncMock()

    mock_p = MagicMock()
    mock_p.__aenter__ = AsyncMock(return_value=mock_p)
    mock_p.__aexit__ = AsyncMock(return_value=False)
    mock_p.chromium.launch = AsyncMock(return_value=browser)

    # when
    with (
        patch("src.reader.strategies.novnc_strategy.async_playwright", return_value=mock_p),
        patch(
            "src.reader.strategies.novnc_strategy.cookie_manager.save_storage_state",
            new=AsyncMock(),
        ) as mock_save,
        patch("src.reader.strategies.novnc_strategy.settings.NOVNC_TIMEOUT_SECONDS", 0),
    ):
        await ns._monitor_for_cookies(_make_flow("https://allegro.pl/oferta/example", "captcha"))

    # then
    mock_save.assert_not_awaited()


@pytest.mark.asyncio
async def test_novnc_captcha_monitor_writes_session_for_never_challenged_page() -> None:
    """establish() is the proactive counterpart to passive capture: a call
    against an ordinary page that already shows real content on the very
    first poll, with no block ever observed, must still persist a session
    record on that first poll -- not only once a captcha is solved. See
    e2e/testing/10-session-establish-test.md, "Two behaviours this spec
    found live, not assumed"."""
    # given
    from src.reader.strategies import novnc_strategy as ns

    page = MagicMock()
    page.goto = AsyncMock(return_value=None)
    page.evaluate = AsyncMock(return_value="Mozilla/5.0")
    page.url = "https://ordinary-site.example/"
    page.content = AsyncMock(return_value="<html><body>" + "genuine article text " * 50 + "</body></html>")

    context = MagicMock()
    context.route = AsyncMock()
    context.route_web_socket = None
    context.new_page = AsyncMock(return_value=page)
    context.storage_state = AsyncMock(return_value={"cookies": [], "origins": []})
    context.cookies = AsyncMock(return_value=context.storage_state.return_value["cookies"])

    browser = MagicMock()
    browser.new_context = AsyncMock(return_value=context)
    browser.close = AsyncMock()

    mock_p = MagicMock()
    mock_p.__aenter__ = AsyncMock(return_value=mock_p)
    mock_p.__aexit__ = AsyncMock(return_value=False)
    mock_p.chromium.launch = AsyncMock(return_value=browser)

    # when
    with (
        patch("src.reader.strategies.novnc_strategy.async_playwright", return_value=mock_p),
        patch(
            "src.reader.strategies.novnc_strategy.cookie_manager.save_storage_state",
            new=AsyncMock(),
        ) as mock_save,
        patch("src.reader.strategies.novnc_strategy.settings.NOVNC_TIMEOUT_SECONDS", 60),
        patch(
            "src.reader.strategies.novnc_strategy.assess",
            return_value=_verdict(wall=False, accepted=True),
        ),
    ):
        await ns._monitor_for_cookies(_make_flow("https://ordinary-site.example/", "captcha"))

    # then
    mock_save.assert_awaited_once()


@pytest.mark.asyncio
async def test_novnc_captcha_monitor_saves_when_wall_clears_without_cf_clearance() -> None:
    """For non-Cloudflare captchas (e.g. DataDome) there is no cf_clearance cookie; the
    monitor must capture once the challenge wall is gone."""
    # given
    from src.reader.strategies import novnc_strategy as ns

    page = MagicMock()
    page.goto = AsyncMock(return_value=None)
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
    context.route = AsyncMock()
    context.route_web_socket = None
    context.new_page = AsyncMock(return_value=page)
    context.storage_state = AsyncMock(
        return_value={"cookies": [{"name": "datadome", "value": "SOLVED"}], "origins": []}
    )
    context.cookies = AsyncMock(return_value=context.storage_state.return_value["cookies"])

    browser = MagicMock()
    browser.new_context = AsyncMock(return_value=context)
    browser.close = AsyncMock()

    mock_p = MagicMock()
    mock_p.__aenter__ = AsyncMock(return_value=mock_p)
    mock_p.__aexit__ = AsyncMock(return_value=False)
    mock_p.chromium.launch = AsyncMock(return_value=browser)

    # when
    with (
        patch("src.reader.strategies.novnc_strategy.async_playwright", return_value=mock_p),
        patch(
            "src.reader.strategies.novnc_strategy.cookie_manager.save_storage_state",
            new=AsyncMock(),
        ) as mock_save,
        patch("src.reader.strategies.novnc_strategy.settings.NOVNC_TIMEOUT_SECONDS", 60),
        patch("src.reader.strategies.novnc_strategy.asyncio.sleep", new=AsyncMock()),
        patch(
            "src.reader.strategies.novnc_strategy.assess",
            side_effect=[
                _verdict(wall=True, accepted=False),
                _verdict(wall=False, accepted=True),
            ],
        ),
    ):
        await ns._monitor_for_cookies(_make_flow("https://www.indeed.com/jobs", "captcha"))

    # then
    mock_save.assert_awaited_once()
    await_args = mock_save.await_args
    assert await_args is not None
    saved_state = await_args.args[1]
    assert any(c["name"] == "datadome" for c in saved_state["cookies"])


_WALL_PAGE = "<html><body><div id='cf-challenge-running'></div></body></html>"
_READABLE_PAGE = (
    "<html><body><article>" + "<p>A sentence a person can read here.</p>" * 40 + "</article></body></html>"
)


async def _poll_page_with_clearance(page_content: str) -> tuple[bool, bool, AsyncMock]:
    from src.reader.strategies import novnc_strategy as ns

    cookies = [{"name": "cf_clearance", "value": "issued", "domain": ".example.com"}]
    page = MagicMock()
    page.evaluate = AsyncMock(return_value="Mozilla/5.0")
    page.url = "https://example.com/"
    page.content = AsyncMock(return_value=page_content)
    context = MagicMock()
    context.storage_state = AsyncMock(return_value={"cookies": cookies, "origins": []})
    with patch(
        "src.reader.strategies.novnc_strategy.cookie_manager.save_storage_state", new=AsyncMock()
    ) as mock_save:
        resolved, page_blocked = await ns._poll_captcha(
            page,
            MainFrameResponses(page),
            context,
            {"cookies": cookies, "origins": []},
            _make_flow("https://example.com/", "captcha"),
            ns._FlowProgress(site="example.com"),
        )

    return resolved, page_blocked, mock_save


@pytest.mark.asyncio
async def test_a_new_clearance_cookie_on_a_wall_does_not_resolve_and_does_not_save() -> None:
    # when
    resolved, page_blocked, mock_save = await _poll_page_with_clearance(_WALL_PAGE)

    # then
    assert resolved is False
    assert page_blocked is True
    mock_save.assert_not_awaited()


@pytest.mark.asyncio
async def test_an_accepted_page_resolves_and_saves() -> None:
    # when
    resolved, page_blocked, mock_save = await _poll_page_with_clearance(_READABLE_PAGE)

    # then
    assert resolved is True
    assert page_blocked is False
    mock_save.assert_awaited_once()


@pytest.mark.asyncio
async def test_a_window_on_a_stored_clearance_stays_open_while_the_page_is_a_wall() -> None:
    # given
    from src.reader.strategies import novnc_strategy as ns

    stored_cookies = [{"name": "cf_clearance", "value": "stored", "domain": ".example.com"}]
    stored_state = {"cookies": stored_cookies, "origins": []}
    page = MagicMock()
    page.goto = AsyncMock(return_value=None)
    page.url = "https://example.com/"
    page.content = AsyncMock(return_value="<html><body><div id='cf-challenge-running'></div></body></html>")
    context = MagicMock()
    context.route = AsyncMock()
    context.route_web_socket = None
    context.new_page = AsyncMock(return_value=page)
    context.cookies = AsyncMock(return_value=stored_cookies)
    context.storage_state = AsyncMock(return_value=stored_state)
    browser = MagicMock()
    browser.new_context = AsyncMock(return_value=context)
    browser.close = AsyncMock()
    mock_p = MagicMock()
    mock_p.__aenter__ = AsyncMock(return_value=mock_p)
    mock_p.__aexit__ = AsyncMock(return_value=False)
    mock_p.chromium.launch = AsyncMock(return_value=browser)

    # when
    with (
        patch("src.reader.strategies.novnc_strategy.async_playwright", return_value=mock_p),
        patch(
            "src.reader.strategies.novnc_strategy.cookie_manager.get_storage_state",
            new=AsyncMock(return_value=stored_state),
        ),
        patch(
            "src.reader.strategies.novnc_strategy.cookie_manager.has_valid_login",
            new=AsyncMock(return_value=False),
        ),
        patch(
            "src.reader.strategies.novnc_strategy.cookie_manager.save_storage_state", new=AsyncMock()
        ) as mock_save,
        patch("src.reader.strategies.novnc_strategy.settings.NOVNC_TIMEOUT_SECONDS", 0.05),
        patch("src.reader.strategies.novnc_strategy.settings.NOVNC_COOKIE_SYNC_POLL_SECONDS", 0.01),
    ):
        await ns._monitor_for_cookies(_make_flow("https://example.com/", "captcha"))

    # then
    assert page.content.await_count >= 2
    mock_save.assert_not_awaited()

"""A NoVNC poll reads cookies and live frames and opens no helper tab, and a save reads the whole state."""

import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.config.config import settings
from src.reader.novnc.flow_registry import NoVNCFlow, flow_key_for, novnc_flow_registry
from src.reader.novnc.window_layout import rect_for_slot
from src.reader.strategies.novnc_strategy import (
    _BROWSER_GONE_OUTCOME,
    _RESOLVED_OUTCOME,
    _FlowProgress,
    _poll_once,
    _poll_until_settled,
)

_POLLS = 5
_SITE = "shop-site.com"
_ACCOUNT_URL = "https://www.shop-site.com/account"
_ORIGIN_A = "https://a.shop-site.com"
_ORIGIN_B = "https://b.shop-site.com"
_ARTICLE = (
    "<html><head><title>Shop</title></head><body><article><p>"
    + "word " * 400
    + "</p></article></body></html>"
)
_LOGIN_FORM = (
    "<html><head><title>Shop</title></head><body><form action='/session' method='post'>"
    "<input type='text' name='user'><input type='password' name='password'>"
    "<button type='submit'>Go</button></form></body></html>"
)
_CHALLENGE = (403, {"cf-mitigated": "challenge", "content-type": "text/html"})
_OK = (200, {"content-type": "text/html"})
_SAVE = "src.reader.strategies.novnc_strategy.cookie_manager.save_storage_state"


def _flow(url: str, intervention_type: str) -> NoVNCFlow:
    window = rect_for_slot(
        0,
        settings.NOVNC_DISPLAY_SIZE,
        (settings.NOVNC_WINDOW_WIDTH_PX, settings.NOVNC_WINDOW_HEIGHT_PX),
        settings.NOVNC_WINDOW_CASCADE_OFFSET_PX,
    )

    return NoVNCFlow(
        flow_id="e5f6a7b8c9d0",
        key=flow_key_for(url, "default"),
        url=url,
        profile="default",
        intervention_type=intervention_type,
        window=window,
        vnc_url="http://vnc/vnc.html?autoconnect=true",
        started_at=time.time(),
        request_id="test-request",
        lease_started=time.monotonic(),
    )


def _responses(status_and_headers: tuple[int, dict[str, str]]) -> MagicMock:
    responses = MagicMock()
    responses.status_and_headers = AsyncMock(return_value=status_and_headers)

    return responses


def _page(url: str, content: str, *, frames: list[MagicMock] | None = None) -> MagicMock:
    page = MagicMock()
    page.url = url
    page.frames = frames or []
    page.is_closed = MagicMock(return_value=False)
    page.content = AsyncMock(return_value=content)
    page.evaluate = AsyncMock(return_value="UA/poll")
    password_inputs = int(content == _LOGIN_FORM)
    page.locator = MagicMock(return_value=MagicMock(count=AsyncMock(return_value=password_inputs)))

    return page


def _context(
    pages: list[MagicMock],
    *,
    cookies: list[dict[str, Any]] | None = None,
    full_states: list[dict[str, Any]] | None = None,
) -> MagicMock:
    context = MagicMock()
    context.pages = pages
    context.cookies = AsyncMock(return_value=cookies or [])
    context.storage_state = (
        AsyncMock(side_effect=full_states)
        if full_states is not None
        else AsyncMock(return_value={"cookies": cookies or [], "origins": []})
    )

    return context


def _storage(origin: str, value: str) -> dict[str, Any]:
    return {"origin": origin, "localStorage": [{"name": "auth_token", "value": value}]}


def _frame(url: str, read: Any) -> MagicMock:
    frame = MagicMock()
    frame.url = url
    frame.evaluate = (
        AsyncMock(side_effect=read) if isinstance(read, Exception) else AsyncMock(return_value=read)
    )

    return frame


def _clearance_cookie() -> dict[str, Any]:
    return {"name": "cf_clearance", "value": "cleared", "domain": ".www.shop-site.com", "path": "/"}


async def test_a_captcha_window_polled_many_times_reads_only_cookies() -> None:
    # given
    page = _page(_ACCOUNT_URL, _ARTICLE)
    context = _context([page])
    flow = _flow(_ACCOUNT_URL, "captcha")
    progress = _FlowProgress(site=_SITE)

    # when
    results = [await _poll_once(page, _responses(_CHALLENGE), context, flow, progress) for _ in range(_POLLS)]

    # then
    assert results == [(None, True)] * _POLLS
    assert context.cookies.await_count == _POLLS
    assert context.storage_state.await_count == 0


async def test_a_resolved_captcha_reads_the_whole_state_once_and_saves_it() -> None:
    # given
    full_state = {"cookies": [_clearance_cookie()], "origins": [_storage(_ORIGIN_A, "kept")]}
    page = _page(_ACCOUNT_URL, _ARTICLE)
    context = _context([page], cookies=[_clearance_cookie()], full_states=[full_state])
    flow = _flow(_ACCOUNT_URL, "captcha")
    save = AsyncMock()

    # when
    with patch(_SAVE, new=save):
        outcome, _ = await _poll_once(page, _responses(_OK), context, flow, _FlowProgress(site=_SITE))

    # then
    assert outcome == _RESOLVED_OUTCOME
    assert context.storage_state.await_count == 1
    assert save.await_args is not None
    assert save.await_args.args[1] == full_state


async def test_a_login_window_on_one_address_reads_the_whole_state_once() -> None:
    # given
    page = _page(_ACCOUNT_URL, _LOGIN_FORM)
    context = _context([page])
    flow = _flow(_ACCOUNT_URL, "login")
    progress = _FlowProgress(site=_SITE)

    # when
    results = [await _poll_once(page, _responses(_OK), context, flow, progress) for _ in range(_POLLS)]

    # then
    assert results == [(None, True)] * _POLLS
    assert context.cookies.await_count == _POLLS
    assert context.storage_state.await_count == 1


@pytest.mark.parametrize("in_popup", [pytest.param(False, id="main-page"), pytest.param(True, id="popup")])
async def test_a_local_storage_change_in_a_live_site_frame_resolves_the_login(in_popup: bool) -> None:
    # given
    frame = _frame(f"{_ORIGIN_A}/widget", {"origin": _ORIGIN_A, "localStorage": []})
    popup = _page(f"{_ORIGIN_A}/popup", _ARTICLE, frames=[frame])
    page = _page(_ACCOUNT_URL, _LOGIN_FORM, frames=[] if in_popup else [frame])
    full_after_login = {"cookies": [], "origins": [_storage(_ORIGIN_A, "signed-in")]}
    context = _context(
        [page, popup] if in_popup else [page],
        full_states=[{"cookies": [], "origins": []}, full_after_login],
    )
    flow = _flow(_ACCOUNT_URL, "login")
    progress = _FlowProgress(site=_SITE)
    save = AsyncMock()

    # when
    with patch(_SAVE, new=save):
        before, _ = await _poll_once(page, _responses(_OK), context, flow, progress)
        frame.evaluate = AsyncMock(return_value=_storage(_ORIGIN_A, "signed-in"))
        page.content = AsyncMock(return_value=_ARTICLE)
        page.locator = MagicMock(return_value=MagicMock(count=AsyncMock(return_value=0)))
        after, _ = await _poll_once(page, _responses(_OK), context, flow, progress)

    # then
    assert before is None
    assert after == _RESOLVED_OUTCOME
    assert save.await_args is not None
    assert save.await_args.args[1] == full_after_login


async def test_a_token_written_just_before_a_redirect_resolves_at_the_first_poll_on_the_new_origin() -> None:
    # given
    page = _page(f"{_ORIGIN_A}/signin", _LOGIN_FORM)
    full_after_redirect = {"cookies": [], "origins": [_storage(_ORIGIN_A, "signed-in")]}
    context = _context(
        [page],
        full_states=[{"cookies": [], "origins": []}, full_after_redirect, full_after_redirect],
    )
    flow = _flow(f"{_ORIGIN_A}/signin", "login")
    progress = _FlowProgress(site=_SITE)
    save = AsyncMock()

    # when
    with patch(_SAVE, new=save):
        before, _ = await _poll_once(page, _responses(_OK), context, flow, progress)
        page.url = f"{_ORIGIN_B}/home"
        page.content = AsyncMock(return_value=_ARTICLE)
        page.locator = MagicMock(return_value=MagicMock(count=AsyncMock(return_value=0)))
        after, _ = await _poll_once(page, _responses(_OK), context, flow, progress)

    # then
    assert before is None
    assert after == _RESOLVED_OUTCOME
    assert progress.last_poll_address == f"{_ORIGIN_B}/home"


async def test_a_token_seen_in_a_frame_stays_after_that_frame_is_gone() -> None:
    # given
    frame = _frame(f"{_ORIGIN_A}/widget", _storage(_ORIGIN_A, "signed-in"))
    page = _page(_ACCOUNT_URL, _LOGIN_FORM, frames=[frame])
    context = _context([page])
    progress = _FlowProgress(site=_SITE)
    flow = _flow(_ACCOUNT_URL, "login")

    # when
    await _poll_once(page, _responses(_OK), context, flow, progress)
    page.frames = []
    await _poll_once(page, _responses(_OK), context, flow, progress)

    # then
    assert progress.site_storage == {_ORIGIN_A: [{"name": "auth_token", "value": "signed-in"}]}


async def test_a_new_address_forgets_a_token_the_site_removed() -> None:
    # given
    page = _page(_ACCOUNT_URL, _LOGIN_FORM)
    context = _context(
        [page],
        full_states=[
            {"cookies": [], "origins": [_storage(_ORIGIN_A, "old")]},
            {"cookies": [], "origins": []},
        ],
    )
    flow = _flow(_ACCOUNT_URL, "login")
    progress = _FlowProgress(site=_SITE)

    # when
    await _poll_once(page, _responses(_OK), context, flow, progress)
    page.url = f"{_ORIGIN_B}/signin"
    await _poll_once(page, _responses(_OK), context, flow, progress)

    # then
    assert progress.site_storage == {}


async def test_a_new_address_reloads_only_the_origins_of_the_site() -> None:
    # given
    full_state = {
        "cookies": [],
        "origins": [_storage(_ORIGIN_A, "kept"), _storage("https://captcha-widget.net", "other")],
    }
    page = _page(_ACCOUNT_URL, _LOGIN_FORM)
    context = _context([page], full_states=[full_state])
    progress = _FlowProgress(site=_SITE)

    # when
    await _poll_once(page, _responses(_OK), context, _flow(_ACCOUNT_URL, "login"), progress)

    # then
    assert list(progress.site_storage) == [_ORIGIN_A]


async def test_off_site_frames_are_not_evaluated() -> None:
    # given
    off_site = _frame("https://captcha-widget.net/challenge", _storage("https://captcha-widget.net", "x"))
    blank = _frame("about:blank", None)
    page = _page(_ACCOUNT_URL, _LOGIN_FORM, frames=[off_site, blank])
    context = _context([page])

    # when
    await _poll_once(page, _responses(_OK), context, _flow(_ACCOUNT_URL, "login"), _FlowProgress(site=_SITE))

    # then
    off_site.evaluate.assert_not_awaited()
    blank.evaluate.assert_not_awaited()


@pytest.mark.parametrize(
    "broken_read",
    [
        pytest.param(None, id="opaque-origin"),
        pytest.param(RuntimeError("Frame was detached"), id="detached"),
        pytest.param(RuntimeError("Target page, context or browser has been closed"), id="popup-closing"),
    ],
)
async def test_a_frame_that_cannot_be_read_does_not_break_the_poll(broken_read: Any) -> None:
    # given
    broken = _frame(f"{_ORIGIN_A}/sandboxed", broken_read)
    healthy = _frame(f"{_ORIGIN_B}/widget", _storage(_ORIGIN_B, "live"))
    page = _page(_ACCOUNT_URL, _LOGIN_FORM, frames=[broken, healthy])
    context = _context([page])
    progress = _FlowProgress(site=_SITE)

    # when
    result = await _poll_once(page, _responses(_OK), context, _flow(_ACCOUNT_URL, "login"), progress)

    # then
    assert result == (None, True)
    assert progress.login_wall_seen is True
    assert progress.site_storage == {_ORIGIN_B: [{"name": "auth_token", "value": "live"}]}


@pytest.mark.parametrize("intervention_type", ["captcha", "login"])
async def test_a_browser_gone_error_from_cookies_ends_as_browser_closed(intervention_type: str) -> None:
    # given
    page = _page(_ACCOUNT_URL, _LOGIN_FORM)
    context = _context([page])
    context.cookies = AsyncMock(side_effect=RuntimeError("Target page, context or browser has been closed"))
    browser = MagicMock()
    browser.is_connected = MagicMock(return_value=True)

    # when
    with patch.object(novnc_flow_registry, "cancel_requested", new=AsyncMock(return_value=False)):
        outcome = await _poll_until_settled(
            browser,
            page,
            _responses(_OK),
            context,
            _flow(_ACCOUNT_URL, intervention_type),
            _FlowProgress(site=_SITE),
            time.monotonic() + 5,
        )

    # then
    assert outcome == _BROWSER_GONE_OUTCOME


async def test_a_failed_whole_state_read_is_tried_again_at_the_next_poll() -> None:
    # given
    page = _page(_ACCOUNT_URL, _LOGIN_FORM)
    context = _context([page])
    context.storage_state = AsyncMock(
        side_effect=[RuntimeError("transient"), {"cookies": [], "origins": [_storage(_ORIGIN_A, "kept")]}]
    )
    flow = _flow(_ACCOUNT_URL, "login")
    progress = _FlowProgress(site=_SITE)

    # when
    await _poll_once(page, _responses(_OK), context, flow, progress)
    await _poll_once(page, _responses(_OK), context, flow, progress)

    # then
    assert context.storage_state.await_count == 2
    assert list(progress.site_storage) == [_ORIGIN_A]

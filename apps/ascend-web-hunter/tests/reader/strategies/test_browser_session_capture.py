"""A browser tier that clears a wall stores the clearance it earned, and nothing else."""

from collections.abc import Awaitable, Callable, Iterator
from contextlib import ExitStack, contextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from playwright.async_api import Error as PlaywrightError

from src.api.exceptions import ChallengeDetectedException
from src.config.config import settings
from src.reader.cloudflare.challenge_signals import ChallengeVerdict
from src.reader.cloudflare.cookie_manager import cookie_manager
from src.reader.strategies import browser_read
from tests.reader.strategies.test_browser_tier_main_frame import (
    _TIERS,
    _camoufox_read,
    _camoufox_wiring,
    _context,
    _page,
    _patchright_read,
    _patchright_wiring,
    _playwright_read,
    _playwright_wiring,
)

_URL = "https://www.example.com/page"
_REAL_USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) Chrome/148.0.0.0"
_WALL_HTML = "<html><head><title>Just a moment...</title></head><body>wall</body></html>"
_PAGE_HTML = (
    "<html><head><title>Reports</title></head><body><article><p>"
    + "word " * 60
    + "</p></article></body></html>"
)
_CLEARANCE: dict[str, Any] = {"name": "cf_clearance", "value": "c", "domain": ".example.com", "path": "/"}
_BOT_COOKIE: dict[str, Any] = {"name": "__cf_bm", "value": "b", "domain": ".example.com", "path": "/"}
_SITE_COOKIE: dict[str, Any] = {"name": "visitor", "value": "v", "domain": ".example.com", "path": "/"}
_LOGIN_COOKIE: dict[str, Any] = {"name": "session", "value": "s", "domain": ".example.com", "path": "/"}
_OTHER_SITE_CLEARANCE: dict[str, Any] = {**_CLEARANCE, "domain": ".other.example.org"}

_PRODUCER_TIERS: list[Any] = [
    pytest.param(_playwright_wiring, _playwright_read, "4-playwright_stealth", id="4-playwright_stealth"),
    pytest.param(_patchright_wiring, _patchright_read, "4a-patchright", id="4a-patchright"),
    pytest.param(_camoufox_wiring, _camoufox_read, "4b-camoufox", id="4b-camoufox"),
]

Wiring = Callable[[MagicMock], Any]
Read = Callable[[str], Awaitable[str]]


def _verdict_of(_status: int, html: str, *_args: Any, **_kwargs: Any) -> ChallengeVerdict:
    is_wall = html == _WALL_HTML

    return ChallengeVerdict(
        score=200 if is_wall else 0,
        threshold=100,
        signals=(),
        vendor="cloudflare" if is_wall else None,
        wall=is_wall,
        has_content=not is_wall,
        intervention_type="captcha",
    )


def _capturing_page(contents: list[str], cookies: list[dict[str, Any]]) -> tuple[MagicMock, MagicMock]:
    page = _page()
    page.content = AsyncMock(side_effect=[*contents, *[contents[-1]] * 4])
    page.evaluate = AsyncMock(
        side_effect=lambda expression, *_: _REAL_USER_AGENT if expression == "navigator.userAgent" else 0
    )
    context = _context(page)
    context.storage_state = AsyncMock(
        return_value={
            "cookies": cookies,
            "origins": [{"origin": "https://www.example.com", "localStorage": []}],
        }
    )

    return page, context


@contextmanager
def _wired_read(wiring: Wiring, context: MagicMock) -> Iterator[AsyncMock]:
    save = AsyncMock()
    with ExitStack() as stack:
        stack.enter_context(wiring(context))
        stack.enter_context(patch.object(browser_read, "assess", new=_verdict_of))
        stack.enter_context(patch.object(cookie_manager, "save_storage_state", new=save))
        yield save


@pytest.mark.asyncio
@pytest.mark.parametrize(("wiring", "read", "producer"), _PRODUCER_TIERS)
async def test_a_read_that_clears_a_wall_stores_its_clearance_under_the_tier_with_the_real_user_agent(
    wiring: Wiring, read: Read, producer: str
) -> None:
    # given a page judged a wall once, then an accepted page holding a clearance
    _, context = _capturing_page([_WALL_HTML, _PAGE_HTML], [_CLEARANCE, _BOT_COOKIE, _SITE_COOKIE])

    # when
    with _wired_read(wiring, context) as save:
        html = await read(_URL)

    # then only the WAF cookies are stored, so an automatic read never looks like a login
    assert html == _PAGE_HTML
    save.assert_awaited_once_with(
        _URL, {"cookies": [_CLEARANCE, _BOT_COOKIE], "origins": []}, _REAL_USER_AGENT, None, producer
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(("wiring", "read"), _TIERS)
async def test_a_page_that_was_never_a_wall_stores_nothing(wiring: Wiring, read: Read) -> None:
    # given a page accepted on the first poll, with a clearance replayed from an earlier read
    _, context = _capturing_page([_PAGE_HTML], [_CLEARANCE])

    # when
    with _wired_read(wiring, context) as save:
        await read(_URL)

    # then
    save.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(("wiring", "read"), _TIERS)
async def test_a_read_that_ends_on_a_wall_stores_nothing(
    wiring: Wiring, read: Read, monkeypatch: pytest.MonkeyPatch
) -> None:
    # given a wall that outlasts the wait, with a clearance cookie already in the jar
    monkeypatch.setattr(settings, "CHALLENGE_CLEAR_WAIT_SECONDS", 0.0)
    _, context = _capturing_page([_WALL_HTML], [_CLEARANCE])

    # when
    with _wired_read(wiring, context) as save, pytest.raises(ChallengeDetectedException):
        await read(_URL)

    # then
    save.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "cookies",
    [[], [_BOT_COOKIE, _SITE_COOKIE], [_OTHER_SITE_CLEARANCE]],
    ids=["none", "no-clearance", "other-site"],
)
async def test_a_cleared_wall_without_a_clearance_cookie_of_the_site_stores_nothing(
    cookies: list[dict[str, Any]],
) -> None:
    # given
    _, context = _capturing_page([_WALL_HTML, _PAGE_HTML], cookies)

    # when
    with _wired_read(_patchright_wiring, context) as save:
        await _patchright_read(_URL)

    # then
    save.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_browser_that_cannot_hand_over_its_state_still_answers_the_read() -> None:
    # given
    _, context = _capturing_page([_WALL_HTML, _PAGE_HTML], [_CLEARANCE])
    context.storage_state = AsyncMock(side_effect=PlaywrightError("target closed"))

    # when
    with _wired_read(_playwright_wiring, context) as save:
        html = await _playwright_read(_URL)

    # then
    assert html == _PAGE_HTML
    save.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_stored_login_survives_a_clearance_capture(monkeypatch: pytest.MonkeyPatch) -> None:
    # given a valid login in the real cookie manager, kept in memory
    monkeypatch.setattr(cookie_manager, "redis_client", None)
    monkeypatch.setattr(cookie_manager, "_memory_store", {})
    await cookie_manager.save_storage_state(
        _URL, {"cookies": [_LOGIN_COOKIE], "origins": []}, "LoginUA/1.0", None, "6-novnc", replaces_login=True
    )
    _, context = _capturing_page([_WALL_HTML, _PAGE_HTML], [_CLEARANCE, _LOGIN_COOKIE])

    # when
    with ExitStack() as stack:
        stack.enter_context(_patchright_wiring(context))
        stack.enter_context(patch.object(browser_read, "assess", new=_verdict_of))
        await _patchright_read(_URL)

    # then the login is untouched and the clearance sits beside it
    stored = await cookie_manager.get_storage_state(_URL)
    assert await cookie_manager.has_valid_login(_URL)
    assert stored is not None
    assert {cookie["name"] for cookie in stored["cookies"]} == {"session", "cf_clearance"}
    assert await cookie_manager.get_user_agent(_URL) == "LoginUA/1.0"


@pytest.mark.asyncio
async def test_a_clearance_capture_does_not_make_the_site_look_logged_in(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # given
    monkeypatch.setattr(cookie_manager, "redis_client", None)
    monkeypatch.setattr(cookie_manager, "_memory_store", {})
    _, context = _capturing_page([_WALL_HTML, _PAGE_HTML], [_CLEARANCE, _SITE_COOKIE])

    # when
    with ExitStack() as stack:
        stack.enter_context(_patchright_wiring(context))
        stack.enter_context(patch.object(browser_read, "assess", new=_verdict_of))
        await _patchright_read(_URL)

    # then
    assert not await cookie_manager.has_auth_state(_URL)
    assert await cookie_manager.get_stored_session_producer(_URL) == "4a-patchright"
    assert await cookie_manager.get_user_agent(_URL) == _REAL_USER_AGENT

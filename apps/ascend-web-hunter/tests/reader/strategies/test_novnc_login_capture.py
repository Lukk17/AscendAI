"""A NoVNC flow keeps a valid stored login, saves a login only once it
succeeded, under the right site and profile, and a later read replays it."""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.config.config import settings
from src.reader.cloudflare.cookie_manager import (
    PRODUCED_BY_IMPORT,
    PRODUCED_BY_LOGIN_SEED,
    PRODUCED_BY_NOVNC,
    cookie_manager,
)
from src.reader.novnc.flow_registry import NoVNCFlow, flow_key_for, novnc_flow_registry
from src.reader.novnc.window_layout import rect_for_slot
from src.reader.strategies.novnc_strategy import (
    _BROWSER_GONE_OUTCOME,
    _log_browser_closed,
    _monitor_for_cookies,
)
from src.reader.strategies.playwright_strategy import PlaywrightStrategy
from src.session.session_manager import session_manager
from src.validator.url_validator import URLValidator
from tests.reader.novnc.test_flow_registry import FakeRedis

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
_HIDDEN_PASSWORD_ARTICLE = _ARTICLE.replace(
    "<article>", "<form hidden><input type='password' name='password'></form><article>"
)

_VISIBLE_MARKUP_PASSWORD_INPUTS = {_LOGIN_FORM: 1}


def _cookie(name: str, value: str, domain: str = "www.shop-site.com") -> dict[str, Any]:
    return {
        "name": name,
        "value": value,
        "domain": domain,
        "path": "/",
        "expires": -1,
        "httpOnly": True,
        "secure": True,
        "sameSite": "Lax",
    }


@dataclass
class _Step:
    url: str
    content: str
    cookies: list[dict[str, Any]]
    origins: list[dict[str, Any]] = field(default_factory=list)
    main_frame: tuple[int, dict[str, str]] | None = None
    rendered_password_inputs: int = 0
    password_probe_error: Exception | None = None


def _main_frame_response(status: int, headers: dict[str, str]) -> MagicMock:
    response = MagicMock(status=status)
    response.all_headers = AsyncMock(return_value=headers)
    response.request.is_navigation_request = MagicMock(return_value=True)
    response.frame.parent_frame = None

    return response


def _live_frame(origin: dict[str, Any]) -> MagicMock:
    frame = MagicMock()
    frame.url = f"{origin['origin']}/"
    frame.evaluate = AsyncMock(return_value=origin)

    return frame


@dataclass
class _ScriptedBrowser:
    """A browser double whose page walks through scripted steps, one per poll."""

    steps: list[_Step]
    index: int = 0
    polled: _Step | None = None
    probed_selectors: list[str] = field(default_factory=list)
    page: MagicMock = field(default_factory=MagicMock)
    context: MagicMock = field(default_factory=MagicMock)
    browser: MagicMock = field(default_factory=MagicMock)

    def __post_init__(self) -> None:
        self.page.url = self.steps[0].url
        self.page.goto = AsyncMock(return_value=None)
        self.page.evaluate = AsyncMock(return_value="UA/scripted")
        self.page.is_closed = MagicMock(return_value=False)
        self.page.content = AsyncMock(side_effect=self._content)
        self.page.locator = MagicMock(side_effect=self._locator)
        self.context.route = AsyncMock()
        self.context.route_web_socket = None
        self.context.new_page = AsyncMock(return_value=self.page)
        self.context.pages = [self.page]
        self.context.cookies = AsyncMock(side_effect=self._cookies)
        self.context.storage_state = AsyncMock(side_effect=self._storage_state)
        self.browser.new_context = AsyncMock(return_value=self.context)
        self.browser.close = AsyncMock()
        self.browser.is_connected = MagicMock(return_value=True)

    def _current(self) -> _Step:
        return self.steps[min(self.index, len(self.steps) - 1)]

    async def _cookies(self) -> list[dict[str, Any]]:
        step = self._current()
        self.polled = step
        self.page.url = step.url
        self.page.frames = [_live_frame(origin) for origin in step.origins]
        if step.main_frame is not None:
            self._navigate(_main_frame_response(*step.main_frame))

        return list(step.cookies)

    async def _storage_state(self) -> dict[str, Any]:
        step = self.polled or self._current()

        return {"cookies": list(step.cookies), "origins": list(step.origins)}

    def _navigate(self, response: MagicMock) -> None:
        for call in self.page.on.call_args_list:
            if call.args[0] == "response":
                call.args[1](response)

    def _locator(self, selector: str) -> MagicMock:
        self.probed_selectors.append(selector)
        step = self.polled or self._current()
        locator = MagicMock()
        if step.password_probe_error is not None:
            locator.count = AsyncMock(side_effect=step.password_probe_error)
        else:
            locator.count = AsyncMock(
                return_value=_VISIBLE_MARKUP_PASSWORD_INPUTS.get(step.content, 0)
                + step.rendered_password_inputs
            )

        return locator

    async def _content(self) -> str:
        step = self._current()
        self.index += 1

        return step.content

    def factory(self) -> Any:
        pw = MagicMock()
        pw.chromium.launch = AsyncMock(return_value=self.browser)
        factory = MagicMock()
        factory.__aenter__ = AsyncMock(return_value=pw)
        factory.__aexit__ = AsyncMock(return_value=False)

        return factory


def _make_flow(url: str, intervention_type: str, profile: str) -> NoVNCFlow:
    window = rect_for_slot(
        0,
        settings.NOVNC_DISPLAY_SIZE,
        (settings.NOVNC_WINDOW_WIDTH_PX, settings.NOVNC_WINDOW_HEIGHT_PX),
        settings.NOVNC_WINDOW_CASCADE_OFFSET_PX,
    )

    return NoVNCFlow(
        flow_id="d4e5f6a7b8c9",
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


@pytest.fixture(autouse=True)
def _isolated_registry(monkeypatch: pytest.MonkeyPatch) -> Any:
    monkeypatch.setattr(novnc_flow_registry, "_redis", FakeRedis())
    monkeypatch.setattr(settings, "NOVNC_COOKIE_SYNC_POLL_SECONDS", 0.01)
    novnc_flow_registry._local.clear()
    yield
    novnc_flow_registry._local.clear()


async def _store_login(url: str, profile: str, value: str = "LOGGED-IN") -> None:
    await cookie_manager.save_storage_state(
        url,
        {"cookies": [_cookie("session", value)], "origins": []},
        "UA/stored",
        profile,
        PRODUCED_BY_NOVNC,
        replaces_login=True,
    )


async def _stored_cookies(url: str, profile: str) -> dict[str, str]:
    return await cookie_manager.get_flat_cookies(url, profile)


async def _run_monitor(flow: NoVNCFlow, scripted: _ScriptedBrowser, timeout_seconds: float = 0.5) -> None:
    with (
        patch("src.reader.strategies.novnc_strategy.async_playwright", return_value=scripted.factory()),
        patch.object(settings, "NOVNC_TIMEOUT_SECONDS", timeout_seconds),
    ):
        flow.lease_started = time.monotonic()
        await asyncio.wait_for(_monitor_for_cookies(flow), timeout=5.0)


async def test_the_window_starts_from_the_stored_session_of_that_site_and_profile() -> None:
    # given
    url = "https://www.shop-site.com/"
    await _store_login(url, "work")
    scripted = _ScriptedBrowser([_Step(url, _ARTICLE, [])])

    # when
    await _run_monitor(_make_flow(url, "login", "work"), scripted, timeout_seconds=0.05)

    # then
    storage_state = scripted.browser.new_context.call_args.kwargs["storage_state"]
    assert [cookie["name"] for cookie in storage_state["cookies"]] == ["session"]
    assert storage_state["cookies"][0]["value"] == "LOGGED-IN"


async def test_the_window_starts_anonymous_without_a_stored_session() -> None:
    # given
    url = "https://www.shop-site.com/"
    scripted = _ScriptedBrowser([_Step(url, _ARTICLE, [])])

    # when
    await _run_monitor(_make_flow(url, "login", "work"), scripted, timeout_seconds=0.05)

    # then
    assert "storage_state" not in scripted.browser.new_context.call_args.kwargs


async def test_a_valid_stored_login_survives_an_abandoned_establish() -> None:
    """Establish opens the window on the site's login page and the human never logs
    in: the window stays open until its timeout and the stored login is intact."""
    # given
    url = "https://www.shop-site.com/"
    await _store_login(url, "work")
    scripted = _ScriptedBrowser([_Step(url, _LOGIN_FORM, [_cookie("_ga", "anonymous")])])

    # when
    with (
        patch("src.reader.strategies.novnc_strategy.async_playwright", return_value=scripted.factory()),
        patch.object(settings, "NOVNC_TIMEOUT_SECONDS", 0.3),
        patch.object(settings, "PUBLIC_VNC_URL", "http://vnc"),
        patch.object(settings, "NOVNC_PUBLIC_URL", None),
    ):
        established = await session_manager.establish(url, "work")
        [flow] = novnc_flow_registry.local()
        assert flow.task is not None
        await asyncio.wait_for(flow.task, timeout=5.0)

    # then
    assert established.intervention_type == "login"
    assert scripted.index > 1
    assert await _stored_cookies(url, "work") == {"session": "LOGGED-IN"}


async def test_a_captcha_capture_over_a_valid_login_keeps_the_login() -> None:
    """A captcha flow accepts an ordinary page whose captured state lacks the
    login cookie: the clearance is saved, the stored login is kept."""
    # given
    url = "https://www.shop-site.com/"
    await _store_login(url, "work")
    scripted = _ScriptedBrowser([_Step(url, _ARTICLE, [_cookie("cf_clearance", "solved")])])

    # when
    await _run_monitor(_make_flow(url, "captcha", "work"), scripted)

    # then
    assert await _stored_cookies(url, "work") == {"session": "LOGGED-IN", "cf_clearance": "solved"}


async def test_a_completed_login_is_saved_once_under_its_site_and_profile() -> None:
    # given
    url = "https://www.shop-site.com/"
    scripted = _ScriptedBrowser(
        [
            _Step(url, _LOGIN_FORM, [_cookie("csrf", "c1")]),
            _Step(url, _LOGIN_FORM, [_cookie("csrf", "c1")]),
            _Step(
                "https://www.shop-site.com/inventory.html",
                _ARTICLE,
                [_cookie("csrf", "c1"), _cookie("session", "s1")],
            ),
        ]
    )
    save = AsyncMock(wraps=cookie_manager.save_storage_state)

    # when
    with patch("src.reader.strategies.novnc_strategy.cookie_manager.save_storage_state", new=save):
        await _run_monitor(_make_flow(url, "login", "work"), scripted, timeout_seconds=2.0)

    # then
    assert save.await_count == 1
    assert await _stored_cookies(url, "work") == {"csrf": "c1", "session": "s1"}
    assert await _stored_cookies(url, "default") == {}
    assert await cookie_manager.get_stored_session_producer(url, "work") == PRODUCED_BY_NOVNC
    assert scripted.browser.close.await_count == 1


async def test_a_new_login_replaces_a_stored_login() -> None:
    # given
    url = "https://www.shop-site.com/"
    await _store_login(url, "work", value="OLD")
    scripted = _ScriptedBrowser(
        [
            _Step(url, _LOGIN_FORM, [_cookie("session", "OLD")]),
            _Step("https://www.shop-site.com/inventory.html", _ARTICLE, [_cookie("other", "x")]),
        ]
    )

    # when
    await _run_monitor(_make_flow(url, "login", "work"), scripted, timeout_seconds=2.0)

    # then
    assert await _stored_cookies(url, "work") == {"other": "x"}


async def test_a_login_page_left_without_a_new_cookie_saves_nothing() -> None:
    # given
    url = "https://www.shop-site.com/"
    scripted = _ScriptedBrowser(
        [
            _Step(url, _LOGIN_FORM, [_cookie("csrf", "c1")]),
            _Step("https://www.shop-site.com/help", _ARTICLE, [_cookie("csrf", "c1")]),
        ]
    )
    save = AsyncMock()

    # when
    with patch("src.reader.strategies.novnc_strategy.cookie_manager.save_storage_state", new=save):
        await _run_monitor(_make_flow(url, "login", "work"), scripted, timeout_seconds=0.2)

    # then
    save.assert_not_awaited()


async def test_a_page_without_any_login_page_saves_nothing() -> None:
    """Cookies that change on ordinary pages are not a login."""
    # given
    url = "https://www.shop-site.com/"
    scripted = _ScriptedBrowser(
        [
            _Step(url, _ARTICLE, [_cookie("_ga", "1")]),
            _Step("https://www.shop-site.com/about", _ARTICLE, [_cookie("_ga", "2")]),
        ]
    )
    save = AsyncMock()

    # when
    with patch("src.reader.strategies.novnc_strategy.cookie_manager.save_storage_state", new=save):
        await _run_monitor(_make_flow(url, "login", "work"), scripted, timeout_seconds=0.2)

    # then
    save.assert_not_awaited()


async def test_a_login_wall_url_counts_as_a_login_page() -> None:
    # given
    url = "https://www.shop-site.com/?login=1"
    scripted = _ScriptedBrowser(
        [
            _Step(url, _ARTICLE, []),
            _Step("https://www.shop-site.com/home", _ARTICLE, [_cookie("session", "s9")]),
        ]
    )

    # when
    await _run_monitor(_make_flow(url, "login", "default"), scripted, timeout_seconds=2.0)

    # then
    assert await _stored_cookies(url, "default") == {"session": "s9"}


async def test_a_login_path_the_site_sent_the_window_to_counts_as_a_login_page() -> None:
    # given
    url = "https://www.shop-site.com/r/programming/"
    landing = "https://www.shop-site.com/login/?dest=https%3A%2F%2Fwww.shop-site.com%2Fr%2Fprogramming%2F"
    welcome = "<html><head><title>Welcome to Shop</title></head><body><shop-login></shop-login></body></html>"
    scripted = _ScriptedBrowser(
        [
            _Step(landing, welcome, [_cookie("csrf", "c1")]),
            _Step(url, _ARTICLE, [_cookie("csrf", "c1"), _cookie("session", "s7")]),
        ]
    )

    # when
    await _run_monitor(_make_flow(url, "login", "default"), scripted, timeout_seconds=2.0)

    # then
    assert await _stored_cookies(url, "default") == {"csrf": "c1", "session": "s7"}


async def test_a_finished_login_that_ends_on_a_login_path_with_a_return_address_resolves() -> None:
    # given
    url = "https://www.shop-site.com/r/programming/"
    callback = "https://www.shop-site.com/login/callback?next=%2Fr%2Fprogramming%2F"
    scripted = _ScriptedBrowser(
        [
            _Step(url, _LOGIN_FORM, []),
            _Step(callback, _ARTICLE, [_cookie("session", "s8")]),
        ]
    )

    # when
    await _run_monitor(_make_flow(url, "login", "default"), scripted, timeout_seconds=2.0)

    # then
    assert await _stored_cookies(url, "default") == {"session": "s8"}


async def test_a_finished_login_that_ends_on_a_signin_callback_resolves() -> None:
    # given
    url = "https://www.shop-site.com/r/programming/"
    callback = "https://www.shop-site.com/signin/callback"
    scripted = _ScriptedBrowser(
        [
            _Step(url, _LOGIN_FORM, []),
            _Step(callback, _ARTICLE, [_cookie("session", "s9")]),
        ]
    )

    # when
    await _run_monitor(_make_flow(url, "login", "default"), scripted, timeout_seconds=2.0)

    # then
    assert await _stored_cookies(url, "default") == {"session": "s9"}


_WEB_COMPONENT_LOGIN = (
    "<html><head><title>Shop</title></head><body><shop-login-form></shop-login-form></body></html>"
)


async def test_a_window_that_stays_on_the_login_address_does_not_resolve_on_a_new_site_cookie() -> None:
    """The site sets a cookie of its own while the login form still shows: nobody logged in."""
    # given
    url = "https://www.shop-site.com/r/programming/"
    landing = "https://www.shop-site.com/login/?reason=lor2&dest=https%3A%2F%2Fwww.shop-site.com%2Fr%2Fprogramming%2F"
    reloaded = "https://www.shop-site.com/login/?reason=lor3&dest=https%3A%2F%2Fwww.shop-site.com%2F"
    scripted = _ScriptedBrowser(
        [
            _Step(landing, _WEB_COMPONENT_LOGIN, [_cookie("csrf", "c1")]),
            _Step(landing, _WEB_COMPONENT_LOGIN, [_cookie("csrf", "c1"), _cookie("session", "anon1")]),
            _Step(reloaded, _WEB_COMPONENT_LOGIN, [_cookie("csrf", "c1"), _cookie("session", "anon2")]),
        ]
    )
    save = AsyncMock()

    # when
    with patch("src.reader.strategies.novnc_strategy.cookie_manager.save_storage_state", new=save):
        await _run_monitor(_make_flow(url, "login", "default"), scripted, timeout_seconds=0.3)

    # then
    save.assert_not_awaited()
    assert scripted.index >= 3


async def test_a_login_wall_seen_on_a_login_address_still_resolves_on_another_path() -> None:
    # given
    url = "https://www.shop-site.com/r/programming/"
    landing = "https://www.shop-site.com/login/?dest=https%3A%2F%2Fwww.shop-site.com%2Fr%2Fprogramming%2F"
    scripted = _ScriptedBrowser(
        [
            _Step(landing, _WEB_COMPONENT_LOGIN, [_cookie("csrf", "c1")]),
            _Step("https://www.shop-site.com/signin/callback", _ARTICLE, [_cookie("session", "s11")]),
        ]
    )

    # when
    await _run_monitor(_make_flow(url, "login", "default"), scripted, timeout_seconds=2.0)

    # then
    assert await _stored_cookies(url, "default") == {"session": "s11"}


async def test_a_password_input_inside_a_shadow_root_counts_as_a_login_page() -> None:
    # given
    url = "https://www.shop-site.com/r/programming/"
    scripted = _ScriptedBrowser(
        [
            _Step(url, _WEB_COMPONENT_LOGIN, [], rendered_password_inputs=1),
            _Step("https://www.shop-site.com/home", _ARTICLE, [_cookie("session", "s12")]),
        ]
    )

    # when
    await _run_monitor(_make_flow(url, "login", "default"), scripted, timeout_seconds=2.0)

    # then
    assert await _stored_cookies(url, "default") == {"session": "s12"}
    assert "input[type=password]:visible" in scripted.probed_selectors


async def test_a_new_cookie_while_a_shadow_root_password_input_shows_does_not_resolve() -> None:
    # given
    url = "https://www.shop-site.com/r/programming/"
    scripted = _ScriptedBrowser(
        [
            _Step(url, _LOGIN_FORM, [_cookie("csrf", "c1")]),
            _Step(
                "https://www.shop-site.com/account/verify",
                _WEB_COMPONENT_LOGIN,
                [_cookie("csrf", "c1"), _cookie("session", "anon")],
                rendered_password_inputs=1,
            ),
        ]
    )
    save = AsyncMock()

    # when
    with patch("src.reader.strategies.novnc_strategy.cookie_manager.save_storage_state", new=save):
        await _run_monitor(_make_flow(url, "login", "default"), scripted, timeout_seconds=0.2)

    # then
    save.assert_not_awaited()


async def test_a_failed_password_probe_is_a_transient_poll_error() -> None:
    # given
    url = "https://www.shop-site.com/r/programming/"
    scripted = _ScriptedBrowser(
        [
            _Step(url, _LOGIN_FORM, []),
            _Step(
                "https://www.shop-site.com/home",
                _ARTICLE,
                [_cookie("session", "s13")],
                password_probe_error=RuntimeError(
                    "Execution context was destroyed, most likely a navigation"
                ),
            ),
            _Step("https://www.shop-site.com/home", _ARTICLE, [_cookie("session", "s13")]),
        ]
    )

    # when
    await _run_monitor(_make_flow(url, "login", "default"), scripted, timeout_seconds=2.0)

    # then
    assert await _stored_cookies(url, "default") == {"session": "s13"}
    assert scripted.index == 3


async def test_a_closed_page_during_the_password_probe_ends_the_window_as_browser_closed() -> None:
    # given
    url = "https://www.shop-site.com/r/programming/"
    scripted = _ScriptedBrowser(
        [
            _Step(
                url,
                _WEB_COMPONENT_LOGIN,
                [],
                password_probe_error=RuntimeError("Target page, context or browser has been closed"),
            ),
        ]
    )
    flow = _make_flow(url, "login", "default")
    save = AsyncMock()

    # when
    with patch("src.reader.strategies.novnc_strategy.cookie_manager.save_storage_state", new=save):
        await _run_monitor(flow, scripted, timeout_seconds=2.0)

    # then
    save.assert_not_awaited()
    result = await novnc_flow_registry.last_result(flow.key)
    assert result is not None
    assert result.outcome == "browser_closed"


async def test_a_page_titled_sign_in_counts_as_a_login_page() -> None:
    # given
    url = "https://www.shop-site.com/r/programming/"
    titled = _ARTICLE.replace("<title>Shop</title>", "<title>Sign in</title>")
    scripted = _ScriptedBrowser(
        [
            _Step(url, titled, []),
            _Step(url, _ARTICLE, [_cookie("session", "s10")]),
        ]
    )

    # when
    await _run_monitor(_make_flow(url, "login", "default"), scripted, timeout_seconds=2.0)

    # then
    assert await _stored_cookies(url, "default") == {"session": "s10"}


async def test_the_saved_login_is_replayed_by_a_later_read() -> None:
    """After the human completes the login, a later headless read of the same
    site and profile starts its browser context from the captured session."""
    # given
    url = "https://www.shop-site.com/"
    scripted = _ScriptedBrowser(
        [
            _Step(url, _LOGIN_FORM, []),
            _Step("https://www.shop-site.com/inventory.html", _ARTICLE, [_cookie("session", "s1")]),
        ]
    )
    await _run_monitor(_make_flow(url, "login", "work"), scripted, timeout_seconds=2.0)
    read_page = MagicMock()
    read_response = MagicMock(status=200)
    read_response.all_headers = AsyncMock(return_value={})
    read_page.goto = AsyncMock(return_value=read_response)
    read_page.content = AsyncMock(return_value=_ARTICLE)
    read_page.url = "https://www.shop-site.com/inventory.html"
    read_page.wait_for_load_state = AsyncMock()
    read_page.wait_for_timeout = AsyncMock()
    read_page.evaluate = AsyncMock(return_value=0)
    read_page.route = AsyncMock()
    read_context = MagicMock()
    read_context.new_page = AsyncMock(return_value=read_page)
    read_context.close = AsyncMock()
    read_context.cookies = AsyncMock(return_value=[])
    read_context.route = AsyncMock()
    read_context.route_web_socket = None
    read_page.context = read_context
    read_browser = MagicMock()
    read_browser.new_context = AsyncMock(return_value=read_context)
    rules = MagicMock()
    rules.should_block.return_value = False

    # when
    assert await session_manager.validate("https://www.shop-site.com/inventory.html", "work") is True
    with (
        patch(
            "src.reader.strategies.playwright_strategy.browser_pool.get_browser",
            new=AsyncMock(return_value=read_browser),
        ),
        patch("src.reader.strategies.playwright_strategy.Stealth.apply_stealth_async", new=AsyncMock()),
    ):
        strategy = PlaywrightStrategy(lambda: "DefaultUA", URLValidator(rules), profile="work")
        await strategy.get_html("https://www.shop-site.com/inventory.html")

    # then
    replayed = read_browser.new_context.call_args.kwargs["storage_state"]
    assert {cookie["name"]: cookie["value"] for cookie in replayed["cookies"]} == {"session": "s1"}


def _local_storage(origin: str, name: str, value: str) -> dict[str, Any]:
    return {"origin": origin, "localStorage": [{"name": name, "value": value}]}


def _sample_value(metric_name: str, **labels: str) -> float:
    from prometheus_client import REGISTRY

    return REGISTRY.get_sample_value(metric_name, labels) or 0.0


def _monitor_outcomes(outcome: str) -> float:
    return _sample_value(
        "strategy_attempts_total", strategy="6-novnc-monitor", outcome=outcome, domain="shop-site.com"
    )


async def _establish_and_wait(
    url: str, profile: str, scripted: _ScriptedBrowser, timeout_seconds: float
) -> None:
    with (
        patch("src.reader.strategies.novnc_strategy.async_playwright", return_value=scripted.factory()),
        patch.object(settings, "NOVNC_TIMEOUT_SECONDS", timeout_seconds),
        patch.object(settings, "PUBLIC_VNC_URL", "http://vnc"),
        patch.object(settings, "NOVNC_PUBLIC_URL", None),
    ):
        await session_manager.establish(url, profile)
        [flow] = novnc_flow_registry.local()
        assert flow.task is not None
        await asyncio.wait_for(flow.task, timeout=5.0)


@pytest.mark.parametrize(
    ("cookies", "origins"),
    [
        pytest.param([_cookie("_ga", "GA1.2.3")], [], id="google-analytics-cookie"),
        pytest.param(
            [_cookie("_gid", "GA1.2.4"), _cookie("_gat_UA-1", "1")], [], id="google-session-cookies"
        ),
        pytest.param([_cookie("OptanonConsent", "groups=C0001")], [], id="consent-cookie"),
        pytest.param([_cookie("OptanonAlertBoxClosed", "2026-11-06")], [], id="consent-banner-cookie"),
        pytest.param([_cookie("CookieConsent", "yes"), _cookie("euconsent-v2", "CP")], [], id="tcf-consent"),
        pytest.param(
            [_cookie("_hjSessionUser_123", "h"), _cookie("_fbp", "fb.1")], [], id="hotjar-and-pixel"
        ),
        pytest.param([_cookie("IDE", "ad", domain=".doubleclick.net")], [], id="third-party-cookie"),
        pytest.param(
            [], [_local_storage("https://www.shop-site.com", "_hjid", "h1")], id="analytics-local-storage"
        ),
        pytest.param(
            [], [_local_storage("https://cdn.tracker.net", "token", "t1")], id="foreign-local-storage"
        ),
    ],
)
async def test_tracking_state_after_leaving_the_login_page_does_not_replace_a_stored_login(
    cookies: list[dict[str, Any]], origins: list[dict[str, Any]]
) -> None:
    # given
    url = "https://www.shop-site.com/"
    await _store_login(url, "work")
    stored = [_cookie("session", "LOGGED-IN")]
    scripted = _ScriptedBrowser(
        [
            _Step(url, _LOGIN_FORM, stored),
            _Step("https://www.shop-site.com/help", _ARTICLE, stored + cookies, origins),
        ]
    )
    save = AsyncMock(wraps=cookie_manager.save_storage_state)

    # when
    with patch("src.reader.strategies.novnc_strategy.cookie_manager.save_storage_state", new=save):
        await _run_monitor(_make_flow(url, "login", "work"), scripted, timeout_seconds=0.2)

    # then
    save.assert_not_awaited()
    assert await _stored_cookies(url, "work") == {"session": "LOGGED-IN"}


async def test_leaving_the_login_page_for_another_site_saves_nothing() -> None:
    # given
    url = "https://www.shop-site.com/"
    scripted = _ScriptedBrowser(
        [
            _Step(url, _LOGIN_FORM, []),
            _Step(
                "https://www.news-site.org/",
                _ARTICLE,
                [_cookie("reader", "r1", domain="www.news-site.org")],
                [_local_storage("https://www.news-site.org", "token", "t1")],
            ),
        ]
    )
    save = AsyncMock()

    # when
    with patch("src.reader.strategies.novnc_strategy.cookie_manager.save_storage_state", new=save):
        await _run_monitor(_make_flow(url, "login", "work"), scripted, timeout_seconds=0.2)

    # then
    save.assert_not_awaited()


async def test_a_site_cookie_on_another_site_page_is_not_a_login() -> None:
    """A new site cookie counts only once the window is back on a page of the site."""
    # given
    url = "https://www.shop-site.com/"
    scripted = _ScriptedBrowser(
        [
            _Step(url, _LOGIN_FORM, []),
            _Step("https://www.news-site.org/", _ARTICLE, [_cookie("session", "s1")]),
        ]
    )
    save = AsyncMock()

    # when
    with patch("src.reader.strategies.novnc_strategy.cookie_manager.save_storage_state", new=save):
        await _run_monitor(_make_flow(url, "login", "work"), scripted, timeout_seconds=0.2)

    # then
    save.assert_not_awaited()


async def test_a_login_wall_seen_only_on_another_site_saves_nothing() -> None:
    # given
    url = "https://www.shop-site.com/"
    scripted = _ScriptedBrowser(
        [
            _Step("https://www.news-site.org/account", _LOGIN_FORM, []),
            _Step("https://www.shop-site.com/home", _ARTICLE, [_cookie("session", "s1")]),
        ]
    )
    save = AsyncMock()

    # when
    with patch("src.reader.strategies.novnc_strategy.cookie_manager.save_storage_state", new=save):
        await _run_monitor(_make_flow(url, "login", "work"), scripted, timeout_seconds=0.2)

    # then
    save.assert_not_awaited()


async def test_a_real_login_saves_its_new_session_cookie_and_replaces_the_stored_login() -> None:
    """The login form, then the inventory page, then a new session cookie of the site."""
    # given
    url = "https://www.shop-site.com/"
    await _store_login(url, "work", value="OLD")
    scripted = _ScriptedBrowser(
        [
            _Step(url, _LOGIN_FORM, [_cookie("_ga", "GA1"), _cookie("session", "OLD")]),
            _Step(
                "https://www.shop-site.com/inventory.html",
                _ARTICLE,
                [
                    _cookie("_ga", "GA2"),
                    _cookie("session", "OLD"),
                    _cookie("session-username", "standard_user"),
                ],
            ),
        ]
    )
    save = AsyncMock(wraps=cookie_manager.save_storage_state)
    resolved_before = _monitor_outcomes("resolved")

    # when
    with patch("src.reader.strategies.novnc_strategy.cookie_manager.save_storage_state", new=save):
        await _run_monitor(_make_flow(url, "login", "work"), scripted, timeout_seconds=2.0)

    # then
    assert save.await_count == 1
    assert save.await_args is not None
    assert save.await_args.kwargs["replaces_login"] is True
    assert await _stored_cookies(url, "work") == {
        "_ga": "GA2",
        "session": "OLD",
        "session-username": "standard_user",
    }
    assert _monitor_outcomes("resolved") == resolved_before + 1.0


async def test_a_local_storage_only_login_is_saved_with_its_origin() -> None:
    # given
    url = "https://www.shop-site.com/"
    origin = "https://www.shop-site.com"
    scripted = _ScriptedBrowser(
        [
            _Step(url, _LOGIN_FORM, [], [_local_storage(origin, "theme", "dark")]),
            _Step(
                "https://www.shop-site.com/inventory.html",
                _ARTICLE,
                [],
                [
                    {
                        "origin": origin,
                        "localStorage": [
                            {"name": "theme", "value": "dark"},
                            {"name": "auth", "value": "jwt"},
                        ],
                    }
                ],
            ),
        ]
    )
    save = AsyncMock()

    # when
    with patch("src.reader.strategies.novnc_strategy.cookie_manager.save_storage_state", new=save):
        await _run_monitor(_make_flow(url, "login", "work"), scripted, timeout_seconds=2.0)

    # then
    save.assert_awaited_once()
    assert save.await_args is not None
    saved_state = save.await_args.args[1]
    assert saved_state["origins"][0]["localStorage"][1] == {"name": "auth", "value": "jwt"}
    assert save.await_args.kwargs["replaces_login"] is True


async def test_a_changed_local_storage_entry_after_the_login_page_is_a_login() -> None:
    # given
    url = "https://www.shop-site.com/"
    origin = "https://www.shop-site.com"
    scripted = _ScriptedBrowser(
        [
            _Step(url, _LOGIN_FORM, [], [_local_storage(origin, "auth", "anonymous")]),
            _Step(
                "https://www.shop-site.com/inventory.html",
                _ARTICLE,
                [],
                [_local_storage(origin, "auth", "jwt")],
            ),
        ]
    )
    save = AsyncMock()

    # when
    with patch("src.reader.strategies.novnc_strategy.cookie_manager.save_storage_state", new=save):
        await _run_monitor(_make_flow(url, "login", "work"), scripted, timeout_seconds=2.0)

    # then
    save.assert_awaited_once()


async def test_an_establish_on_a_site_already_logged_in_ends_at_once_and_keeps_the_login() -> None:
    # given
    url = "https://www.shop-site.com/inventory.html"
    await _store_login(url, "work")
    saved_at = await cookie_manager.get_auth_saved_at(url, "work")
    scripted = _ScriptedBrowser(
        [_Step(url, _ARTICLE, [_cookie("session", "LOGGED-IN"), _cookie("cart", "1")])]
    )
    save = AsyncMock()
    already_before = _monitor_outcomes("already_authenticated")

    # when
    with patch("src.reader.strategies.novnc_strategy.cookie_manager.save_storage_state", new=save):
        await _establish_and_wait(url, "work", scripted, timeout_seconds=30.0)

    # then
    save.assert_not_awaited()
    assert scripted.index == 1
    assert novnc_flow_registry.local() == []
    assert await novnc_flow_registry.find(flow_key_for(url, "work")) is None
    assert scripted.browser.close.await_count == 1
    assert await _stored_cookies(url, "work") == {"session": "LOGGED-IN"}
    assert await cookie_manager.get_auth_saved_at(url, "work") == saved_at
    assert _monitor_outcomes("already_authenticated") == already_before + 1.0
    assert (await session_manager.status(url, "work")).status == "active"


@pytest.mark.parametrize(
    ("produced_by", "replaces_login"),
    [
        pytest.param(PRODUCED_BY_IMPORT, True, id="import"),
        pytest.param(PRODUCED_BY_LOGIN_SEED, False, id="login-seed"),
    ],
)
async def test_an_establish_over_an_imported_or_seeded_login_ends_at_once(
    produced_by: str, replaces_login: bool
) -> None:
    # given
    url = "https://www.shop-site.com/inventory.html"
    await cookie_manager.save_storage_state(
        url,
        {"cookies": [_cookie("session", "LOGGED-IN")], "origins": []},
        "UA/stored",
        "work",
        produced_by,
        replaces_login=replaces_login,
    )
    scripted = _ScriptedBrowser([_Step(url, _ARTICLE, [_cookie("session", "LOGGED-IN")])])
    already_before = _monitor_outcomes("already_authenticated")

    # when
    await _establish_and_wait(url, "work", scripted, timeout_seconds=30.0)

    # then
    assert scripted.index == 1
    assert _monitor_outcomes("already_authenticated") == already_before + 1.0


async def test_a_stored_captcha_clearance_does_not_end_a_login_establish() -> None:
    # given
    url = "https://www.shop-site.com/inventory.html"
    clearance = [_cookie("session", "ANON"), _cookie("cf_clearance", "CLEARED")]
    await cookie_manager.save_storage_state(
        url, {"cookies": clearance, "origins": []}, "UA/stored", "work", PRODUCED_BY_NOVNC
    )
    scripted = _ScriptedBrowser([_Step(url, _ARTICLE, clearance)])
    already_before = _monitor_outcomes("already_authenticated")
    timeouts_before = _monitor_outcomes("timeout")

    # when
    await _establish_and_wait(url, "work", scripted, timeout_seconds=0.2)

    # then
    assert scripted.index > 2
    assert _monitor_outcomes("already_authenticated") == already_before
    assert _monitor_outcomes("timeout") == timeouts_before + 1.0


async def test_an_already_logged_in_window_waits_for_the_page_to_render_before_ending() -> None:
    """A blank first render is neither a login wall nor content, so the flow waits for the next poll."""
    # given
    url = "https://www.shop-site.com/inventory.html"
    await _store_login(url, "work")
    stored = [_cookie("session", "LOGGED-IN")]
    scripted = _ScriptedBrowser(
        [
            _Step(url, "<html><head></head><body><div id='root'></div></body></html>", stored),
            _Step(url, _ARTICLE, stored),
        ]
    )

    # when
    await _run_monitor(_make_flow(url, "login", "work"), scripted, timeout_seconds=30.0)

    # then
    assert scripted.index == 2


async def test_a_stored_login_that_meets_a_login_wall_waits_for_the_human() -> None:
    # given
    url = "https://www.shop-site.com/inventory.html"
    await _store_login(url, "work")
    stored = [_cookie("session", "LOGGED-IN")]
    scripted = _ScriptedBrowser([_Step(url, _LOGIN_FORM, stored), _Step(url, _ARTICLE, stored)])
    timeouts_before = _monitor_outcomes("timeout")

    # when
    await _run_monitor(_make_flow(url, "login", "work"), scripted, timeout_seconds=0.2)

    # then
    assert scripted.index > 2
    assert _monitor_outcomes("timeout") == timeouts_before + 1.0
    assert await _stored_cookies(url, "work") == {"session": "LOGGED-IN"}


async def test_an_ordinary_first_page_without_a_stored_login_keeps_the_window_open() -> None:
    # given
    url = "https://www.shop-site.com/"
    scripted = _ScriptedBrowser([_Step(url, _ARTICLE, [_cookie("cart", "1")])])
    timeouts_before = _monitor_outcomes("timeout")

    # when
    await _run_monitor(_make_flow(url, "login", "work"), scripted, timeout_seconds=0.2)

    # then
    assert scripted.index > 2
    assert _monitor_outcomes("timeout") == timeouts_before + 1.0


def _verdict_count(verdict: str) -> float:
    return _sample_value("challenge_verdicts_total", verdict=verdict, tier="novnc-monitor")


def _all_verdicts() -> float:
    return _verdict_count("wall") + _verdict_count("content") + _verdict_count("no_content")


async def test_the_session_status_names_the_already_authenticated_window() -> None:
    # given
    url = "https://www.shop-site.com/inventory.html"
    await _store_login(url, "work")
    scripted = _ScriptedBrowser([_Step(url, _ARTICLE, [_cookie("session", "LOGGED-IN")])])

    # when
    with patch("src.reader.strategies.novnc_strategy.cookie_manager.save_storage_state", new=AsyncMock()):
        await _establish_and_wait(url, "work", scripted, timeout_seconds=30.0)
    info = await session_manager.status(url, "work")

    # then
    last_window = info.to_dict()["last_window"]
    assert isinstance(last_window, dict)
    assert last_window["outcome"] == "already_authenticated"
    assert last_window["intervention_type"] == "login"
    assert isinstance(last_window["flow_id"], str)
    assert len(last_window["flow_id"]) == 12
    assert isinstance(last_window["finished_at"], float)


async def test_an_establish_on_a_local_storage_only_login_ends_as_already_authenticated() -> None:
    # given
    url = "https://www.shop-site.com/inventory.html"
    origin = "https://www.shop-site.com"
    await cookie_manager.save_storage_state(
        url,
        {"cookies": [], "origins": [_local_storage(origin, "auth", "jwt")]},
        "UA/stored",
        "work",
        PRODUCED_BY_NOVNC,
        replaces_login=True,
    )
    scripted = _ScriptedBrowser([_Step(url, _ARTICLE, [], [_local_storage(origin, "auth", "jwt")])])
    already_before = _monitor_outcomes("already_authenticated")

    # when
    with patch("src.reader.strategies.novnc_strategy.cookie_manager.save_storage_state", new=AsyncMock()):
        await _establish_and_wait(url, "work", scripted, timeout_seconds=30.0)

    # then
    assert _monitor_outcomes("already_authenticated") == already_before + 1.0
    assert (await session_manager.status(url, "work")).status == "active"


async def test_a_window_counts_one_verdict_however_often_it_rechecks_the_page() -> None:
    # given
    url = "https://www.shop-site.com/"
    scripted = _ScriptedBrowser(
        [
            _Step(url, _LOGIN_FORM, []),
            _Step(url, _LOGIN_FORM, []),
            _Step(url, _LOGIN_FORM, []),
            _Step("https://www.shop-site.com/inventory.html", _ARTICLE, [_cookie("session", "NEW")]),
        ]
    )
    before = _all_verdicts()

    # when
    with patch("src.reader.strategies.novnc_strategy.cookie_manager.save_storage_state", new=AsyncMock()):
        await _run_monitor(_make_flow(url, "login", "work"), scripted, timeout_seconds=2.0)

    # then
    assert scripted.index >= 4
    assert _all_verdicts() == before + 1.0


async def test_a_window_counts_its_final_verdict() -> None:
    # given
    url = "https://www.shop-site.com/"
    scripted = _ScriptedBrowser(
        [
            _Step(url, _LOGIN_FORM, []),
            _Step("https://www.shop-site.com/inventory.html", _ARTICLE, [_cookie("session", "NEW")]),
        ]
    )
    content_before = _verdict_count("content")
    others_before = _verdict_count("wall") + _verdict_count("no_content")

    # when
    with patch("src.reader.strategies.novnc_strategy.cookie_manager.save_storage_state", new=AsyncMock()):
        await _run_monitor(_make_flow(url, "login", "work"), scripted, timeout_seconds=2.0)

    # then
    assert _verdict_count("content") == content_before + 1.0
    assert _verdict_count("wall") + _verdict_count("no_content") == others_before


_HEADER_ONLY_WALL = "<html><head><title>Shop</title></head><body><p>One moment.</p></body></html>"

_CHALLENGE_HEADERS = {"cf-mitigated": "challenge"}


async def test_a_window_on_a_header_only_wall_ends_with_a_wall_verdict() -> None:
    """The window's checks read the status and headers of the page's main-frame response."""
    # given
    url = "https://www.shop-site.com/"
    scripted = _ScriptedBrowser([_Step(url, _HEADER_ONLY_WALL, [])])
    scripted.page.goto = AsyncMock(return_value=_main_frame_response(403, _CHALLENGE_HEADERS))
    walls_before = _verdict_count("wall")
    others_before = _verdict_count("content") + _verdict_count("no_content")

    # when
    await _run_monitor(_make_flow(url, "captcha", "work"), scripted, timeout_seconds=0.2)

    # then
    assert scripted.index >= 1
    assert _verdict_count("wall") == walls_before + 1.0
    assert _verdict_count("content") + _verdict_count("no_content") == others_before


async def test_a_window_judges_its_last_check_with_the_latest_main_frame_response() -> None:
    """A later main-frame navigation replaces the first response the window saw."""
    # given
    url = "https://www.shop-site.com/"
    scripted = _ScriptedBrowser(
        [
            _Step(url, _ARTICLE, [], main_frame=(200, {})),
            _Step(url, _ARTICLE, [], main_frame=(403, _CHALLENGE_HEADERS)),
        ]
    )
    walls_before = _verdict_count("wall")
    others_before = _verdict_count("content") + _verdict_count("no_content")

    # when
    await _run_monitor(_make_flow(url, "login", "work"), scripted, timeout_seconds=0.2)

    # then
    assert scripted.index >= 2
    assert _verdict_count("wall") == walls_before + 1.0
    assert _verdict_count("content") + _verdict_count("no_content") == others_before


async def test_a_window_that_never_checked_a_page_counts_no_verdict() -> None:
    # given
    url = "https://www.shop-site.com/"
    scripted = _ScriptedBrowser([_Step(url, _ARTICLE, [])])
    scripted.browser.is_connected = MagicMock(return_value=False)
    before = _all_verdicts()

    # when
    await _run_monitor(_make_flow(url, "login", "work"), scripted, timeout_seconds=2.0)

    # then
    assert scripted.index == 0
    assert _all_verdicts() == before


async def test_a_close_asked_by_another_copy_ends_the_window_as_cancelled_and_saves_nothing() -> None:
    # given
    url = "https://www.shop-site.com/"
    scripted = _ScriptedBrowser(
        [
            _Step(url, _LOGIN_FORM, []),
            _Step("https://www.shop-site.com/inventory.html", _ARTICLE, [_cookie("session", "NEW")]),
        ]
    )
    flow = _make_flow(url, "login", "work")
    novnc_flow_registry._local[flow.flow_id] = flow
    flow.settled.set()
    client = novnc_flow_registry._client()
    assert client is not None
    await client.set(f"novnc_flow_cancel:{flow.flow_id}", "1", px=60_000)
    save = AsyncMock()
    cancelled_before = _monitor_outcomes("cancelled")

    # when
    with patch("src.reader.strategies.novnc_strategy.cookie_manager.save_storage_state", new=save):
        await _run_monitor(flow, scripted, timeout_seconds=2.0)

    # then
    save.assert_not_awaited()
    assert scripted.index == 0
    assert scripted.browser.close.await_count == 1
    assert novnc_flow_registry.local() == []
    assert _monitor_outcomes("cancelled") == cancelled_before + 1.0
    result = await novnc_flow_registry.last_result(flow.key)
    assert result is not None
    assert (result.flow_id, result.outcome) == (flow.flow_id, "cancelled")


def _metric_total(sample_name: str) -> float:
    from prometheus_client import REGISTRY

    return sum(
        sample.value
        for family in REGISTRY.collect()
        for sample in family.samples
        if sample.name == sample_name
    )


async def test_a_window_records_score_and_signals_once_from_its_last_check() -> None:
    # given
    from src.reader.cloudflare.challenge_signals import assess

    url = "https://www.shop-site.com/"
    final_cookies = [_cookie("session", "NEW")]
    final_signals = len(assess(200, _ARTICLE, None, ["session"]).signals)
    scripted = _ScriptedBrowser(
        [
            _Step(url, _LOGIN_FORM, []),
            _Step(url, _LOGIN_FORM, []),
            _Step(url, _LOGIN_FORM, []),
            _Step("https://www.shop-site.com/inventory.html", _ARTICLE, final_cookies),
        ]
    )
    scores_before = _metric_total("challenge_score_count")
    signals_before = _metric_total("challenge_signals_fired_total")

    # when
    with patch("src.reader.strategies.novnc_strategy.cookie_manager.save_storage_state", new=AsyncMock()):
        await _run_monitor(_make_flow(url, "login", "work"), scripted, timeout_seconds=2.0)

    # then
    assert scripted.index >= 4
    assert _metric_total("challenge_score_count") == scores_before + 1.0
    assert _metric_total("challenge_signals_fired_total") == signals_before + final_signals


async def test_a_window_that_never_checked_a_page_records_no_score() -> None:
    # given
    url = "https://www.shop-site.com/"
    scripted = _ScriptedBrowser([_Step(url, _ARTICLE, [])])
    scripted.browser.is_connected = MagicMock(return_value=False)
    scores_before = _metric_total("challenge_score_count")

    # when
    await _run_monitor(_make_flow(url, "login", "work"), scripted, timeout_seconds=2.0)

    # then
    assert _metric_total("challenge_score_count") == scores_before


@pytest.mark.parametrize(
    "content",
    [
        pytest.param(_HIDDEN_PASSWORD_ARTICLE, id="hidden-form"),
        pytest.param(
            _ARTICLE.replace(
                "<article>", "<noscript><input type='password' name='password'></noscript><article>"
            ),
            id="noscript",
        ),
        pytest.param(
            _ARTICLE.replace(
                "<article>", "<template><input type='password' name='password'></template><article>"
            ),
            id="template",
        ),
        pytest.param(
            _ARTICLE.replace("<article>", "<script>const f = \"<input type='password'>\";</script><article>"),
            id="script-text",
        ),
    ],
)
async def test_a_finished_login_whose_page_keeps_only_an_invisible_password_input_resolves(
    content: str,
) -> None:
    # given
    url = "https://www.shop-site.com/"
    scripted = _ScriptedBrowser(
        [
            _Step(url, _LOGIN_FORM, [_cookie("csrf", "c1")]),
            _Step(
                "https://www.shop-site.com/home", content, [_cookie("csrf", "c1"), _cookie("session", "s14")]
            ),
        ]
    )

    # when
    await _run_monitor(_make_flow(url, "login", "default"), scripted, timeout_seconds=2.0)

    # then
    assert await _stored_cookies(url, "default") == {"csrf": "c1", "session": "s14"}
    assert scripted.probed_selectors == ["input[type=password]:visible", "input[type=password]:visible"]


_SIGNED_SITE = "https://www.shop-site.com/?X-Amz-Signature=secret"


async def test_a_solved_captcha_logs_no_signature(caplog: pytest.LogCaptureFixture) -> None:
    # given
    scripted = _ScriptedBrowser([_Step(_SIGNED_SITE, _ARTICLE, [_cookie("cf_clearance", "solved")])])
    caplog.set_level(logging.DEBUG)

    # when
    await _run_monitor(_make_flow(_SIGNED_SITE, "captcha", "work"), scripted)

    # then
    assert "captcha solved for https://www.shop-site.com/ " in caplog.text
    assert "Background task started to monitor session for https://www.shop-site.com/ " in caplog.text
    assert "X-Amz-Signature" not in caplog.text


async def test_a_site_already_logged_in_logs_no_signature(caplog: pytest.LogCaptureFixture) -> None:
    # given
    await _store_login(_SIGNED_SITE, "work")
    scripted = _ScriptedBrowser([_Step(_SIGNED_SITE, _ARTICLE, [])])
    caplog.set_level(logging.DEBUG)

    # when
    await _run_monitor(_make_flow(_SIGNED_SITE, "login", "work"), scripted, timeout_seconds=2.0)

    # then
    assert "https://www.shop-site.com/ is already logged in" in caplog.text
    assert "X-Amz-Signature" not in caplog.text


async def test_a_timed_out_window_logs_no_signature(caplog: pytest.LogCaptureFixture) -> None:
    # given
    scripted = _ScriptedBrowser([_Step(_SIGNED_SITE, _LOGIN_FORM, [])])
    caplog.set_level(logging.DEBUG)

    # when
    await _run_monitor(_make_flow(_SIGNED_SITE, "login", "work"), scripted, timeout_seconds=0.05)

    # then
    assert "intervention for https://www.shop-site.com/ timed out" in caplog.text
    assert "X-Amz-Signature" not in caplog.text


def test_a_closed_browser_logs_no_signature(caplog: pytest.LogCaptureFixture) -> None:
    # given
    caplog.set_level(logging.DEBUG)

    # when
    _log_browser_closed(_make_flow(_SIGNED_SITE, "login", "work"), _BROWSER_GONE_OUTCOME)

    # then
    assert "browser closed for https://www.shop-site.com/ " in caplog.text
    assert "X-Amz-Signature" not in caplog.text


async def test_the_login_resolved_log_line_carries_no_query_fragment_or_user_info(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # given
    url = "https://reader:hunter2@www.shop-site.com/"
    callback = "https://www.shop-site.com/oauth/callback?code=SECRET#access_token=SECRET"
    scripted = _ScriptedBrowser(
        [
            _Step(url, _LOGIN_FORM, []),
            _Step(callback, _ARTICLE, [_cookie("session", "s15")]),
        ]
    )
    caplog.set_level(logging.DEBUG)

    # when
    await _run_monitor(_make_flow(url, "login", "default"), scripted, timeout_seconds=2.0)

    # then
    assert await _stored_cookies(url, "default") == {"session": "s15"}
    assert "login resolved (now at https://www.shop-site.com/oauth/callback)" in caplog.text
    assert "SECRET" not in caplog.text
    assert "hunter2" not in caplog.text

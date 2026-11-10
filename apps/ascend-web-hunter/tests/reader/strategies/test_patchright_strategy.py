"""Tests for PatchrightStrategy (task 2.1)."""

from contextlib import ExitStack, contextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from ascend_python_common.uri_guard import UnsafeUriError
from patchright.async_api import Error as PatchrightError

from src.api.exceptions import ChallengeDetectedException
from src.reader.cloudflare.challenge_signals import ChallengeVerdict
from src.reader.strategies.patchright_strategy import PatchrightStrategy
from src.validator.url_validator import URLValidator

_CLEAN_HTML = "<html><body><article><p>" + "word " * 30 + "</p></article></body></html>"


def _make_url_validator() -> URLValidator:
    rules = MagicMock()
    rules.should_block.return_value = False
    return URLValidator(rules)


def _accepted_verdict() -> ChallengeVerdict:
    return ChallengeVerdict(
        score=0,
        threshold=100,
        signals=(),
        vendor=None,
        wall=False,
        has_content=True,
        intervention_type="captcha",
    )


def _wall_verdict(intervention_type: str = "captcha") -> ChallengeVerdict:
    return ChallengeVerdict(
        score=200,
        threshold=100,
        signals=(),
        vendor="cloudflare",
        wall=True,
        has_content=False,
        intervention_type=intervention_type,
    )


def _make_page(html: str = _CLEAN_HTML) -> MagicMock:
    goto_response = MagicMock(status=200)
    goto_response.all_headers = AsyncMock(return_value={})
    page = MagicMock()
    page.goto = AsyncMock(return_value=goto_response)
    page.content = AsyncMock(return_value=html)
    page.url = "https://example.com/page"
    page.wait_for_load_state = AsyncMock()
    page.wait_for_timeout = AsyncMock()
    page.evaluate = AsyncMock(return_value=0)
    page.route = AsyncMock()

    return page


def _make_browser(page: MagicMock) -> tuple[MagicMock, MagicMock]:
    context = MagicMock()
    context.new_page = AsyncMock(return_value=page)
    context.close = AsyncMock()
    context.cookies = AsyncMock(return_value=[])
    context.storage_state = AsyncMock(return_value={"cookies": [], "origins": []})
    context.route = AsyncMock()
    context.route_web_socket = None
    page.context = context

    browser = MagicMock()
    browser.new_context = AsyncMock(return_value=context)
    browser.close = AsyncMock()

    return browser, context


def _make_playwright(browser: MagicMock) -> MagicMock:
    playwright = MagicMock()
    playwright.chromium.launch = AsyncMock(return_value=browser)
    entered = MagicMock()
    entered.__aenter__ = AsyncMock(return_value=playwright)
    entered.__aexit__ = AsyncMock(return_value=False)

    return entered


@contextmanager
def _base_patches(browser: MagicMock, entered: MagicMock) -> Any:
    with ExitStack() as stack:
        stack.enter_context(
            patch(
                "src.reader.strategies.patchright_strategy.async_playwright",
                return_value=entered,
            )
        )
        stack.enter_context(
            patch(
                "src.reader.strategies.patchright_strategy.cookie_manager.get_storage_state",
                new=AsyncMock(return_value=None),
            )
        )
        stack.enter_context(
            patch(
                "src.reader.strategies.patchright_strategy.cookie_manager.get_user_agent",
                new=AsyncMock(return_value=None),
            )
        )
        stack.enter_context(
            patch(
                "src.reader.strategies.patchright_strategy.proxy_provider.for_playwright",
                return_value=None,
            )
        )
        stack.enter_context(
            patch(
                "src.reader.strategies.browser_read.ChallengeDetector.is_login_redirect_url",
                return_value=False,
            )
        )
        stack.enter_context(
            patch(
                "src.reader.strategies.browser_read.assess",
                return_value=_accepted_verdict(),
            )
        )
        yield


@pytest.mark.asyncio
async def test_patchright_replays_storage_state_and_returns_html() -> None:
    """Stored state is replayed into the context and a clean page returns its HTML."""
    # given
    stored_state: dict[str, Any] = {
        "cookies": [{"name": "li_at", "value": "TOKEN", "domain": ".linkedin.com", "path": "/"}],
        "origins": [],
    }
    page = _make_page()
    browser, context = _make_browser(page)
    entered = _make_playwright(browser)

    # when
    with (
        patch(
            "src.reader.strategies.patchright_strategy.async_playwright",
            return_value=entered,
        ),
        patch(
            "src.reader.strategies.patchright_strategy.cookie_manager.get_storage_state",
            new=AsyncMock(return_value=stored_state),
        ),
        patch(
            "src.reader.strategies.patchright_strategy.cookie_manager.get_user_agent",
            new=AsyncMock(return_value="UA/1.0"),
        ),
        patch(
            "src.reader.strategies.patchright_strategy.proxy_provider.for_playwright",
            return_value=None,
        ),
        patch(
            "src.reader.strategies.browser_read.ChallengeDetector.is_login_redirect_url",
            return_value=False,
        ),
        patch(
            "src.reader.strategies.browser_read.assess",
            return_value=_accepted_verdict(),
        ),
    ):
        strategy = PatchrightStrategy(lambda: "DefaultUA", _make_url_validator())
        html = await strategy.get_html("https://linkedin.com/feed")

    # then
    assert html == _CLEAN_HTML
    call_kwargs = browser.new_context.call_args.kwargs
    assert call_kwargs["storage_state"] == stored_state
    assert call_kwargs["user_agent"] == "UA/1.0"
    context.close.assert_awaited_once()
    browser.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_patchright_omits_storage_state_when_absent() -> None:
    """Without a stored session the browser keeps its own user agent and gets no storage_state."""
    # given
    page = _make_page()
    browser, _ = _make_browser(page)
    entered = _make_playwright(browser)

    # when
    with _base_patches(browser, entered):
        strategy = PatchrightStrategy(lambda: "DefaultUA", _make_url_validator())
        await strategy.get_html("https://example.com")

    # then
    call_kwargs = browser.new_context.call_args.kwargs
    assert "storage_state" not in call_kwargs
    assert "user_agent" not in call_kwargs


@pytest.mark.asyncio
async def test_patchright_wall_verdict_raises() -> None:
    """A wall verdict past the challenge deadline raises ChallengeDetectedException."""
    # given
    page = _make_page()
    browser, _ = _make_browser(page)
    entered = _make_playwright(browser)

    # when / then
    with (
        patch(
            "src.reader.strategies.patchright_strategy.async_playwright",
            return_value=entered,
        ),
        patch(
            "src.reader.strategies.patchright_strategy.cookie_manager.get_storage_state",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "src.reader.strategies.patchright_strategy.cookie_manager.get_user_agent",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "src.reader.strategies.patchright_strategy.proxy_provider.for_playwright",
            return_value=None,
        ),
        patch(
            "src.reader.strategies.browser_read.ChallengeDetector.is_login_redirect_url",
            return_value=False,
        ),
        patch(
            "src.reader.strategies.browser_read.assess",
            return_value=_wall_verdict(),
        ),
        patch("src.reader.strategies.patchright_strategy.settings.CHALLENGE_CLEAR_WAIT_SECONDS", 0),
    ):
        strategy = PatchrightStrategy(lambda: "DefaultUA", _make_url_validator())
        with pytest.raises(ChallengeDetectedException):
            await strategy.get_html("https://example.com")


@pytest.mark.asyncio
async def test_patchright_login_wall_early_exit_raises() -> None:
    """A login wall verdict raises at once, without waiting for the challenge deadline."""
    # given
    page = _make_page()
    browser, _ = _make_browser(page)
    entered = _make_playwright(browser)

    # when / then
    with (
        patch(
            "src.reader.strategies.patchright_strategy.async_playwright",
            return_value=entered,
        ),
        patch(
            "src.reader.strategies.patchright_strategy.cookie_manager.get_storage_state",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "src.reader.strategies.patchright_strategy.cookie_manager.get_user_agent",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "src.reader.strategies.patchright_strategy.proxy_provider.for_playwright",
            return_value=None,
        ),
        patch(
            "src.reader.strategies.browser_read.ChallengeDetector.is_login_redirect_url",
            return_value=False,
        ),
        patch(
            "src.reader.strategies.browser_read.assess",
            return_value=_wall_verdict("login"),
        ),
    ):
        strategy = PatchrightStrategy(lambda: "DefaultUA", _make_url_validator())
        with pytest.raises(ChallengeDetectedException):
            await strategy.get_html("https://example.com")


@pytest.mark.asyncio
async def test_patchright_login_redirect_url_raises_before_navigation() -> None:
    """A login redirect URL raises before the first navigation runs."""
    # given
    page = _make_page()
    browser, _ = _make_browser(page)
    entered = _make_playwright(browser)

    # when / then
    with (
        patch(
            "src.reader.strategies.patchright_strategy.async_playwright",
            return_value=entered,
        ),
        patch(
            "src.reader.strategies.patchright_strategy.cookie_manager.get_storage_state",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "src.reader.strategies.patchright_strategy.cookie_manager.get_user_agent",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "src.reader.strategies.patchright_strategy.proxy_provider.for_playwright",
            return_value=None,
        ),
        patch(
            "src.reader.strategies.browser_read.ChallengeDetector.is_login_redirect_url",
            return_value=True,
        ),
        patch(
            "src.reader.strategies.browser_read.assess",
            return_value=_accepted_verdict(),
        ),
    ):
        strategy = PatchrightStrategy(lambda: "DefaultUA", _make_url_validator())
        with pytest.raises(ChallengeDetectedException):
            await strategy.get_html("https://example.com/login?continue=/feed")

    page.goto.assert_not_awaited()


@pytest.mark.asyncio
async def test_patchright_content_error_retries_poll() -> None:
    """A content read error waits and polls again instead of failing the tier."""
    # given
    page = _make_page()
    page.content = AsyncMock(side_effect=[PatchrightError("boom"), _CLEAN_HTML, _CLEAN_HTML])
    browser, _ = _make_browser(page)
    entered = _make_playwright(browser)

    # when
    with _base_patches(browser, entered):
        strategy = PatchrightStrategy(lambda: "DefaultUA", _make_url_validator())
        html = await strategy.get_html("https://example.com")

    # then
    assert html == _CLEAN_HTML
    assert page.content.await_count == 3


@pytest.mark.asyncio
async def test_patchright_networkidle_error_keeps_polling() -> None:
    """A networkidle wait error falls through to the next poll iteration."""
    # given
    page = _make_page()
    page.wait_for_load_state = AsyncMock(side_effect=[PatchrightError("busy"), None])
    browser, _ = _make_browser(page)
    entered = _make_playwright(browser)

    # when
    with _base_patches(browser, entered):
        strategy = PatchrightStrategy(lambda: "DefaultUA", _make_url_validator())
        html = await strategy.get_html("https://example.com")

    # then
    assert html == _CLEAN_HTML
    assert page.wait_for_load_state.await_count == 2


@pytest.mark.asyncio
async def test_patchright_late_login_wall_raises() -> None:
    """A login wall found only after rendering raises."""
    # given
    page = _make_page()
    browser, _ = _make_browser(page)
    entered = _make_playwright(browser)

    # when / then
    with (
        patch(
            "src.reader.strategies.patchright_strategy.async_playwright",
            return_value=entered,
        ),
        patch(
            "src.reader.strategies.patchright_strategy.cookie_manager.get_storage_state",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "src.reader.strategies.patchright_strategy.cookie_manager.get_user_agent",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "src.reader.strategies.patchright_strategy.proxy_provider.for_playwright",
            return_value=None,
        ),
        patch(
            "src.reader.strategies.browser_read.ChallengeDetector.is_login_redirect_url",
            return_value=False,
        ),
        patch(
            "src.reader.strategies.browser_read.assess",
            side_effect=[_accepted_verdict(), _wall_verdict("login")],
        ),
    ):
        strategy = PatchrightStrategy(lambda: "DefaultUA", _make_url_validator())
        with pytest.raises(ChallengeDetectedException):
            await strategy.get_html("https://example.com")


@pytest.mark.asyncio
async def test_patchright_post_render_block_raises() -> None:
    """A wall found only after rendering raises even without a login type."""
    # given
    page = _make_page()
    browser, _ = _make_browser(page)
    entered = _make_playwright(browser)

    # when / then
    with (
        patch(
            "src.reader.strategies.patchright_strategy.async_playwright",
            return_value=entered,
        ),
        patch(
            "src.reader.strategies.patchright_strategy.cookie_manager.get_storage_state",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "src.reader.strategies.patchright_strategy.cookie_manager.get_user_agent",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "src.reader.strategies.patchright_strategy.proxy_provider.for_playwright",
            return_value=None,
        ),
        patch(
            "src.reader.strategies.browser_read.ChallengeDetector.is_login_redirect_url",
            return_value=False,
        ),
        patch(
            "src.reader.strategies.browser_read.assess",
            side_effect=[_accepted_verdict(), _wall_verdict()],
        ),
    ):
        strategy = PatchrightStrategy(lambda: "DefaultUA", _make_url_validator())
        with pytest.raises(ChallengeDetectedException):
            await strategy.get_html("https://example.com")


@pytest.mark.asyncio
async def test_patchright_initial_navigation_without_response() -> None:
    """A navigation without a response object defaults to status 200 and empty headers."""
    # given
    page = _make_page()
    page.goto = AsyncMock(return_value=None)
    browser, _ = _make_browser(page)
    entered = _make_playwright(browser)

    # when
    with _base_patches(browser, entered):
        strategy = PatchrightStrategy(lambda: "DefaultUA", _make_url_validator())
        html = await strategy.get_html("https://example.com")

    # then
    assert html == _CLEAN_HTML


@pytest.mark.asyncio
async def test_patchright_passes_proxy_to_context() -> None:
    """A configured proxy reaches the browser context."""
    # given
    page = _make_page()
    browser, _ = _make_browser(page)
    entered = _make_playwright(browser)

    # when
    with (
        patch(
            "src.reader.strategies.patchright_strategy.async_playwright",
            return_value=entered,
        ),
        patch(
            "src.reader.strategies.patchright_strategy.cookie_manager.get_storage_state",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "src.reader.strategies.patchright_strategy.cookie_manager.get_user_agent",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "src.reader.strategies.patchright_strategy.proxy_provider.for_playwright",
            return_value={"server": "socks5://proxy:1080"},
        ),
        patch(
            "src.reader.strategies.browser_read.ChallengeDetector.is_login_redirect_url",
            return_value=False,
        ),
        patch(
            "src.reader.strategies.browser_read.assess",
            return_value=_accepted_verdict(),
        ),
    ):
        strategy = PatchrightStrategy(lambda: "DefaultUA", _make_url_validator())
        await strategy.get_html("https://example.com")

    # then
    assert browser.new_context.call_args.kwargs["proxy"] == {"server": "chained:socks5://proxy:1080"}


@pytest.mark.asyncio
async def test_patchright_wall_retry_then_deadline_exit_returns_render() -> None:
    """A wall inside the deadline waits and retries; the loop deadline still ends the poll."""
    # given
    page = _make_page()
    browser, _ = _make_browser(page)
    entered = _make_playwright(browser)
    calls = {"n": 0}

    def _assess_seq(*args: Any, **kwargs: Any) -> ChallengeVerdict:
        calls["n"] += 1
        if calls["n"] == 1:
            return _wall_verdict()

        return _accepted_verdict()

    # when
    with (
        patch(
            "src.reader.strategies.patchright_strategy.async_playwright",
            return_value=entered,
        ),
        patch(
            "src.reader.strategies.patchright_strategy.cookie_manager.get_storage_state",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "src.reader.strategies.patchright_strategy.cookie_manager.get_user_agent",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "src.reader.strategies.patchright_strategy.proxy_provider.for_playwright",
            return_value=None,
        ),
        patch(
            "src.reader.strategies.browser_read.ChallengeDetector.is_login_redirect_url",
            return_value=False,
        ),
        patch(
            "src.reader.strategies.browser_read.assess",
            side_effect=_assess_seq,
        ),
        patch("src.reader.strategies.patchright_strategy.settings.EXTRACT_TIMEOUT", 0.05),
        patch(
            "src.reader.strategies.patchright_strategy.settings.CHALLENGE_CLEAR_WAIT_SECONDS",
            60.0,
        ),
    ):
        strategy = PatchrightStrategy(lambda: "DefaultUA", _make_url_validator())
        html = await strategy.get_html("https://example.com")

    # then
    assert html == _CLEAN_HTML
    assert calls["n"] >= 2


@pytest.mark.asyncio
async def test_patchright_zero_budget_skips_poll_and_returns_render() -> None:
    """A zero read budget skips the poll loop and still checks the rendered page."""
    # given
    page = _make_page()
    browser, _ = _make_browser(page)
    entered = _make_playwright(browser)

    # when
    with (
        patch(
            "src.reader.strategies.patchright_strategy.async_playwright",
            return_value=entered,
        ),
        patch(
            "src.reader.strategies.patchright_strategy.cookie_manager.get_storage_state",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "src.reader.strategies.patchright_strategy.cookie_manager.get_user_agent",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "src.reader.strategies.patchright_strategy.proxy_provider.for_playwright",
            return_value=None,
        ),
        patch(
            "src.reader.strategies.browser_read.ChallengeDetector.is_login_redirect_url",
            return_value=False,
        ),
        patch(
            "src.reader.strategies.browser_read.assess",
            return_value=_accepted_verdict(),
        ),
        patch("src.reader.strategies.patchright_strategy.settings.EXTRACT_TIMEOUT", 0),
    ):
        strategy = PatchrightStrategy(lambda: "DefaultUA", _make_url_validator())
        html = await strategy.get_html("https://example.com")

    # then
    assert html == _CLEAN_HTML
    page.wait_for_load_state.assert_not_awaited()


@pytest.mark.asyncio
async def test_patchright_extract_returns_text() -> None:
    """extract() returns the trafilatura text of the rendered page."""
    # given
    page = _make_page()
    browser, _ = _make_browser(page)
    entered = _make_playwright(browser)

    # when
    with _base_patches(browser, entered):
        strategy = PatchrightStrategy(lambda: "DefaultUA", _make_url_validator())
        text = await strategy.extract("https://example.com")

    # then
    assert "word" in text


@pytest.mark.asyncio
async def test_patchright_refused_navigation_raises_unsafe_uri() -> None:
    # given
    page = _make_page()
    page.goto = AsyncMock(side_effect=PatchrightError("net::ERR_BLOCKED_BY_CLIENT"))
    browser, _ = _make_browser(page)
    entered = _make_playwright(browser)

    # when / then
    with (
        patch(
            "src.reader.strategies.patchright_strategy.async_playwright",
            return_value=entered,
        ),
        patch(
            "src.reader.strategies.patchright_strategy.cookie_manager.get_storage_state",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "src.reader.strategies.patchright_strategy.cookie_manager.get_user_agent",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "src.reader.strategies.patchright_strategy.proxy_provider.for_playwright",
            return_value=None,
        ),
        patch(
            "src.reader.strategies.browser_read.ChallengeDetector.is_login_redirect_url",
            return_value=False,
        ),
        patch(
            "src.reader.strategies.patchright_strategy.install_browser_guard",
            new=AsyncMock(return_value=["http://169.254.169.254/"]),
        ),
    ):
        strategy = PatchrightStrategy(lambda: "DefaultUA", _make_url_validator())
        with pytest.raises(UnsafeUriError):
            await strategy.get_html("https://example.com/redirect")


@pytest.mark.asyncio
async def test_patchright_plain_navigation_error_propagates() -> None:
    # given
    page = _make_page()
    page.goto = AsyncMock(side_effect=PatchrightError("net::ERR_CONNECTION_REFUSED"))
    browser, _ = _make_browser(page)
    entered = _make_playwright(browser)

    # when / then
    with _base_patches(browser, entered):
        strategy = PatchrightStrategy(lambda: "DefaultUA", _make_url_validator())
        with pytest.raises(PatchrightError):
            await strategy.get_html("https://example.com/down")


@pytest.mark.asyncio
async def test_patchright_recorded_navigation_raises_post_render() -> None:
    # given
    page = _make_page()
    browser, _ = _make_browser(page)
    entered = _make_playwright(browser)

    # when / then
    with (
        patch(
            "src.reader.strategies.patchright_strategy.async_playwright",
            return_value=entered,
        ),
        patch(
            "src.reader.strategies.patchright_strategy.cookie_manager.get_storage_state",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "src.reader.strategies.patchright_strategy.cookie_manager.get_user_agent",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "src.reader.strategies.patchright_strategy.proxy_provider.for_playwright",
            return_value=None,
        ),
        patch(
            "src.reader.strategies.browser_read.ChallengeDetector.is_login_redirect_url",
            return_value=False,
        ),
        patch(
            "src.reader.strategies.browser_read.assess",
            return_value=_accepted_verdict(),
        ),
        patch(
            "src.reader.strategies.patchright_strategy.install_browser_guard",
            new=AsyncMock(return_value=["http://169.254.169.254/"]),
        ),
    ):
        strategy = PatchrightStrategy(lambda: "DefaultUA", _make_url_validator())
        with pytest.raises(UnsafeUriError):
            await strategy.get_html("https://example.com/article")

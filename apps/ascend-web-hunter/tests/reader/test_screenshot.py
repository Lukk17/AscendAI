"""Task 5.2: full-page screenshot capture for the `screenshot` output format."""

import logging
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from ascend_python_common.uri_guard import FetchTarget, UnsafeUriError
from playwright.async_api import Error as PlaywrightError

from src.api.exceptions import ChallengeDetectedException
from src.reader import browser_guard
from src.reader.browser_guard import BrowserFamily
from src.reader.cloudflare.challenge_signals import assess
from src.reader.screenshot import capture_page
from src.reader.strategies.base_strategy import FetchedHtml
from tests.reader.login_title_pages import SIGN_IN_HTML

_PNG = b"\x89PNG\r\n\x1afake-png-bytes"
_HTML = "<html><head><title>Shot</title></head><body><p>Shot.</p></body></html>"
_TIER = "playwright"


def _navigation_response(headers: dict[str, str]) -> MagicMock:
    response = MagicMock(status=200)
    response.all_headers = AsyncMock(return_value=headers)

    return response


def _page(
    html: str = _HTML,
    screenshot: Any = _PNG,
    goto_error: Exception | None = None,
) -> MagicMock:
    page = MagicMock()
    if goto_error is not None:
        page.goto = AsyncMock(side_effect=goto_error)
    else:
        page.goto = AsyncMock(return_value=_navigation_response({}))
    page.content = AsyncMock(return_value=html)
    page.screenshot = AsyncMock(return_value=screenshot)
    page.url = "https://example.com/"

    return page


def _context(page: MagicMock) -> MagicMock:
    context = MagicMock()
    context.new_page = AsyncMock(return_value=page)
    context.close = AsyncMock()
    context.route = AsyncMock()
    context.add_init_script = AsyncMock()
    context.route_web_socket = AsyncMock()
    context.cookies = AsyncMock(return_value=[])
    page.context = context

    return context


def _validator() -> MagicMock:
    validator = MagicMock()
    validator.should_block = MagicMock(return_value=False)

    return validator


@pytest.mark.asyncio
async def test_capture_page_returns_html_and_png() -> None:
    # given
    page = _page()
    context = _context(page)

    async def opener() -> MagicMock:
        return context

    # when
    captured = await capture_page(
        opener, "https://example.com/", _validator(), family=BrowserFamily.CHROMIUM, tier=_TIER
    )

    # then
    assert captured is not None
    assert captured[0] == _HTML
    assert captured[1] == _PNG
    page.goto.assert_awaited_once()
    assert page.screenshot.await_args is not None
    assert page.screenshot.await_args.kwargs.get("full_page") is True
    context.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_captured_html_carries_the_validators_of_the_navigation_answer() -> None:
    # given
    page = _page()
    page.goto = AsyncMock(return_value=_navigation_response({"etag": '"shot"', "last-modified": "Sun"}))
    context = _context(page)

    async def opener() -> MagicMock:
        return context

    # when
    captured = await capture_page(
        opener, "https://example.com/", _validator(), family=BrowserFamily.CHROMIUM, tier=_TIER
    )

    # then
    assert captured is not None
    html = captured[0]
    assert isinstance(html, FetchedHtml)
    assert (html.etag, html.last_modified) == ('"shot"', "Sun")


@pytest.mark.asyncio
async def test_capture_failure_returns_none_and_closes() -> None:
    # given
    page = _page(goto_error=RuntimeError("navigation blew up"))
    context = _context(page)

    async def opener() -> MagicMock:
        return context

    # when
    captured = await capture_page(
        opener, "https://example.com/", _validator(), family=BrowserFamily.CHROMIUM, tier=_TIER
    )

    # then
    assert captured is None
    context.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_playwright_strategy_screenshot_page() -> None:
    # given
    from src.reader.strategies.playwright_strategy import PlaywrightStrategy

    strategy = PlaywrightStrategy(lambda: "ua", MagicMock())
    context = _context(_page())

    # when
    with (
        patch(
            "src.reader.strategies.playwright_strategy.browser_pool.get_browser",
            new=AsyncMock(return_value=MagicMock()),
        ),
        patch.object(strategy, "_create_stealth_context", new=AsyncMock(return_value=context)),
    ):
        captured = await strategy.screenshot_page("https://example.com/")

    # then
    assert captured is not None
    assert captured[0] == _HTML
    assert captured[1] == _PNG


@pytest.mark.asyncio
async def test_patchright_strategy_screenshot_page() -> None:
    # given
    from src.reader.strategies.patchright_strategy import PatchrightStrategy

    strategy = PatchrightStrategy(lambda: "ua", MagicMock())
    browser = MagicMock()
    context = _context(_page())

    # when
    with (
        patch.object(strategy, "_launched_browser") as launched,
        patch.object(strategy, "_create_context", new=AsyncMock(return_value=context)),
    ):
        launched.return_value.__aenter__ = AsyncMock(return_value=browser)
        launched.return_value.__aexit__ = AsyncMock(return_value=False)
        captured = await strategy.screenshot_page("https://example.com/")

    # then
    assert captured is not None
    assert captured[0] == _HTML
    assert captured[1] == _PNG


@pytest.mark.asyncio
async def test_camoufox_strategy_screenshot_page() -> None:
    # given
    from src.reader.strategies.camoufox_strategy import CamoufoxStrategy

    strategy = CamoufoxStrategy(MagicMock())
    browser = MagicMock()
    context = _context(_page())

    # when
    with (
        patch("src.reader.strategies.camoufox_strategy.AsyncCamoufox") as factory,
        patch.object(strategy, "_create_context", new=AsyncMock(return_value=context)),
    ):
        factory.return_value.__aenter__ = AsyncMock(return_value=browser)
        factory.return_value.__aexit__ = AsyncMock(return_value=False)
        captured = await strategy.screenshot_page("https://example.com/")

    # then
    assert captured is not None
    assert captured[0] == _HTML
    assert captured[1] == _PNG


def _navigation_route(url: str, frame: Any = None) -> MagicMock:
    request = MagicMock()
    request.frame = frame if frame is not None else MagicMock()
    request.frame.parent_frame = None
    browser_guard._read_frames.add(request.frame)
    request.url = url
    request.method = "GET"
    request.post_data_buffer = None
    request.all_headers = AsyncMock(return_value={})
    request.is_navigation_request = MagicMock(return_value=True)
    route = MagicMock()
    route.request = request
    route.abort = AsyncMock()
    route.continue_ = AsyncMock()
    route.fulfill = AsyncMock()

    return route


async def _guard_check(url: str, _policy: object) -> FetchTarget:
    if "169.254.169.254" in url:
        raise UnsafeUriError(f"private address: {url}")

    return FetchTarget(url=url, host="example.com", port=443)


@pytest.mark.asyncio
async def test_capture_redirect_to_private_address_raises_unsafe_uri() -> None:
    # given a redirect the route never sees, which the tunnel refused
    page = _page()
    route = _navigation_route("https://example.com/", page.main_frame)
    hop = _navigation_route("http://169.254.169.254/latest/meta-data/", page.main_frame)
    context = _context(page)

    async def navigate(*_args: object, **_kwargs: object) -> None:
        await context.route.await_args.args[1](route)
        failed = next(call.args[1] for call in context.on.call_args_list if call.args[0] == "requestfailed")
        failed(hop.request)
        raise PlaywrightError("net::ERR_TUNNEL_CONNECTION_FAILED")

    page.goto = AsyncMock(side_effect=navigate)

    async def opener() -> MagicMock:
        return context

    # when
    with (
        patch("src.reader.browser_guard.check_fetch_uri", new=AsyncMock(side_effect=_guard_check)),
        patch.object(browser_guard.browser_tunnel, "was_refused", return_value=True),
        pytest.raises(UnsafeUriError, match=r"169\.254\.169\.254"),
    ):
        await capture_page(
            opener, "https://example.com/", _validator(), family=BrowserFamily.CHROMIUM, tier=_TIER
        )

    # then
    route.continue_.assert_awaited_once()
    page.screenshot.assert_not_awaited()
    context.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_capture_refused_later_navigation_on_a_wall_page_raises_unsafe_uri() -> None:
    # given
    page = _page()
    context = _context(page)
    refused_request = MagicMock(url="http://169.254.169.254/", frame=page.main_frame)
    refused_request.is_navigation_request = MagicMock(return_value=True)

    async def content() -> str:
        failed = next(call.args[1] for call in context.on.call_args_list if call.args[0] == "requestfailed")
        failed(refused_request)

        return "<html><body><div id='cf-challenge-running'>Just a moment...</div></body></html>"

    page.content = AsyncMock(side_effect=content)

    async def opener() -> MagicMock:
        return context

    # when / then
    with (
        patch.object(browser_guard.browser_tunnel, "was_refused", return_value=True),
        pytest.raises(UnsafeUriError, match=r"169\.254\.169\.254"),
    ):
        await capture_page(
            opener, "https://example.com/", _validator(), family=BrowserFamily.CHROMIUM, tier=_TIER
        )

    page.screenshot.assert_not_awaited()


@pytest.mark.asyncio
async def test_capture_installs_the_guard_before_navigating() -> None:
    # given
    page = _page()
    context = _context(page)
    order: list[str] = []
    context.route = AsyncMock(side_effect=lambda *_a, **_k: order.append("route"))
    page.goto = AsyncMock(side_effect=lambda *_a, **_k: order.append("goto"))

    async def opener() -> MagicMock:
        return context

    # when
    captured = await capture_page(
        opener, "https://example.com/", _validator(), family=BrowserFamily.CHROMIUM, tier=_TIER
    )

    # then
    assert captured is not None
    assert order == ["route", "goto"]


@pytest.mark.asyncio
async def test_capture_script_navigation_to_refused_address_raises_unsafe_uri() -> None:
    # given
    page = _page()
    context = _context(page)

    async def navigate(*_args: object, **_kwargs: object) -> None:
        handler = context.route.await_args.args[1]
        await handler(_navigation_route("http://169.254.169.254/"))

    page.goto = AsyncMock(side_effect=navigate)

    async def opener() -> MagicMock:
        return context

    # when / then
    with (
        patch("src.reader.browser_guard.check_fetch_uri", new=AsyncMock(side_effect=_guard_check)),
        pytest.raises(UnsafeUriError, match=r"169\.254\.169\.254"),
    ):
        await capture_page(
            opener, "https://example.com/", _validator(), family=BrowserFamily.CHROMIUM, tier=_TIER
        )

    context.close.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("family", list(BrowserFamily))
async def test_capture_installs_the_guard_for_the_given_browser_family(family: BrowserFamily) -> None:
    # given
    context = _context(_page())

    async def opener() -> MagicMock:
        return context

    install = AsyncMock(return_value=[])

    # when
    with patch("src.reader.screenshot.install_browser_guard", new=install):
        await capture_page(opener, "https://example.com/", _validator(), family=family, tier=_TIER)

    # then
    assert install.await_args is not None
    assert install.await_args.kwargs["family"] is family


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("module", "family"),
    [
        ("playwright_strategy", BrowserFamily.CHROMIUM),
        ("patchright_strategy", BrowserFamily.CHROMIUM),
        ("camoufox_strategy", BrowserFamily.FIREFOX),
    ],
)
async def test_strategy_screenshot_names_its_browser_family(module: str, family: BrowserFamily) -> None:
    # given
    from src.reader.strategies.camoufox_strategy import CamoufoxStrategy
    from src.reader.strategies.patchright_strategy import PatchrightStrategy
    from src.reader.strategies.playwright_strategy import PlaywrightStrategy

    strategies: dict[str, Any] = {
        "playwright_strategy": PlaywrightStrategy(lambda: "ua", MagicMock()),
        "patchright_strategy": PatchrightStrategy(lambda: "ua", MagicMock()),
        "camoufox_strategy": CamoufoxStrategy(MagicMock()),
    }
    strategy = strategies[module]
    capture = AsyncMock(return_value=None)
    launcher = MagicMock()
    launcher.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
    launcher.return_value.__aexit__ = AsyncMock(return_value=False)

    # when
    with (
        patch(f"src.reader.strategies.{module}.capture_page", new=capture),
        patch("src.reader.strategies.playwright_strategy.browser_pool.get_browser", new=AsyncMock()),
        patch.object(PatchrightStrategy, "_launched_browser", new=launcher),
        patch("src.reader.strategies.camoufox_strategy.AsyncCamoufox", new=launcher),
    ):
        await strategy.screenshot_page("https://example.com/")

    # then
    assert capture.await_args is not None
    assert capture.await_args.kwargs["family"] is family


_WALL_HTML = "<html><body><div id='cf-challenge-running'></div></body></html>"

_ARTICLE_HTML = "<html><body><article><p>" + "word " * 30 + "</p></article></body></html>"


def _verdict_count(tier: str, outcome: str) -> float:
    from prometheus_client import REGISTRY

    return REGISTRY.get_sample_value("challenge_verdicts_total", {"verdict": outcome, "tier": tier}) or 0.0


def _sample_total(sample_name: str) -> float:
    from prometheus_client import REGISTRY

    return sum(
        sample.value
        for family in REGISTRY.collect()
        for sample in family.samples
        if sample.name == sample_name
    )


async def _capture(context: MagicMock) -> tuple[str, bytes] | None:
    async def opener() -> MagicMock:
        return context

    return await capture_page(
        opener, "https://example.com/", _validator(), family=BrowserFamily.CHROMIUM, tier=_TIER
    )


@pytest.mark.asyncio
async def test_a_captured_content_page_counts_one_content_verdict_under_its_tier() -> None:
    # given
    context = _context(_page(html=_ARTICLE_HTML))
    contents_before = _verdict_count(_TIER, "content")
    verdicts_before = _sample_total("challenge_verdicts_total")
    scores_before = _sample_total("challenge_score_count")

    # when
    captured = await _capture(context)

    # then
    assert captured is not None
    assert _verdict_count(_TIER, "content") == contents_before + 1.0
    assert _sample_total("challenge_verdicts_total") == verdicts_before + 1.0
    assert _sample_total("challenge_score_count") == scores_before + 1.0


@pytest.mark.asyncio
async def test_a_captured_wall_raises_the_challenge_and_counts_one_wall_verdict() -> None:
    # given
    page = _page(html=_WALL_HTML)
    context = _context(page)
    walls_before = _verdict_count(_TIER, "wall")
    verdicts_before = _sample_total("challenge_verdicts_total")
    scores_before = _sample_total("challenge_score_count")

    # when
    with pytest.raises(ChallengeDetectedException) as raised:
        await _capture(context)

    # then
    assert raised.value.verdict.wall is True
    assert _verdict_count(_TIER, "wall") == walls_before + 1.0
    assert _sample_total("challenge_verdicts_total") == verdicts_before + 1.0
    assert _sample_total("challenge_score_count") == scores_before + 1.0
    page.screenshot.assert_not_awaited()
    context.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_a_captured_login_page_raises_a_login_challenge_and_counts_one_verdict() -> None:
    # given
    context = _context(_page(html=SIGN_IN_HTML))
    verdicts_before = _sample_total("challenge_verdicts_total")
    scores_before = _sample_total("challenge_score_count")

    # when
    with pytest.raises(ChallengeDetectedException) as raised:
        await _capture(context)

    # then
    assert raised.value.verdict.intervention_type == "login"
    assert _sample_total("challenge_verdicts_total") == verdicts_before + 1.0
    assert _sample_total("challenge_score_count") == scores_before + 1.0


@pytest.mark.asyncio
async def test_a_capture_the_site_sent_to_a_login_path_raises_a_login_challenge() -> None:
    # given
    page = _page(html=_ARTICLE_HTML)
    page.url = "https://example.com/login/?dest=%2F"
    context = _context(page)

    # when
    with pytest.raises(ChallengeDetectedException) as raised:
        await _capture(context)

    # then
    assert raised.value.verdict.intervention_type == "login"


@pytest.mark.asyncio
async def test_a_capture_is_judged_by_the_main_frame_answer_and_the_context_cookie_names() -> None:
    # given
    page = _page(html=_ARTICLE_HTML)
    answer = MagicMock(status=403)
    answer.all_headers = AsyncMock(return_value={"cf-mitigated": "challenge"})
    page.goto = AsyncMock(return_value=answer)
    context = _context(page)
    context.cookies = AsyncMock(return_value=[{"name": "datadome"}])

    # when
    with (
        patch("src.reader.strategies.browser_read.assess", wraps=assess) as judged,
        pytest.raises(ChallengeDetectedException),
    ):
        await _capture(context)

    # then
    assert judged.call_args.args[0] == 403
    assert judged.call_args.args[2] == {"cf-mitigated": "challenge"}
    assert judged.call_args.args[3] == ["datadome"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("module", "tier"),
    [
        ("playwright_strategy", "playwright"),
        ("patchright_strategy", "patchright"),
        ("camoufox_strategy", "camoufox"),
    ],
)
async def test_strategy_screenshot_names_its_tier(module: str, tier: str) -> None:
    # given
    from src.reader.strategies.camoufox_strategy import CamoufoxStrategy
    from src.reader.strategies.patchright_strategy import PatchrightStrategy
    from src.reader.strategies.playwright_strategy import PlaywrightStrategy

    strategies: dict[str, Any] = {
        "playwright_strategy": PlaywrightStrategy(lambda: "ua", MagicMock()),
        "patchright_strategy": PatchrightStrategy(lambda: "ua", MagicMock()),
        "camoufox_strategy": CamoufoxStrategy(MagicMock()),
    }
    capture = AsyncMock(return_value=None)
    launcher = MagicMock()
    launcher.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
    launcher.return_value.__aexit__ = AsyncMock(return_value=False)

    # when
    with (
        patch(f"src.reader.strategies.{module}.capture_page", new=capture),
        patch("src.reader.strategies.playwright_strategy.browser_pool.get_browser", new=AsyncMock()),
        patch.object(PatchrightStrategy, "_launched_browser", new=launcher),
        patch("src.reader.strategies.camoufox_strategy.AsyncCamoufox", new=launcher),
    ):
        await strategies[module].screenshot_page("https://example.com/")

    # then
    assert capture.await_args is not None
    assert capture.await_args.kwargs["tier"] == tier


@pytest.mark.asyncio
async def test_a_failed_capture_logs_the_reason_without_a_query(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # given
    url = "https://example.com/doc?X-Amz-Signature=secret"
    context = _context(_page(goto_error=RuntimeError(f"navigating to {url} failed")))

    async def opener() -> MagicMock:
        return context

    # when
    with caplog.at_level(logging.WARNING, logger="src.reader.screenshot"):
        captured = await capture_page(opener, url, _validator(), family=BrowserFamily.CHROMIUM, tier=_TIER)

    # then
    assert captured is None
    assert "X-Amz-Signature" not in caplog.text
    assert (
        "screenshot: capture failed for https://example.com/doc: navigating to https://example.com/doc failed"
        in caplog.text
    )

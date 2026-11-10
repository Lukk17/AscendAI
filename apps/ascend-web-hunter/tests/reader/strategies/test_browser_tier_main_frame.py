"""Browser tiers judge a page by its latest main-frame response and its title, and close their context."""

from collections.abc import Awaitable, Callable, Iterator
from contextlib import ExitStack, contextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from ascend_python_common.uri_guard import UnsafeUriError
from playwright.async_api import Error as PlaywrightError

from src.api.exceptions import ChallengeDetectedException
from src.config.config import settings
from src.reader.browser_guard import browser_tunnel
from src.reader.strategies import browser_read
from src.reader.strategies.base_strategy import FetchedHtml
from src.reader.strategies.browser_read import PageNotMeasuredError, PageTooLargeError
from src.reader.strategies.camoufox_strategy import CamoufoxStrategy
from src.reader.strategies.main_frame_response import MainFrameResponses, is_main_frame_document
from src.reader.strategies.patchright_strategy import PatchrightStrategy
from src.reader.strategies.playwright_strategy import PlaywrightStrategy
from tests.reader.login_title_pages import SIGN_IN_HTML, WIKIPEDIA_LOGIN_ARTICLE_HTML

_RICH_HTML = "<html><body><article><p>" + "word " * 30 + "</p></article></body></html>"

_CONTENT_WITH_EMAIL_FORM_HTML = (
    "<html><head><title>Release notes</title></head><body><article><h1>Release notes</h1><p>"
    + "This release adds faster page reads and fixes the export of long reports. " * 4
    + '</p></article><aside><form action="/newsletter"><label>Email address</label>'
    '<input type="email" name="email"><button type="submit">Subscribe</button></form>'
    "</aside></body></html>"
)

_CHALLENGE_HEADERS = {"cf-mitigated": "challenge"}

_URL = "https://example.com/page"


def _response(
    status: int, headers: dict[str, str], *, navigation: bool = True, main_frame: bool = True
) -> MagicMock:
    response = MagicMock(status=status)
    response.headers = headers
    response.all_headers = AsyncMock(return_value=headers)
    response.request.is_navigation_request = MagicMock(return_value=navigation)
    response.frame.parent_frame = None if main_frame else MagicMock()

    return response


def _page() -> MagicMock:
    page = MagicMock()
    page.goto = AsyncMock(return_value=_response(200, {}))
    page.content = AsyncMock(return_value=_RICH_HTML)
    page.url = _URL
    page.wait_for_load_state = AsyncMock()
    page.wait_for_timeout = AsyncMock()
    page.evaluate = AsyncMock(return_value=0)

    return page


def _context(page: MagicMock) -> MagicMock:
    context = MagicMock()
    context.new_page = AsyncMock(return_value=page)
    context.close = AsyncMock()
    context.cookies = AsyncMock(return_value=[])
    context.storage_state = AsyncMock(return_value={"cookies": [], "origins": []})
    context.route = AsyncMock()
    context.add_init_script = AsyncMock()
    context.route_web_socket = None
    page.context = context

    return context


@contextmanager
def _playwright_wiring(context: MagicMock) -> Iterator[None]:
    module = "src.reader.strategies.playwright_strategy"
    browser = MagicMock()
    browser.new_context = AsyncMock(return_value=context)
    with ExitStack() as stack:
        stack.enter_context(patch(f"{module}.browser_pool.get_browser", new=AsyncMock(return_value=browser)))
        stack.enter_context(
            patch(f"{module}.Stealth", return_value=MagicMock(apply_stealth_async=AsyncMock()))
        )
        stack.enter_context(
            patch(f"{module}.cookie_manager.get_storage_state", new=AsyncMock(return_value=None))
        )
        stack.enter_context(
            patch(f"{module}.cookie_manager.get_user_agent", new=AsyncMock(return_value=None))
        )
        stack.enter_context(patch(f"{module}.proxy_provider.for_playwright", return_value=None))
        yield


@contextmanager
def _patchright_wiring(context: MagicMock) -> Iterator[None]:
    module = "src.reader.strategies.patchright_strategy"
    browser = MagicMock()
    browser.new_context = AsyncMock(return_value=context)
    browser.close = AsyncMock()
    driver = MagicMock()
    driver.chromium.launch = AsyncMock(return_value=browser)
    entered = MagicMock()
    entered.__aenter__ = AsyncMock(return_value=driver)
    entered.__aexit__ = AsyncMock(return_value=False)
    with ExitStack() as stack:
        stack.enter_context(patch(f"{module}.async_playwright", return_value=entered))
        stack.enter_context(
            patch(f"{module}.cookie_manager.get_storage_state", new=AsyncMock(return_value=None))
        )
        stack.enter_context(
            patch(f"{module}.cookie_manager.get_user_agent", new=AsyncMock(return_value=None))
        )
        stack.enter_context(patch(f"{module}.proxy_provider.for_playwright", return_value=None))
        yield


@contextmanager
def _camoufox_wiring(context: MagicMock) -> Iterator[None]:
    module = "src.reader.strategies.camoufox_strategy"
    entered = MagicMock()
    entered.__aenter__ = AsyncMock(return_value=MagicMock())
    entered.__aexit__ = AsyncMock(return_value=False)
    with ExitStack() as stack:
        stack.enter_context(patch(f"{module}.AsyncCamoufox", return_value=entered))
        stack.enter_context(patch(f"{module}.AsyncNewContext", new=AsyncMock(return_value=context)))
        stack.enter_context(
            patch(f"{module}.cookie_manager.get_storage_state", new=AsyncMock(return_value=None))
        )
        stack.enter_context(patch(f"{module}.proxy_provider.for_playwright", return_value=None))
        yield


def _playwright_read(url: str) -> Awaitable[str]:
    return PlaywrightStrategy(lambda: "ua", MagicMock(should_block=MagicMock(return_value=False))).get_html(
        url
    )


def _patchright_read(url: str) -> Awaitable[str]:
    return PatchrightStrategy(lambda: "ua", MagicMock(should_block=MagicMock(return_value=False))).get_html(
        url
    )


def _camoufox_read(url: str) -> Awaitable[str]:
    return CamoufoxStrategy(MagicMock(should_block=MagicMock(return_value=False))).get_html(url)


_TIERS: list[Any] = [
    pytest.param(_playwright_wiring, _playwright_read, id="4-playwright_stealth"),
    pytest.param(_patchright_wiring, _patchright_read, id="4a-patchright"),
    pytest.param(_camoufox_wiring, _camoufox_read, id="4b-camoufox"),
]


_COUNTED_TIERS: list[Any] = [
    pytest.param(_playwright_wiring, _playwright_read, "playwright", id="4-playwright_stealth"),
    pytest.param(_patchright_wiring, _patchright_read, "patchright", id="4a-patchright"),
    pytest.param(_camoufox_wiring, _camoufox_read, "camoufox", id="4b-camoufox"),
]


def _response_listener(page: MagicMock) -> Callable[[Any], None]:
    for call in page.on.call_args_list:
        if call.args[0] == "response":
            listener: Callable[[Any], None] = call.args[1]

            return listener

    raise AssertionError("no response listener was registered on the page")


@pytest.mark.asyncio
@pytest.mark.parametrize(("wiring", "read"), _TIERS)
async def test_cleared_challenge_is_judged_by_the_latest_main_frame_response(
    wiring: Any, read: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    # given
    monkeypatch.setattr(settings, "CHALLENGE_CLEAR_WAIT_SECONDS", 0)
    page = _page()
    context = _context(page)
    challenge = _response(403, _CHALLENGE_HEADERS)

    async def navigate(*_args: object, **_kwargs: object) -> MagicMock:
        listener = _response_listener(page)
        listener(challenge)
        listener(_response(200, {}))
        listener(_response(403, _CHALLENGE_HEADERS, navigation=False))
        listener(_response(403, _CHALLENGE_HEADERS, main_frame=False))

        return challenge

    page.goto = AsyncMock(side_effect=navigate)

    # when
    with wiring(context):
        html = await read(_URL)

    # then
    assert html == _RICH_HTML
    context.close.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(("wiring", "read"), _TIERS)
async def test_page_carries_the_validators_of_the_latest_main_frame_response(wiring: Any, read: Any) -> None:
    # given
    page = _page()
    context = _context(page)
    first = _response(200, {"etag": '"first"', "last-modified": "Mon"})

    async def navigate(*_args: object, **_kwargs: object) -> MagicMock:
        listener = _response_listener(page)
        listener(first)
        listener(_response(200, {"etag": '"final"', "last-modified": "Tue"}))
        listener(_response(200, {"etag": '"script"'}, navigation=False))
        listener(_response(200, {"etag": '"frame"'}, main_frame=False))

        return first

    page.goto = AsyncMock(side_effect=navigate)

    # when
    with wiring(context):
        html = await read(_URL)

    # then
    assert isinstance(html, FetchedHtml)
    assert (html.etag, html.last_modified) == ('"final"', "Tue")


@pytest.mark.asyncio
@pytest.mark.parametrize(("wiring", "read"), _TIERS)
async def test_challenge_still_on_the_latest_main_frame_response_is_a_wall(
    wiring: Any, read: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    # given
    monkeypatch.setattr(settings, "CHALLENGE_CLEAR_WAIT_SECONDS", 0)
    page = _page()
    context = _context(page)
    challenge = _response(403, _CHALLENGE_HEADERS)

    async def navigate(*_args: object, **_kwargs: object) -> MagicMock:
        listener = _response_listener(page)
        listener(_response(200, {}))
        listener(challenge)

        return challenge

    page.goto = AsyncMock(side_effect=navigate)

    # when / then
    with wiring(context), pytest.raises(ChallengeDetectedException):
        await read(_URL)

    context.close.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(("wiring", "read"), _TIERS)
async def test_page_titled_sign_in_with_an_email_first_form_is_a_login_wall(wiring: Any, read: Any) -> None:
    # given
    page = _page()
    page.content = AsyncMock(return_value=SIGN_IN_HTML)
    context = _context(page)

    # when
    with wiring(context), pytest.raises(ChallengeDetectedException) as raised:
        await read(_URL)

    # then
    assert raised.value.verdict.intervention_type == "login"
    page.wait_for_load_state.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(("wiring", "read", "tier"), _COUNTED_TIERS)
async def test_page_titled_sign_in_only_after_rendering_is_a_login_wall(
    wiring: Any, read: Any, tier: str
) -> None:
    # given
    page = _page()
    page.content = AsyncMock(side_effect=[_RICH_HTML, SIGN_IN_HTML])
    context = _context(page)
    verdicts_before = _all_verdicts(tier)
    scores_before = _metric_total("challenge_score_count")

    # when
    with wiring(context), pytest.raises(ChallengeDetectedException) as raised:
        await read(_URL)

    # then
    assert raised.value.verdict.intervention_type == "login"
    assert _all_verdicts(tier) == verdicts_before + 1.0
    assert _metric_total("challenge_score_count") == scores_before + 1.0


_LOGIN_LANDING_URL = "https://example.com/login/?reason=lor2&dest=https%3A%2F%2Fexample.com%2Fpage"


@pytest.mark.asyncio
@pytest.mark.parametrize(("wiring", "read", "tier"), _COUNTED_TIERS)
async def test_read_redirected_to_a_login_path_is_a_login_wall(wiring: Any, read: Any, tier: str) -> None:
    # given
    page = _page()
    page.url = _LOGIN_LANDING_URL
    context = _context(page)
    verdicts_before = _all_verdicts(tier)

    # when
    with wiring(context), pytest.raises(ChallengeDetectedException) as raised:
        await read(_URL)

    # then
    assert raised.value.verdict.intervention_type == "login"
    assert _all_verdicts(tier) == verdicts_before + 1.0
    page.wait_for_load_state.assert_not_awaited()
    context.close.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(("wiring", "read", "tier"), _COUNTED_TIERS)
async def test_read_sent_to_a_login_path_only_after_rendering_is_a_login_wall(
    wiring: Any, read: Any, tier: str
) -> None:
    # given
    page = _page()
    context = _context(page)
    verdicts_before = _all_verdicts(tier)

    async def land_on_login(*_args: object, **_kwargs: object) -> None:
        page.url = _LOGIN_LANDING_URL

    page.wait_for_load_state = AsyncMock(side_effect=land_on_login)

    # when
    with wiring(context), pytest.raises(ChallengeDetectedException) as raised:
        await read(_URL)

    # then
    assert raised.value.verdict.intervention_type == "login"
    assert _all_verdicts(tier) == verdicts_before + 1.0


@pytest.mark.asyncio
@pytest.mark.parametrize(("wiring", "read"), _TIERS)
async def test_content_page_with_an_email_form_and_no_login_title_is_returned(wiring: Any, read: Any) -> None:
    # given
    page = _page()
    page.content = AsyncMock(return_value=_CONTENT_WITH_EMAIL_FORM_HTML)
    context = _context(page)

    # when
    with wiring(context):
        html = await read(_URL)

    # then
    assert html == _CONTENT_WITH_EMAIL_FORM_HTML


@pytest.mark.asyncio
@pytest.mark.parametrize(("wiring", "read"), _TIERS)
async def test_read_whose_main_frame_the_tunnel_refused_while_rendering_is_unsafe(
    wiring: Any, read: Any
) -> None:
    # given
    page = _page()
    context = _context(page)
    refused_request = MagicMock(url="http://10.0.0.5/", frame=page.main_frame)
    refused_request.is_navigation_request = MagicMock(return_value=True)

    async def content() -> str:
        failed = next(call.args[1] for call in context.on.call_args_list if call.args[0] == "requestfailed")
        failed(refused_request)

        return _CONTENT_WITH_EMAIL_FORM_HTML

    page.content = AsyncMock(side_effect=content)

    # when / then
    with (
        wiring(context),
        patch.object(browser_tunnel, "was_refused", return_value=True),
        pytest.raises(UnsafeUriError, match=r"10\.0\.0\.5"),
    ):
        await read(_URL)


def _refusing_content(context: MagicMock, page: MagicMock, html: str) -> Callable[[], Awaitable[str]]:
    refused_request = MagicMock(url="http://10.0.0.5/", frame=page.main_frame)
    refused_request.is_navigation_request = MagicMock(return_value=True)

    async def content() -> str:
        failed = next(call.args[1] for call in context.on.call_args_list if call.args[0] == "requestfailed")
        failed(refused_request)

        return html

    return content


_WALL_HTML = "<html><body><div id='cf-challenge-running'>Just a moment...</div></body></html>"


@pytest.mark.asyncio
@pytest.mark.parametrize(("wiring", "read"), _TIERS)
@pytest.mark.parametrize(
    "html",
    [_WALL_HTML, "<html><body></body></html>", SIGN_IN_HTML],
    ids=["wall", "no content", "login wall"],
)
async def test_a_later_navigation_refused_on_a_page_that_is_not_content_is_unsafe(
    wiring: Any, read: Any, html: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # given
    monkeypatch.setattr(settings, "CHALLENGE_CLEAR_WAIT_SECONDS", 0)
    page = _page()
    context = _context(page)
    page.content = AsyncMock(side_effect=_refusing_content(context, page, html))

    # when / then
    with (
        wiring(context),
        patch.object(browser_tunnel, "was_refused", return_value=True),
        pytest.raises(UnsafeUriError, match=r"10\.0\.0\.5"),
    ):
        await read(_URL)


@pytest.mark.asyncio
async def test_a_refusal_seen_while_the_page_content_cannot_be_read_ends_the_poll_as_unsafe() -> None:
    # given
    page = _page()
    context = _context(page)
    readable = _refusing_content(context, page, "")

    async def content() -> str:
        await readable()

        raise PlaywrightError("Execution context was destroyed")

    page.content = AsyncMock(side_effect=content)

    # when / then
    with (
        _playwright_wiring(context),
        patch.object(browser_tunnel, "was_refused", return_value=True),
        pytest.raises(UnsafeUriError),
    ):
        await _playwright_read(_URL)


@pytest.mark.asyncio
async def test_a_page_that_cannot_be_measured_while_polling_is_polled_again() -> None:
    # given
    page = _page()
    page.content = AsyncMock(return_value=_CONTENT_WITH_EMAIL_FORM_HTML)
    context = _context(page)
    measure = AsyncMock(side_effect=[PageNotMeasuredError("navigating"), 10, 10])

    # when
    with _playwright_wiring(context), patch.object(browser_read, "_page_html_length", new=measure):
        html = await _playwright_read(_URL)

    # then
    assert html == _CONTENT_WITH_EMAIL_FORM_HTML
    assert measure.await_count == 3


@pytest.mark.asyncio
@pytest.mark.parametrize(("wiring", "read"), _TIERS)
async def test_a_page_above_the_cap_fails_the_read_without_copying_it(
    wiring: Any, read: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    # given
    monkeypatch.setattr(settings, "BROWSER_RESPONSE_MAX_BYTES", 100)
    page = _page()
    context = _context(page)
    page.content = AsyncMock(return_value=_CONTENT_WITH_EMAIL_FORM_HTML)

    # when / then
    with (
        wiring(context),
        patch.object(browser_read, "_page_html_length", new=AsyncMock(return_value=101)),
        pytest.raises(PageTooLargeError),
    ):
        await read(_URL)

    page.content.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(("wiring", "read"), _TIERS)
async def test_page_titled_login_with_rich_article_text_is_returned(wiring: Any, read: Any) -> None:
    # given
    page = _page()
    page.content = AsyncMock(return_value=WIKIPEDIA_LOGIN_ARTICLE_HTML)
    context = _context(page)

    # when
    with wiring(context):
        html = await read(_URL)

    # then
    assert html == WIKIPEDIA_LOGIN_ARTICLE_HTML


@pytest.mark.asyncio
@pytest.mark.parametrize(("wiring", "read"), _TIERS)
async def test_context_is_closed_when_opening_the_page_fails(wiring: Any, read: Any) -> None:
    # given
    page = _page()
    context = _context(page)
    context.new_page = AsyncMock(side_effect=RuntimeError("page did not open"))

    # when / then
    with wiring(context), pytest.raises(RuntimeError, match="page did not open"):
        await read(_URL)

    context.close.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(("wiring", "read"), _TIERS)
async def test_context_is_closed_when_installing_the_guard_fails(wiring: Any, read: Any) -> None:
    # given
    page = _page()
    context = _context(page)
    context.route = AsyncMock(side_effect=RuntimeError("route install failed"))

    # when / then
    with wiring(context), pytest.raises(RuntimeError, match="route install failed"):
        await read(_URL)

    context.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_responses_without_any_navigation_answer_status_200_and_no_headers() -> None:
    # given
    responses = MainFrameResponses(_page())

    # when
    status, headers = await responses.status_and_headers()

    # then
    assert (status, headers) == (200, {})


def test_main_frame_document_check_rejects_subresources_and_child_frames() -> None:
    # when
    main = is_main_frame_document(_response(200, {}))
    subresource = is_main_frame_document(_response(200, {}, navigation=False))
    child_frame = is_main_frame_document(_response(200, {}, main_frame=False))

    # then
    assert (main, subresource, child_frame) == (True, False, False)


_WALL_HTML = "<html><body><div id='cf-challenge-running'></div></body></html>"


class _PollClock:
    def __init__(self) -> None:
        self.now = 0.0

    def read(self) -> float:
        return self.now

    async def wait(self, *_args: object) -> None:
        self.now += 1.0


def _verdict_count(tier: str, outcome: str) -> float:
    from prometheus_client import REGISTRY

    return REGISTRY.get_sample_value("challenge_verdicts_total", {"verdict": outcome, "tier": tier}) or 0.0


def _all_verdicts(tier: str) -> float:
    return sum(_verdict_count(tier, outcome) for outcome in ("wall", "content", "no_content"))


def _metric_total(sample_name: str) -> float:
    from prometheus_client import REGISTRY

    return sum(
        sample.value
        for family in REGISTRY.collect()
        for sample in family.samples
        if sample.name == sample_name
    )


def _signal_count(html: str) -> int:
    from src.reader.cloudflare.challenge_signals import assess

    return len(assess(200, html, {}, [], record_metrics=False).signals)


@pytest.mark.asyncio
@pytest.mark.parametrize(("wiring", "read", "tier"), _COUNTED_TIERS)
async def test_a_wall_rechecked_on_every_poll_counts_one_verdict_score_and_signal_set(
    wiring: Any, read: Any, tier: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # given
    monkeypatch.setattr(settings, "CHALLENGE_CLEAR_WAIT_SECONDS", 3.0)
    clock = _PollClock()
    page = _page()
    page.content = AsyncMock(return_value=_WALL_HTML)
    page.wait_for_timeout = AsyncMock(side_effect=clock.wait)
    context = _context(page)
    signals_per_check = _signal_count(_WALL_HTML)
    walls_before = _verdict_count(tier, "wall")
    verdicts_before = _all_verdicts(tier)
    scores_before = _metric_total("challenge_score_count")
    signals_before = _metric_total("challenge_signals_fired_total")

    # when
    with (
        wiring(context),
        patch("time.perf_counter", side_effect=clock.read),
        pytest.raises(ChallengeDetectedException) as raised,
    ):
        await read(_URL)

    # then
    assert raised.value.verdict.wall is True
    assert page.content.await_count == 4
    assert signals_per_check > 0
    assert _verdict_count(tier, "wall") == walls_before + 1.0
    assert _all_verdicts(tier) == verdicts_before + 1.0
    assert _metric_total("challenge_score_count") == scores_before + 1.0
    assert _metric_total("challenge_signals_fired_total") == signals_before + signals_per_check


@pytest.mark.asyncio
@pytest.mark.parametrize(("wiring", "read", "tier"), _COUNTED_TIERS)
async def test_a_content_page_counts_one_content_verdict_score_and_signal_set(
    wiring: Any, read: Any, tier: str
) -> None:
    # given
    page = _page()
    context = _context(page)
    signals_per_check = _signal_count(_RICH_HTML)
    contents_before = _verdict_count(tier, "content")
    verdicts_before = _all_verdicts(tier)
    scores_before = _metric_total("challenge_score_count")
    signals_before = _metric_total("challenge_signals_fired_total")

    # when
    with wiring(context):
        html = await read(_URL)

    # then
    assert html == _RICH_HTML
    assert page.content.await_count == 2
    assert _verdict_count(tier, "content") == contents_before + 1.0
    assert _all_verdicts(tier) == verdicts_before + 1.0
    assert _metric_total("challenge_score_count") == scores_before + 1.0
    assert _metric_total("challenge_signals_fired_total") == signals_before + signals_per_check


@pytest.mark.asyncio
@pytest.mark.parametrize(("wiring", "read", "tier"), _COUNTED_TIERS)
async def test_a_wall_that_clears_counts_only_the_content_verdict_of_the_rendered_page(
    wiring: Any, read: Any, tier: str
) -> None:
    # given
    clock = _PollClock()
    page = _page()
    page.content = AsyncMock(side_effect=[_WALL_HTML, _WALL_HTML, _RICH_HTML, _RICH_HTML])
    page.wait_for_timeout = AsyncMock(side_effect=clock.wait)
    context = _context(page)
    walls_before = _verdict_count(tier, "wall")
    contents_before = _verdict_count(tier, "content")
    scores_before = _metric_total("challenge_score_count")

    # when
    with wiring(context), patch("time.perf_counter", side_effect=clock.read):
        html = await read(_URL)

    # then
    assert html == _RICH_HTML
    assert _verdict_count(tier, "wall") == walls_before
    assert _verdict_count(tier, "content") == contents_before + 1.0
    assert _metric_total("challenge_score_count") == scores_before + 1.0


@pytest.mark.asyncio
@pytest.mark.parametrize(("wiring", "read", "tier"), _COUNTED_TIERS)
async def test_a_login_wall_found_while_polling_counts_one_verdict_and_score(
    wiring: Any, read: Any, tier: str
) -> None:
    # given
    page = _page()
    page.content = AsyncMock(return_value=SIGN_IN_HTML)
    context = _context(page)
    verdicts_before = _all_verdicts(tier)
    scores_before = _metric_total("challenge_score_count")

    # when
    with wiring(context), pytest.raises(ChallengeDetectedException):
        await read(_URL)

    # then
    assert _all_verdicts(tier) == verdicts_before + 1.0
    assert _metric_total("challenge_score_count") == scores_before + 1.0


@pytest.mark.asyncio
@pytest.mark.parametrize(("wiring", "read", "tier"), _COUNTED_TIERS)
async def test_a_login_address_refused_before_navigation_counts_one_verdict_and_score(
    wiring: Any, read: Any, tier: str
) -> None:
    # given
    page = _page()
    context = _context(page)
    verdicts_before = _all_verdicts(tier)
    scores_before = _metric_total("challenge_score_count")

    # when
    with wiring(context), pytest.raises(ChallengeDetectedException) as raised:
        await read(f"{_URL}?login=1")

    # then
    assert raised.value.verdict.intervention_type == "login"
    page.goto.assert_not_awaited()
    assert _all_verdicts(tier) == verdicts_before + 1.0
    assert _metric_total("challenge_score_count") == scores_before + 1.0


@pytest.mark.asyncio
async def test_a_web_reader_content_read_counts_one_tier_verdict_and_one_second_look_verdict() -> None:
    # given
    from src.reader.web_reader import WebReader

    page = _page()
    context = _context(page)
    playwright_before = _verdict_count("playwright", "content")
    reader_before = _verdict_count("reader", "content")
    verdicts_before = _metric_total("challenge_verdicts_total")
    scores_before = _metric_total("challenge_score_count")

    # when
    with _playwright_wiring(context):
        result = await WebReader().read(_URL, tier="4-playwright_stealth")

    # then
    assert result["status"] == "success"
    assert _verdict_count("playwright", "content") == playwright_before + 1.0
    assert _verdict_count("reader", "content") == reader_before + 1.0
    assert _metric_total("challenge_verdicts_total") == verdicts_before + 2.0
    assert _metric_total("challenge_score_count") == scores_before + 2.0


def _fail_after_the_poll(page: MagicMock, context: MagicMock, stage: str) -> None:
    failure = RuntimeError(f"{stage} failed")
    if stage == "wait":
        page.wait_for_timeout = AsyncMock(side_effect=failure)
    elif stage == "scroll":
        page.evaluate = AsyncMock(side_effect=failure)
    elif stage == "content":
        page.content = AsyncMock(side_effect=[_RICH_HTML, failure])
    else:
        context.cookies = AsyncMock(side_effect=[[], failure])


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["wait", "scroll", "content", "assessment"])
@pytest.mark.parametrize(("wiring", "read", "tier"), _COUNTED_TIERS)
async def test_a_read_that_fails_after_its_poll_counts_the_last_polled_verdict_once(
    wiring: Any, read: Any, tier: str, stage: str
) -> None:
    # given
    page = _page()
    context = _context(page)
    _fail_after_the_poll(page, context, stage)
    contents_before = _verdict_count(tier, "content")
    verdicts_before = _all_verdicts(tier)
    scores_before = _metric_total("challenge_score_count")
    signals_before = _metric_total("challenge_signals_fired_total")

    # when
    with wiring(context), pytest.raises(RuntimeError, match=f"{stage} failed"):
        await read(_URL)

    # then
    assert _verdict_count(tier, "content") == contents_before + 1.0
    assert _all_verdicts(tier) == verdicts_before + 1.0
    assert _metric_total("challenge_score_count") == scores_before + 1.0
    assert _metric_total("challenge_signals_fired_total") == signals_before + _signal_count(_RICH_HTML)
    context.close.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(("wiring", "read", "tier"), _COUNTED_TIERS)
async def test_a_read_that_fails_before_its_first_check_counts_no_verdict(
    wiring: Any, read: Any, tier: str
) -> None:
    # given
    page = _page()
    page.goto = AsyncMock(side_effect=RuntimeError("navigation failed"))
    context = _context(page)
    verdicts_before = _all_verdicts(tier)
    scores_before = _metric_total("challenge_score_count")

    # when
    with wiring(context), pytest.raises(RuntimeError, match="navigation failed"):
        await read(_URL)

    # then
    assert _all_verdicts(tier) == verdicts_before
    assert _metric_total("challenge_score_count") == scores_before


@pytest.mark.asyncio
async def test_headers_are_those_of_the_latest_main_frame_response_and_none_before_any() -> None:
    # given
    page = _page()
    responses = MainFrameResponses(page)
    before = await responses.headers()
    listener = _response_listener(page)
    listener(_response(200, {"etag": '"first"'}))
    listener(_response(403, {"etag": '"final"'}))

    # when
    after = await responses.headers()

    # then
    assert before == {}
    assert after == {"etag": '"final"'}


@pytest.mark.asyncio
@pytest.mark.parametrize(("wiring", "read", "tier"), _COUNTED_TIERS)
async def test_a_login_address_refused_before_navigation_logs_no_query(
    wiring: Any, read: Any, tier: str, caplog: pytest.LogCaptureFixture
) -> None:
    # given
    page = _page()

    # when
    with (
        caplog.at_level("WARNING", logger="src.reader.strategies.browser_read"),
        wiring(_context(page)),
        pytest.raises(ChallengeDetectedException),
    ):
        await read(f"{_URL}?login=secret")

    # then
    assert _URL in caplog.text
    assert "login=secret" not in caplog.text

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from crawlee.statistics import FinalStatistics
from playwright.async_api import Error as PlaywrightError

from src.api.exceptions import ChallengeDetectedException
from src.reader.strategies.beautifulsoup_strategy import BeautifulSoupStrategy
from src.reader.strategies.crawlee_strategy import CrawleeStrategy
from src.reader.strategies.curl_cffi_fetcher import fetch_with_curl_cffi
from src.reader.strategies.playwright_strategy import PlaywrightStrategy
from src.reader.strategies.trafilatura_strategy import TrafilaturaStrategy
from tests.reader.crawlee_test_support import final_statistics

SAMPLE_HTML = "<html><body><p>Text</p><script>bad</script></body></html>"

_RICH_HTML = "<html><body><article><p>" + "word " * 30 + "</p></article></body></html>"

_WALL_HTML = "<html><body><div id='cf-challenge-running'></div></body></html>"

_LOGIN_WALL_HTML = (
    "<html><body>"
    "<div id='cf-challenge-running'></div>"
    "<p>" + " ".join(["outside"] * 39) + "</p>"
    "<form><p>" + " ".join(["inside"] * 61) + "</p>"
    "<input name='captcha'><input type='password' name='pw'></form>"
    "</body></html>"
)


class _MockResponse:
    def __init__(
        self, html: str = SAMPLE_HTML, status: int = 200, headers: dict[str, str] | None = None
    ) -> None:
        self.status_code = status
        self.text = html
        self.url = "http://test.com"
        self.headers: dict[str, str] = dict(headers or {})

    def raise_for_status(self) -> Any:
        return None


def _make_curl_session(response: _MockResponse) -> MagicMock:
    session = MagicMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    session.get = AsyncMock(return_value=response)

    return session


@pytest.fixture
def patch_cookies_none() -> Any:
    with (
        patch(
            "src.reader.strategies.curl_cffi_fetcher.cookie_manager.get_flat_cookies",
            new=AsyncMock(return_value={}),
        ),
        patch(
            "src.reader.strategies.curl_cffi_fetcher.cookie_manager.get_user_agent",
            new=AsyncMock(return_value=None),
        ),
    ):
        yield


@pytest.mark.asyncio
async def test_curl_cffi_fetcher_returns_html(patch_cookies_none: Any, pinned_public_host: Any) -> None:
    # given
    session = _make_curl_session(_MockResponse(SAMPLE_HTML))

    # when
    with patch(
        "src.reader.strategies.curl_cffi_fetcher.requests.AsyncSession",
        return_value=session,
    ):
        result = await fetch_with_curl_cffi("http://test.com", lambda: "ua", "TestStrat")

    # then
    assert result == SAMPLE_HTML


@pytest.mark.asyncio
async def test_curl_cffi_fetcher_uses_cached_cookies(pinned_public_host: Any) -> None:
    # given
    session = _make_curl_session(_MockResponse(SAMPLE_HTML))

    # when
    with (
        patch(
            "src.reader.strategies.curl_cffi_fetcher.cookie_manager.get_flat_cookies",
            new=AsyncMock(return_value={"cf_clearance": "x"}),
        ),
        patch(
            "src.reader.strategies.curl_cffi_fetcher.cookie_manager.get_user_agent",
            new=AsyncMock(return_value="cached-ua"),
        ),
        patch(
            "src.reader.strategies.curl_cffi_fetcher.requests.AsyncSession",
            return_value=session,
        ),
    ):
        result = await fetch_with_curl_cffi("http://test.com", lambda: "fallback", "TestStrat")

    # then
    assert result == SAMPLE_HTML
    call = session.get.call_args
    assert call.kwargs["headers"]["User-Agent"] == "cached-ua"
    assert call.kwargs["cookies"] == {"cf_clearance": "x"}


@pytest.mark.asyncio
async def test_curl_cffi_fetcher_raises_on_login_wall(
    patch_cookies_none: Any, pinned_public_host: Any
) -> None:
    # given
    session = _make_curl_session(_MockResponse(SAMPLE_HTML))

    # when
    with (
        patch(
            "src.reader.strategies.curl_cffi_fetcher.requests.AsyncSession",
            return_value=session,
        ),
        patch(
            "src.reader.strategies.curl_cffi_fetcher.ChallengeDetector.is_login_required",
            return_value=True,
        ),
    ):
        with pytest.raises(ChallengeDetectedException) as exc:
            await fetch_with_curl_cffi("http://test.com", lambda: "ua", "TestStrat")

    # then
    assert exc.value.intervention_type == "login"


@pytest.mark.asyncio
async def test_curl_cffi_fetcher_raises_on_waf_block(
    patch_cookies_none: Any, pinned_public_host: Any
) -> None:
    # given
    body = "<html><body><article><p>" + "word " * 200 + "</p></article></body></html>"
    response = _MockResponse(body, status=403, headers={"cf-mitigated": "challenge"})
    session = _make_curl_session(response)

    # when
    with patch(
        "src.reader.strategies.curl_cffi_fetcher.requests.AsyncSession",
        return_value=session,
    ):
        with pytest.raises(ChallengeDetectedException) as exc:
            await fetch_with_curl_cffi("http://test.com", lambda: "ua", "TestStrat")

    # then
    assert exc.value.intervention_type == "captcha"
    assert exc.value.verdict.vendor == "cloudflare"
    assert exc.value.verdict.wall is True


@pytest.mark.asyncio
async def test_curl_cffi_fetcher_passes_status_headers_and_cookie_names_to_verdict(
    patch_cookies_none: Any, pinned_public_host: Any
) -> None:
    # given
    from src.reader.cloudflare.challenge_signals import assess as real_assess

    body = "<html><body><article><p>" + "word " * 200 + "</p></article></body></html>"
    headers = {"x-dd-b": "1", "set-cookie": "datadome=abc; Path=/"}
    session = _make_curl_session(_MockResponse(body, status=200, headers=headers))

    # when
    with (
        patch(
            "src.reader.strategies.curl_cffi_fetcher.requests.AsyncSession",
            return_value=session,
        ),
        patch(
            "src.reader.strategies.curl_cffi_fetcher.assess",
            wraps=real_assess,
        ) as mock_assess,
    ):
        result = await fetch_with_curl_cffi("http://test.com", lambda: "ua", "TestStrat")

    # then
    assert result == body
    assert mock_assess.call_args.args[0] == 200
    assert mock_assess.call_args.args[2] == headers
    assert mock_assess.call_args.args[3] == ["datadome"]


@pytest.mark.asyncio
async def test_curl_cffi_fetcher_returns_empty_on_transport_error(
    patch_cookies_none: Any, pinned_public_host: Any
) -> None:
    # when
    with patch(
        "src.reader.strategies.curl_cffi_fetcher.requests.AsyncSession",
        side_effect=RuntimeError("net"),
    ):
        result = await fetch_with_curl_cffi("http://test.com", lambda: "ua", "TestStrat")

    # then
    assert result == ""


@pytest.mark.asyncio
async def test_beautifulsoup_extract_strips_noise(patch_cookies_none: Any, pinned_public_host: Any) -> None:
    # given
    session = _make_curl_session(_MockResponse(SAMPLE_HTML))
    strategy = BeautifulSoupStrategy(lambda: "ua")

    # when
    with patch(
        "src.reader.strategies.curl_cffi_fetcher.requests.AsyncSession",
        return_value=session,
    ):
        result = await strategy.extract("http://test.com")

    # then
    assert "Text" in result
    assert "bad" not in result


@pytest.mark.asyncio
async def test_beautifulsoup_extract_empty_html(patch_cookies_none: Any) -> None:
    # when
    with patch(
        "src.reader.strategies.beautifulsoup_strategy.fetch_with_curl_cffi",
        new=AsyncMock(return_value=""),
    ):
        strategy = BeautifulSoupStrategy(lambda: "ua")
        result = await strategy.extract("http://test.com")

    # then
    assert result == ""


@pytest.mark.asyncio
async def test_trafilatura_extract(patch_cookies_none: Any) -> None:
    # given
    long_text = "Extracted content. " * 20  # 380 chars, well above the readability output

    # when
    with (
        patch(
            "src.reader.strategies.trafilatura_strategy.fetch_with_curl_cffi",
            new=AsyncMock(return_value=SAMPLE_HTML),
        ),
        patch(
            "src.reader.extraction.trafilatura.extract",
            return_value=long_text,
        ),
    ):
        strategy = TrafilaturaStrategy(lambda: "ua")
        result = await strategy.extract("http://test.com")

    # then
    assert result == long_text


@pytest.mark.asyncio
async def test_trafilatura_extract_empty_html() -> None:
    # when
    with patch(
        "src.reader.strategies.trafilatura_strategy.fetch_with_curl_cffi",
        new=AsyncMock(return_value=""),
    ):
        strategy = TrafilaturaStrategy(lambda: "ua")
        result = await strategy.extract("http://test.com")

    # then
    assert result == ""


@pytest.mark.asyncio
async def test_trafilatura_extract_falls_back_to_readability_when_trafilatura_returns_none(
    patch_cookies_none: Any,
) -> None:
    """When trafilatura returns None the readability fallback content is returned instead of empty string."""
    # when
    with (
        patch(
            "src.reader.strategies.trafilatura_strategy.fetch_with_curl_cffi",
            new=AsyncMock(return_value=SAMPLE_HTML),
        ),
        patch(
            "src.reader.extraction.trafilatura.extract",
            return_value=None,
        ),
        patch(
            "src.reader.extraction._readability_extract",
            return_value={
                "content": "<p>Fallback content</p>",
                "title": "",
                "author": "",
                "date": "",
                "sitename": "",
                "source": "readability",
            },
        ),
    ):
        strategy = TrafilaturaStrategy(lambda: "ua")
        result = await strategy.extract("http://test.com")

    # then
    assert result == "<p>Fallback content</p>"


# Playwright strategy: use the singleton browser_pool which the conftest already mocked.


def _build_playwright_page_mock(html: str, current_url: str = "http://test.com") -> MagicMock:
    goto_response = MagicMock(status=200)
    goto_response.all_headers = AsyncMock(return_value={})
    page = MagicMock()
    page.url = current_url
    page.content = AsyncMock(return_value=html)
    page.goto = AsyncMock(return_value=goto_response)
    page.wait_for_load_state = AsyncMock(side_effect=PlaywrightError("networkidle timeout"))
    page.wait_for_timeout = AsyncMock()
    page.evaluate = AsyncMock(return_value=0)
    page.route = AsyncMock()

    return page


def _wire_browser_pool(monkeypatch: Any, page: Any) -> None:
    from src.runtime import browser_pool as bp_module

    context = MagicMock()
    context.new_page = AsyncMock(return_value=page)
    context.close = AsyncMock()
    context.cookies = AsyncMock(return_value=[])
    context.route = AsyncMock()
    context.route_web_socket = None
    page.context = context

    browser = MagicMock()
    browser.is_connected = MagicMock(return_value=True)
    browser.new_context = AsyncMock(return_value=context)

    monkeypatch.setattr(bp_module.browser_pool, "get_browser", AsyncMock(return_value=browser))


@pytest.mark.asyncio
async def test_playwright_extract_happy_path(monkeypatch: Any) -> None:
    # given
    from src.reader.cloudflare.challenge_signals import assess as real_assess

    accepted = real_assess(200, _RICH_HTML)
    assert accepted.accepted is True
    page = _build_playwright_page_mock(_RICH_HTML)
    page.wait_for_load_state = AsyncMock(return_value=None)
    _wire_browser_pool(monkeypatch, page)

    # when
    with (
        patch(
            "src.reader.strategies.playwright_strategy.Stealth",
            return_value=MagicMock(apply_stealth_async=AsyncMock()),
        ),
        patch(
            "src.reader.strategies.playwright_strategy.assess",
            return_value=accepted,
        ),
        patch(
            "src.reader.strategies.playwright_strategy.trafilatura.extract",
            return_value="Extracted",
        ),
        patch(
            "src.reader.strategies.playwright_strategy.time.perf_counter",
            return_value=0.0,
        ),
    ):
        strategy = PlaywrightStrategy(lambda: "ua", MagicMock())
        result = await strategy.extract("http://test.com")

    # then
    assert result == "Extracted"


@pytest.mark.asyncio
async def test_playwright_extract_returns_empty_when_trafilatura_none(monkeypatch: Any) -> None:
    # given
    from src.reader.cloudflare.challenge_signals import assess as real_assess

    accepted = real_assess(200, _RICH_HTML)
    assert accepted.accepted is True
    page = _build_playwright_page_mock(_RICH_HTML)
    page.wait_for_load_state = AsyncMock(return_value=None)
    _wire_browser_pool(monkeypatch, page)

    # when
    with (
        patch(
            "src.reader.strategies.playwright_strategy.Stealth",
            return_value=MagicMock(apply_stealth_async=AsyncMock()),
        ),
        patch(
            "src.reader.strategies.playwright_strategy.assess",
            return_value=accepted,
        ),
        patch(
            "src.reader.strategies.playwright_strategy.trafilatura.extract",
            return_value=None,
        ),
        patch(
            "src.reader.strategies.playwright_strategy.time.perf_counter",
            return_value=0.0,
        ),
    ):
        strategy = PlaywrightStrategy(lambda: "ua", MagicMock())
        result = await strategy.extract("http://test.com")

    # then
    assert result == ""


@pytest.mark.asyncio
async def test_playwright_raises_challenge_on_login_redirect_url(monkeypatch: Any) -> None:
    # given
    page = _build_playwright_page_mock("<html></html>")
    _wire_browser_pool(monkeypatch, page)

    # when
    with patch(
        "src.reader.strategies.playwright_strategy.Stealth",
        return_value=MagicMock(apply_stealth_async=AsyncMock()),
    ):
        strategy = PlaywrightStrategy(lambda: "ua", MagicMock())
        with pytest.raises(ChallengeDetectedException) as exc:
            await strategy.get_html("http://test.com?login=1")

    # then
    assert exc.value.intervention_type == "login"


@pytest.mark.asyncio
async def test_playwright_raises_challenge_on_login_wall_during_poll(monkeypatch: Any) -> None:
    # given
    page = _build_playwright_page_mock(_LOGIN_WALL_HTML)
    _wire_browser_pool(monkeypatch, page)

    # when
    with (
        patch(
            "src.reader.strategies.playwright_strategy.Stealth",
            return_value=MagicMock(apply_stealth_async=AsyncMock()),
        ),
        patch(
            "src.reader.strategies.playwright_strategy.time.perf_counter",
            return_value=0.0,
        ),
    ):
        strategy = PlaywrightStrategy(lambda: "ua", MagicMock())
        with pytest.raises(ChallengeDetectedException) as exc:
            await strategy.get_html("http://test.com")

    # then
    assert exc.value.intervention_type == "login"
    assert exc.value.verdict.vendor == "cloudflare"
    assert exc.value.verdict.wall is True


@pytest.mark.asyncio
async def test_playwright_raises_challenge_on_blocked_during_poll(monkeypatch: Any) -> None:
    # given
    page = _build_playwright_page_mock(_WALL_HTML)
    _wire_browser_pool(monkeypatch, page)
    perf_values = iter([0.0, 100.0, 100.0])

    # when
    with (
        patch(
            "src.reader.strategies.playwright_strategy.Stealth",
            return_value=MagicMock(apply_stealth_async=AsyncMock()),
        ),
        patch(
            "src.reader.strategies.playwright_strategy.time.perf_counter",
            side_effect=perf_values,
        ),
    ):
        strategy = PlaywrightStrategy(lambda: "ua", MagicMock())
        with pytest.raises(ChallengeDetectedException) as exc:
            await strategy.get_html("http://test.com")

    # then
    assert exc.value.intervention_type == "captcha"
    assert exc.value.verdict.vendor == "cloudflare"


@pytest.mark.asyncio
async def test_playwright_waits_for_challenge_to_auto_clear_then_succeeds(monkeypatch: Any) -> None:
    """A Cloudflare JS challenge that auto-clears within the budget must NOT escalate:
    the headful tier keeps polling, the challenge resolves, and content is returned."""
    # given
    from src.reader.cloudflare.challenge_signals import assess as real_assess

    wall = real_assess(200, _WALL_HTML)
    assert wall.wall is True
    cleared = real_assess(200, _RICH_HTML)
    assert cleared.accepted is True
    page = _build_playwright_page_mock(_RICH_HTML)
    page.wait_for_load_state = AsyncMock(return_value=None)
    _wire_browser_pool(monkeypatch, page)

    # when
    with (
        patch(
            "src.reader.strategies.playwright_strategy.Stealth",
            return_value=MagicMock(apply_stealth_async=AsyncMock()),
        ),
        patch(
            "src.reader.strategies.playwright_strategy.assess",
            side_effect=[wall, wall, cleared, cleared],
        ),
        patch(
            "src.reader.strategies.playwright_strategy.trafilatura.extract",
            return_value="Extracted",
        ),
        patch(
            "src.reader.strategies.playwright_strategy.time.perf_counter",
            return_value=0.0,
        ),
    ):
        strategy = PlaywrightStrategy(lambda: "ua", MagicMock())
        result = await strategy.extract("http://test.com")

    # then
    assert result == "Extracted"


@pytest.mark.asyncio
async def test_playwright_escalates_when_challenge_never_clears(monkeypatch: Any) -> None:
    """A challenge still present after the auto-clear budget escalates to NoVNC."""
    # given
    page = _build_playwright_page_mock(_WALL_HTML)
    _wire_browser_pool(monkeypatch, page)
    # perf values: poll_start (0.0), loop check 1 (0.0), challenge check 1 (5.0 < 12.0) → wait,
    # loop check 2 (0.0), challenge check 2 (50.0 >= 12.0) → raise.
    perf_values = iter([0.0, 0.0, 5.0, 0.0, 50.0])

    # when
    with (
        patch(
            "src.reader.strategies.playwright_strategy.Stealth",
            return_value=MagicMock(apply_stealth_async=AsyncMock()),
        ),
        patch(
            "src.reader.strategies.playwright_strategy.time.perf_counter",
            side_effect=perf_values,
        ),
    ):
        strategy = PlaywrightStrategy(lambda: "ua", MagicMock())
        with pytest.raises(ChallengeDetectedException) as exc:
            await strategy.get_html("http://test.com")

    # then
    assert exc.value.intervention_type == "captcha"
    assert exc.value.verdict.vendor == "cloudflare"
    assert page.wait_for_timeout.await_count >= 1


@pytest.mark.asyncio
async def test_playwright_still_blocked_after_deadline_raises_not_returns_html(monkeypatch: Any) -> None:
    """The post-loop captcha re-check must raise even if the poll loop exited by deadline."""
    # given
    page = _build_playwright_page_mock(_WALL_HTML)
    _wire_browser_pool(monkeypatch, page)
    perf_values = iter([0.0, 100.0, 100.0])

    # when
    with (
        patch(
            "src.reader.strategies.playwright_strategy.Stealth",
            return_value=MagicMock(apply_stealth_async=AsyncMock()),
        ),
        patch(
            "src.reader.strategies.playwright_strategy.time.perf_counter",
            side_effect=perf_values,
        ),
    ):
        strategy = PlaywrightStrategy(lambda: "ua", MagicMock())
        with pytest.raises(ChallengeDetectedException) as exc:
            await strategy.get_html("http://test.com")

    # then
    assert exc.value.intervention_type == "captcha"
    assert exc.value.verdict.vendor == "cloudflare"


@pytest.mark.asyncio
async def test_playwright_passes_initial_response_headers_to_post_render_assess(
    monkeypatch: Any,
) -> None:
    """The status, headers and cookie names of the initial response reach the
    post-render verdict: the headers are the initial response's, not the
    rendered page's."""
    # given
    from src.reader.cloudflare.challenge_signals import assess as real_assess

    initial_headers = {"cf-mitigated": "challenge", "x-extra": "1"}
    goto_response = MagicMock(status=403)
    goto_response.all_headers = AsyncMock(return_value=initial_headers)
    page = _build_playwright_page_mock(_RICH_HTML)
    page.goto = AsyncMock(return_value=goto_response)
    _wire_browser_pool(monkeypatch, page)
    perf_values = iter([0.0, 100.0, 100.0])

    # when
    with (
        patch(
            "src.reader.strategies.playwright_strategy.Stealth",
            return_value=MagicMock(apply_stealth_async=AsyncMock()),
        ),
        patch(
            "src.reader.strategies.playwright_strategy.assess",
            wraps=real_assess,
        ) as mock_assess,
        patch(
            "src.reader.strategies.playwright_strategy.time.perf_counter",
            side_effect=perf_values,
        ),
    ):
        strategy = PlaywrightStrategy(lambda: "ua", MagicMock())
        with pytest.raises(ChallengeDetectedException) as exc:
            await strategy.get_html("http://test.com")

    # then
    assert exc.value.intervention_type == "captcha"
    assert exc.value.verdict.vendor == "cloudflare"
    assert mock_assess.call_count >= 1
    for call in mock_assess.call_args_list:
        assert call.args[0] == 403
        assert call.args[2] == initial_headers


@pytest.mark.asyncio
async def test_playwright_raises_late_login_wall(monkeypatch: Any) -> Any:
    # given
    from src.reader.cloudflare.challenge_signals import assess as real_assess

    cleared = real_assess(200, _RICH_HTML)
    assert cleared.accepted is True
    login_wall = real_assess(200, _LOGIN_WALL_HTML)
    assert login_wall.wall is True
    assert login_wall.intervention_type == "login"
    page = _build_playwright_page_mock(_RICH_HTML)
    page.wait_for_load_state = AsyncMock(return_value=None)
    _wire_browser_pool(monkeypatch, page)

    # when
    with (
        patch(
            "src.reader.strategies.playwright_strategy.Stealth",
            return_value=MagicMock(apply_stealth_async=AsyncMock()),
        ),
        patch(
            "src.reader.strategies.playwright_strategy.assess",
            side_effect=[cleared, login_wall],
        ),
        patch(
            "src.reader.strategies.playwright_strategy.time.perf_counter",
            return_value=0.0,
        ),
    ):
        strategy = PlaywrightStrategy(lambda: "ua", MagicMock())
        with pytest.raises(ChallengeDetectedException) as exc:
            await strategy.get_html("http://test.com")

    # then
    assert exc.value.intervention_type == "login"


@pytest.mark.asyncio
async def test_playwright_retries_after_transient_content_read_error(monkeypatch: Any) -> None:
    """A transient PlaywrightError while reading page.content() during polling must be
    swallowed and retried rather than propagated to the caller."""
    # given
    from src.reader.cloudflare.challenge_signals import assess as real_assess

    accepted = real_assess(200, _RICH_HTML)
    assert accepted.accepted is True
    html = _RICH_HTML
    page = _build_playwright_page_mock(html)
    page.content = AsyncMock(side_effect=[PlaywrightError("frame detached"), html, html])
    page.wait_for_load_state = AsyncMock(return_value=None)
    _wire_browser_pool(monkeypatch, page)

    # when
    with (
        patch(
            "src.reader.strategies.playwright_strategy.Stealth",
            return_value=MagicMock(apply_stealth_async=AsyncMock()),
        ),
        patch(
            "src.reader.strategies.playwright_strategy.assess",
            return_value=accepted,
        ),
        patch(
            "src.reader.strategies.playwright_strategy.trafilatura.extract",
            return_value="Extracted",
        ),
        patch(
            "src.reader.strategies.playwright_strategy.time.perf_counter",
            return_value=0.0,
        ),
    ):
        strategy = PlaywrightStrategy(lambda: "ua", MagicMock())
        result = await strategy.extract("http://test.com")

    # then
    assert result == "Extracted"
    assert page.wait_for_timeout.await_count >= 1


@pytest.mark.asyncio
async def test_playwright_retries_after_transient_networkidle_wait_error(monkeypatch: Any) -> None:
    """A transient PlaywrightError while waiting for the networkidle load state during
    polling must be swallowed and retried rather than propagated to the caller."""
    # given
    from src.reader.cloudflare.challenge_signals import assess as real_assess

    accepted = real_assess(200, _RICH_HTML)
    assert accepted.accepted is True
    page = _build_playwright_page_mock(_RICH_HTML)
    page.wait_for_load_state = AsyncMock(side_effect=[PlaywrightError("networkidle timeout"), None])
    _wire_browser_pool(monkeypatch, page)

    # when
    with (
        patch(
            "src.reader.strategies.playwright_strategy.Stealth",
            return_value=MagicMock(apply_stealth_async=AsyncMock()),
        ),
        patch(
            "src.reader.strategies.playwright_strategy.assess",
            return_value=accepted,
        ),
        patch(
            "src.reader.strategies.playwright_strategy.trafilatura.extract",
            return_value="Extracted",
        ),
        patch(
            "src.reader.strategies.playwright_strategy.time.perf_counter",
            return_value=0.0,
        ),
    ):
        strategy = PlaywrightStrategy(lambda: "ua", MagicMock())
        result = await strategy.extract("http://test.com")

    # then
    assert result == "Extracted"


# Crawlee strategy


@pytest.fixture(autouse=True)
def _crawlee_seed_url_check_passes() -> Any:
    """The seed-URL guard check is unit-tested separately; keep these tests hermetic."""
    with patch(
        "src.reader.strategies.crawlee_strategy.check_fetch_uri",
        new=AsyncMock(return_value=MagicMock()),
    ):
        yield


@pytest.mark.asyncio
async def test_crawlee_strategy_extract_returns_trafilatura_result() -> None:
    # when
    with (
        patch("src.reader.strategies.crawlee_strategy.AdaptivePlaywrightCrawler") as mock_crawler_cls,
        patch(
            "src.reader.strategies.crawlee_strategy.trafilatura.extract",
            return_value="Crawlee",
        ),
    ):
        mock_crawler = MagicMock()
        mock_crawler.run = AsyncMock(return_value=final_statistics(1))
        mock_crawler.router.default_handler = lambda f: f
        mock_crawler.pre_navigation_hook = lambda f: f
        mock_crawler_cls.with_beautifulsoup_static_parser.return_value = mock_crawler
        strategy = CrawleeStrategy(MagicMock())
        result = await strategy.extract("http://test.com")

    # then
    assert result == "Crawlee"


@pytest.mark.asyncio
async def test_crawlee_strategy_raises_challenge_on_login_wall() -> None:
    """A title-login wall behind the crawler escalates with the login type."""
    # given
    html = "<html><head><title>Sign In</title></head><body><p>" + "word " * 12 + "</p></body></html>"

    async def fake_run(urls: list[str]) -> FinalStatistics:
        assert captured["default"] is not None
        await captured["default"](fake_context)
        return final_statistics(1)

    captured: dict[str, Any] = {}
    fake_context = MagicMock()
    fake_context.page.content = AsyncMock(return_value=html)

    # when
    with patch("src.reader.strategies.crawlee_strategy.AdaptivePlaywrightCrawler") as mock_crawler_cls:
        mock_crawler = MagicMock()
        mock_crawler.run = AsyncMock(side_effect=fake_run)
        mock_crawler.router.default_handler = lambda fn: captured.setdefault("default", fn)
        mock_crawler.pre_navigation_hook = lambda fn: captured.setdefault("pre_nav", fn)
        mock_crawler_cls.with_beautifulsoup_static_parser.return_value = mock_crawler
        strategy = CrawleeStrategy(MagicMock())
        with pytest.raises(ChallengeDetectedException) as exc:
            await strategy.get_html("http://test.com")

    # then
    assert exc.value.intervention_type == "login"


@pytest.mark.asyncio
async def test_crawlee_strategy_raises_challenge_on_waf_block() -> None:
    """A wall behind the crawler escalates with the captcha type and the vendor."""
    # given
    html = "<html><body><div id='cf-challenge-running'></div></body></html>"

    async def fake_run(urls: list[str]) -> FinalStatistics:
        assert captured["default"] is not None
        await captured["default"](fake_context)
        return final_statistics(1)

    captured: dict[str, Any] = {}
    fake_context = MagicMock()
    fake_context.page.content = AsyncMock(return_value=html)

    # when
    with patch("src.reader.strategies.crawlee_strategy.AdaptivePlaywrightCrawler") as mock_crawler_cls:
        mock_crawler = MagicMock()
        mock_crawler.run = AsyncMock(side_effect=fake_run)
        mock_crawler.router.default_handler = lambda fn: captured.setdefault("default", fn)
        mock_crawler.pre_navigation_hook = lambda fn: captured.setdefault("pre_nav", fn)
        mock_crawler_cls.with_beautifulsoup_static_parser.return_value = mock_crawler
        strategy = CrawleeStrategy(MagicMock())
        with pytest.raises(ChallengeDetectedException) as exc:
            await strategy.get_html("http://test.com")

    # then
    assert exc.value.intervention_type == "captcha"
    assert exc.value.verdict.vendor == "cloudflare"
    assert exc.value.verdict.wall is True


@pytest.mark.asyncio
async def test_crawlee_result_container_carries_final_status_and_headers() -> None:
    """The result container carries the final status and headers so the verdict
    sees the same response the crawler rendered."""
    # given
    from crawlee.crawlers import AdaptivePlaywrightCrawlingContext

    strategy = CrawleeStrategy(MagicMock())
    context = MagicMock(spec=AdaptivePlaywrightCrawlingContext)
    context.page = MagicMock()
    context.page.content = AsyncMock(return_value="<html>final</html>")
    last_response = {"status": 403, "headers": {"cf-mitigated": "challenge"}}
    result_container: dict[str, Any] = {"html": "", "status": 200, "headers": {}}

    # when
    await strategy._handle_crawlee_request(context, result_container, last_response)

    # then
    assert result_container["html"] == "<html>final</html>"
    assert result_container["status"] == 403
    assert result_container["headers"] == {"cf-mitigated": "challenge"}


@pytest.mark.asyncio
async def test_crawlee_handle_request_playwright_context() -> None:
    # given
    from crawlee.crawlers import PlaywrightCrawlingContext

    strategy = CrawleeStrategy(MagicMock())
    context = MagicMock(spec=PlaywrightCrawlingContext)
    context.page = MagicMock()
    context.page.content = AsyncMock(return_value="<html>from playwright</html>")
    result_container: dict[str, Any] = {"html": "", "status": 200, "headers": {}}

    # when
    await strategy._handle_crawlee_request(context, result_container, {})

    # then
    assert "playwright" in result_container["html"]
    assert result_container["status"] == 200
    assert result_container["headers"] == {}


@pytest.mark.asyncio
async def test_crawlee_handle_request_falls_back_to_snapshot_when_page_content_raises() -> None:
    """When page.content() raises, _handle_crawlee_request must fall back to get_snapshot()."""
    # given
    from crawlee.crawlers import AdaptivePlaywrightCrawlingContext

    strategy = CrawleeStrategy(MagicMock())
    context = MagicMock(spec=AdaptivePlaywrightCrawlingContext)
    context.page = MagicMock()
    context.page.content = AsyncMock(side_effect=RuntimeError("page detached"))
    snapshot = MagicMock()
    snapshot.html = "<html>snapshot</html>"
    context.get_snapshot = AsyncMock(return_value=snapshot)
    result_container: dict[str, Any] = {"html": "", "status": 200, "headers": {}}

    # when
    await strategy._handle_crawlee_request(context, result_container, {})

    # then
    assert result_container["html"] == "<html>snapshot</html>"
    context.get_snapshot.assert_awaited_once()


@pytest.mark.asyncio
async def test_crawlee_response_summary_tolerates_broken_response() -> None:
    # given
    from typing import TYPE_CHECKING, cast

    from src.reader.strategies.crawlee_strategy import _response_summary

    if TYPE_CHECKING:
        from playwright.async_api import Response as PlaywrightResponse

    class _BrokenHeaders:
        @property
        def headers(self) -> dict[str, str]:
            raise RuntimeError("gone")

        @property
        def status(self) -> int:
            raise RuntimeError("gone")

    good = MagicMock()
    good.headers = {"cf-mitigated": "challenge"}
    good.status = 403

    # when
    broken = _response_summary(cast("PlaywrightResponse", _BrokenHeaders()))
    ok = _response_summary(cast("PlaywrightResponse", good))

    # then
    assert broken == {"status": 200, "headers": {}}
    assert ok == {"status": 403, "headers": {"cf-mitigated": "challenge"}}


@pytest.mark.asyncio
async def test_crawlee_decorated_handlers_executed() -> Any:
    """The crawlee strategy registers two decorated inner functions
    (request_handler and install_guard). Capture them and invoke directly so
    their bodies are covered."""
    # given
    captured: dict[str, Any] = {}

    def capture_default(fn: Any) -> Any:
        captured["default"] = fn

        return fn

    def capture_pre_nav(fn: Any) -> Any:
        captured["pre_nav"] = fn

        return fn

    with patch("src.reader.strategies.crawlee_strategy.AdaptivePlaywrightCrawler") as mock_crawler_cls:
        mock_crawler = MagicMock()
        mock_crawler.run = AsyncMock(return_value=final_statistics(1))
        mock_crawler.router.default_handler = capture_default
        mock_crawler.pre_navigation_hook = capture_pre_nav
        mock_crawler_cls.with_beautifulsoup_static_parser.return_value = mock_crawler

        url_validator = MagicMock()
        url_validator.route_handler = AsyncMock()
        strategy = CrawleeStrategy(url_validator)
        await strategy.get_html("http://test.com")

    # Now invoke the captured handlers directly to cover their bodies.
    context_playwright = MagicMock()
    context_playwright.page = MagicMock()
    context_playwright.page.content = AsyncMock(return_value="<html>x</html>")
    context_playwright.page.context.route = AsyncMock()
    context_playwright.page.context.route_web_socket = None

    # when
    await captured["pre_nav"](context_playwright)

    # then
    context_playwright.page.context.route.assert_awaited_once()

    container_handler = captured["default"]
    # The default handler routes through _handle_crawlee_request which we already cover.
    plain_context = MagicMock()
    plain_context.page.content = AsyncMock(return_value="<html>handled</html>")
    await container_handler(plain_context)


@pytest.mark.asyncio
async def test_crawlee_extract_empty_when_trafilatura_none() -> None:
    # when
    with (
        patch("src.reader.strategies.crawlee_strategy.AdaptivePlaywrightCrawler") as mock_crawler_cls,
        patch(
            "src.reader.strategies.crawlee_strategy.trafilatura.extract",
            return_value=None,
        ),
    ):
        mock_crawler = MagicMock()
        mock_crawler.run = AsyncMock(return_value=final_statistics(1))
        mock_crawler.router.default_handler = lambda f: f
        mock_crawler.pre_navigation_hook = lambda f: f
        mock_crawler_cls.with_beautifulsoup_static_parser.return_value = mock_crawler
        strategy = CrawleeStrategy(MagicMock())
        result = await strategy.extract("http://test.com")

    # then
    assert result == ""

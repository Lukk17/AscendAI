from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.api.exceptions import ChallengeDetectedException
from src.reader.strategies.beautifulsoup_strategy import BeautifulSoupStrategy
from src.reader.strategies.crawlee_strategy import CrawleeStrategy
from src.reader.strategies.curl_cffi_fetcher import fetch_with_curl_cffi
from src.reader.strategies.playwright_strategy import PlaywrightStrategy
from src.reader.strategies.trafilatura_strategy import TrafilaturaStrategy

SAMPLE_HTML = "<html><body><p>Text</p><script>bad</script></body></html>"


class _MockResponse:
    def __init__(self, html: str = SAMPLE_HTML, status: int = 200) -> None:
        self.status_code = status
        self.text = html
        self.url = "http://test.com"

    def raise_for_status(self):
        return None


def _make_curl_session(response: _MockResponse) -> MagicMock:
    session = MagicMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    session.get = AsyncMock(return_value=response)

    return session


@pytest.fixture
def patch_cookies_none():
    with patch(
        "src.reader.strategies.curl_cffi_fetcher.cookie_manager.get_session_data",
        new=AsyncMock(return_value=None),
    ):
        yield


@pytest.mark.asyncio
async def test_curl_cffi_fetcher_returns_html(patch_cookies_none):
    session = _make_curl_session(_MockResponse(SAMPLE_HTML))
    with patch(
        "src.reader.strategies.curl_cffi_fetcher.requests.AsyncSession",
        return_value=session,
    ):
        result = await fetch_with_curl_cffi("http://test.com", lambda: "ua", "TestStrat")
    assert result == SAMPLE_HTML


@pytest.mark.asyncio
async def test_curl_cffi_fetcher_uses_cached_cookies():
    session = _make_curl_session(_MockResponse(SAMPLE_HTML))
    with (
        patch(
            "src.reader.strategies.curl_cffi_fetcher.cookie_manager.get_session_data",
            new=AsyncMock(return_value={"cookies": {"cf_clearance": "x"}, "user_agent": "cached-ua"}),
        ),
        patch(
            "src.reader.strategies.curl_cffi_fetcher.requests.AsyncSession",
            return_value=session,
        ),
    ):
        result = await fetch_with_curl_cffi("http://test.com", lambda: "fallback", "TestStrat")
    assert result == SAMPLE_HTML
    call = session.get.call_args
    assert call.kwargs["headers"]["User-Agent"] == "cached-ua"
    assert call.kwargs["cookies"] == {"cf_clearance": "x"}


@pytest.mark.asyncio
async def test_curl_cffi_fetcher_raises_on_login_wall(patch_cookies_none):
    session = _make_curl_session(_MockResponse(SAMPLE_HTML))
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
    assert exc.value.intervention_type == "login"


@pytest.mark.asyncio
async def test_curl_cffi_fetcher_raises_on_waf_block(patch_cookies_none):
    session = _make_curl_session(_MockResponse(SAMPLE_HTML))
    with (
        patch(
            "src.reader.strategies.curl_cffi_fetcher.requests.AsyncSession",
            return_value=session,
        ),
        patch(
            "src.reader.strategies.curl_cffi_fetcher.ChallengeDetector.is_login_required",
            return_value=False,
        ),
        patch(
            "src.reader.strategies.curl_cffi_fetcher.ChallengeDetector.is_blocked",
            return_value=True,
        ),
    ):
        with pytest.raises(ChallengeDetectedException) as exc:
            await fetch_with_curl_cffi("http://test.com", lambda: "ua", "TestStrat")
    assert exc.value.intervention_type == "captcha"


@pytest.mark.asyncio
async def test_curl_cffi_fetcher_returns_empty_on_transport_error(patch_cookies_none):
    with patch(
        "src.reader.strategies.curl_cffi_fetcher.requests.AsyncSession",
        side_effect=RuntimeError("net"),
    ):
        result = await fetch_with_curl_cffi("http://test.com", lambda: "ua", "TestStrat")
    assert result == ""


@pytest.mark.asyncio
async def test_beautifulsoup_extract_strips_noise(patch_cookies_none):
    session = _make_curl_session(_MockResponse(SAMPLE_HTML))
    strategy = BeautifulSoupStrategy(lambda: "ua")
    with patch(
        "src.reader.strategies.curl_cffi_fetcher.requests.AsyncSession",
        return_value=session,
    ):
        result = await strategy.extract("http://test.com")
    assert "Text" in result
    assert "bad" not in result


@pytest.mark.asyncio
async def test_beautifulsoup_extract_empty_html(patch_cookies_none):
    with patch(
        "src.reader.strategies.beautifulsoup_strategy.fetch_with_curl_cffi",
        new=AsyncMock(return_value=""),
    ):
        strategy = BeautifulSoupStrategy(lambda: "ua")
        result = await strategy.extract("http://test.com")
    assert result == ""


@pytest.mark.asyncio
async def test_trafilatura_extract(patch_cookies_none):
    with (
        patch(
            "src.reader.strategies.trafilatura_strategy.fetch_with_curl_cffi",
            new=AsyncMock(return_value=SAMPLE_HTML),
        ),
        patch(
            "src.reader.strategies.trafilatura_strategy.trafilatura.extract",
            return_value="Extracted",
        ),
    ):
        strategy = TrafilaturaStrategy(lambda: "ua")
        result = await strategy.extract("http://test.com")
    assert result == "Extracted"


@pytest.mark.asyncio
async def test_trafilatura_extract_empty_html():
    with patch(
        "src.reader.strategies.trafilatura_strategy.fetch_with_curl_cffi",
        new=AsyncMock(return_value=""),
    ):
        strategy = TrafilaturaStrategy(lambda: "ua")
        result = await strategy.extract("http://test.com")
    assert result == ""


@pytest.mark.asyncio
async def test_trafilatura_extract_returns_empty_when_trafilatura_returns_none(patch_cookies_none):
    with (
        patch(
            "src.reader.strategies.trafilatura_strategy.fetch_with_curl_cffi",
            new=AsyncMock(return_value=SAMPLE_HTML),
        ),
        patch(
            "src.reader.strategies.trafilatura_strategy.trafilatura.extract",
            return_value=None,
        ),
    ):
        strategy = TrafilaturaStrategy(lambda: "ua")
        result = await strategy.extract("http://test.com")
    assert result == ""


# Playwright strategy: use the singleton browser_pool which the conftest already mocked.


def _build_playwright_page_mock(html: str, current_url: str = "http://test.com") -> MagicMock:
    page = MagicMock()
    page.url = current_url
    page.content = AsyncMock(return_value=html)
    page.goto = AsyncMock(return_value=MagicMock(status=200))
    page.wait_for_load_state = AsyncMock(side_effect=Exception("nope"))
    page.wait_for_timeout = AsyncMock()
    page.route = AsyncMock()

    return page


def _wire_browser_pool(monkeypatch, page) -> None:
    from src.runtime import browser_pool as bp_module

    context = MagicMock()
    context.new_page = AsyncMock(return_value=page)
    context.close = AsyncMock()

    browser = MagicMock()
    browser.is_connected = MagicMock(return_value=True)
    browser.new_context = AsyncMock(return_value=context)

    monkeypatch.setattr(bp_module.browser_pool, "get_browser", AsyncMock(return_value=browser))


@pytest.mark.asyncio
async def test_playwright_extract_happy_path(monkeypatch):
    page = _build_playwright_page_mock("<html><body>content</body></html>")
    _wire_browser_pool(monkeypatch, page)
    with (
        patch(
            "src.reader.strategies.playwright_strategy.Stealth",
            return_value=MagicMock(apply_stealth_async=AsyncMock()),
        ),
        patch(
            "src.reader.strategies.playwright_strategy.trafilatura.extract",
            return_value="Extracted",
        ),
    ):
        strategy = PlaywrightStrategy(lambda: "ua", MagicMock())
        result = await strategy.extract("http://test.com")
    assert result == "Extracted"


@pytest.mark.asyncio
async def test_playwright_extract_returns_empty_when_trafilatura_none(monkeypatch):
    page = _build_playwright_page_mock("<html></html>")
    _wire_browser_pool(monkeypatch, page)
    with (
        patch(
            "src.reader.strategies.playwright_strategy.Stealth",
            return_value=MagicMock(apply_stealth_async=AsyncMock()),
        ),
        patch(
            "src.reader.strategies.playwright_strategy.trafilatura.extract",
            return_value=None,
        ),
    ):
        strategy = PlaywrightStrategy(lambda: "ua", MagicMock())
        result = await strategy.extract("http://test.com")
    assert result == ""


@pytest.mark.asyncio
async def test_playwright_raises_challenge_on_login_redirect_url(monkeypatch):
    page = _build_playwright_page_mock("<html></html>")
    _wire_browser_pool(monkeypatch, page)
    with patch(
        "src.reader.strategies.playwright_strategy.Stealth",
        return_value=MagicMock(apply_stealth_async=AsyncMock()),
    ):
        strategy = PlaywrightStrategy(lambda: "ua", MagicMock())
        with pytest.raises(ChallengeDetectedException) as exc:
            await strategy.get_html("http://test.com?login=1")
    assert exc.value.intervention_type == "login"


@pytest.mark.asyncio
async def test_playwright_raises_challenge_on_login_wall_during_poll(monkeypatch):
    page = _build_playwright_page_mock("<html></html>")
    _wire_browser_pool(monkeypatch, page)
    with (
        patch(
            "src.reader.strategies.playwright_strategy.Stealth",
            return_value=MagicMock(apply_stealth_async=AsyncMock()),
        ),
        patch(
            "src.reader.strategies.playwright_strategy.ChallengeDetector.is_login_required",
            return_value=True,
        ),
    ):
        strategy = PlaywrightStrategy(lambda: "ua", MagicMock())
        with pytest.raises(ChallengeDetectedException) as exc:
            await strategy.get_html("http://test.com")
    assert exc.value.intervention_type == "login"


@pytest.mark.asyncio
async def test_playwright_raises_challenge_on_blocked_during_poll(monkeypatch):
    page = _build_playwright_page_mock("<html></html>")
    _wire_browser_pool(monkeypatch, page)
    with (
        patch(
            "src.reader.strategies.playwright_strategy.Stealth",
            return_value=MagicMock(apply_stealth_async=AsyncMock()),
        ),
        patch(
            "src.reader.strategies.playwright_strategy.ChallengeDetector.is_login_required",
            return_value=False,
        ),
        patch(
            "src.reader.strategies.playwright_strategy.ChallengeDetector.is_blocked",
            return_value=True,
        ),
    ):
        strategy = PlaywrightStrategy(lambda: "ua", MagicMock())
        with pytest.raises(ChallengeDetectedException) as exc:
            await strategy.get_html("http://test.com")
    assert exc.value.intervention_type == "captcha"


@pytest.mark.asyncio
async def test_playwright_raises_late_login_wall(monkeypatch):
    page = _build_playwright_page_mock("<html></html>")
    page.wait_for_load_state = AsyncMock(return_value=None)
    _wire_browser_pool(monkeypatch, page)

    # First poll round clean, late-stage check positive
    call_count = [0]

    def is_login(_url, _html):
        call_count[0] += 1
        return call_count[0] > 1  # only the late-stage call returns True

    with (
        patch(
            "src.reader.strategies.playwright_strategy.Stealth",
            return_value=MagicMock(apply_stealth_async=AsyncMock()),
        ),
        patch(
            "src.reader.strategies.playwright_strategy.ChallengeDetector.is_login_required",
            side_effect=is_login,
        ),
    ):
        strategy = PlaywrightStrategy(lambda: "ua", MagicMock())
        with pytest.raises(ChallengeDetectedException) as exc:
            await strategy.get_html("http://test.com")
    assert exc.value.intervention_type == "login"


# Crawlee strategy


@pytest.mark.asyncio
async def test_crawlee_strategy_extract_returns_trafilatura_result():
    with (
        patch("src.reader.strategies.crawlee_strategy.AdaptivePlaywrightCrawler") as mock_crawler_cls,
        patch(
            "src.reader.strategies.crawlee_strategy.trafilatura.extract",
            return_value="Crawlee",
        ),
    ):
        mock_crawler = MagicMock()
        mock_crawler.run = AsyncMock()
        mock_crawler.router.default_handler = lambda f: f
        mock_crawler.pre_navigation_hook = lambda f: f
        mock_crawler_cls.with_beautifulsoup_static_parser.return_value = mock_crawler
        strategy = CrawleeStrategy(MagicMock())
        result = await strategy.extract("http://test.com")
    assert result == "Crawlee"


@pytest.mark.asyncio
async def test_crawlee_strategy_raises_challenge_on_login_wall():
    with (
        patch("src.reader.strategies.crawlee_strategy.AdaptivePlaywrightCrawler") as mock_crawler_cls,
        patch(
            "src.reader.strategies.crawlee_strategy.ChallengeDetector.is_login_required",
            return_value=True,
        ),
    ):
        mock_crawler = MagicMock()
        mock_crawler.run = AsyncMock()
        mock_crawler.router.default_handler = lambda f: f
        mock_crawler.pre_navigation_hook = lambda f: f
        mock_crawler_cls.with_beautifulsoup_static_parser.return_value = mock_crawler
        strategy = CrawleeStrategy(MagicMock())
        with pytest.raises(ChallengeDetectedException) as exc:
            await strategy.get_html("http://test.com")
    assert exc.value.intervention_type == "login"


@pytest.mark.asyncio
async def test_crawlee_strategy_raises_challenge_on_waf_block():
    with (
        patch("src.reader.strategies.crawlee_strategy.AdaptivePlaywrightCrawler") as mock_crawler_cls,
        patch(
            "src.reader.strategies.crawlee_strategy.ChallengeDetector.is_login_required",
            return_value=False,
        ),
        patch(
            "src.reader.strategies.crawlee_strategy.ChallengeDetector.is_blocked",
            return_value=True,
        ),
    ):
        mock_crawler = MagicMock()
        mock_crawler.run = AsyncMock()
        mock_crawler.router.default_handler = lambda f: f
        mock_crawler.pre_navigation_hook = lambda f: f
        mock_crawler_cls.with_beautifulsoup_static_parser.return_value = mock_crawler
        strategy = CrawleeStrategy(MagicMock())
        with pytest.raises(ChallengeDetectedException) as exc:
            await strategy.get_html("http://test.com")
    assert exc.value.intervention_type == "captcha"


@pytest.mark.asyncio
async def test_crawlee_handle_request_playwright_context():
    from crawlee.crawlers import PlaywrightCrawlingContext

    strategy = CrawleeStrategy(MagicMock())
    context = MagicMock(spec=PlaywrightCrawlingContext)
    context.page = MagicMock()
    context.page.content = AsyncMock(return_value="<html>from playwright</html>")
    result_container = {"html": ""}
    await strategy._handle_crawlee_request(context, result_container)
    assert "playwright" in result_container["html"]


@pytest.mark.asyncio
async def test_crawlee_handle_request_soup_context():
    strategy = CrawleeStrategy(MagicMock())
    context = MagicMock(spec=[])
    context.soup = "<html>soup</html>"
    result_container = {"html": ""}
    await strategy._handle_crawlee_request(context, result_container)
    assert "soup" in result_container["html"]


@pytest.mark.asyncio
async def test_crawlee_handle_request_response_context():
    strategy = CrawleeStrategy(MagicMock())
    context = MagicMock(spec=[])
    response = MagicMock()
    response.text = "<html>response</html>"
    context.response = response
    result_container = {"html": ""}
    await strategy._handle_crawlee_request(context, result_container)
    assert "response" in result_container["html"]


@pytest.mark.asyncio
async def test_crawlee_handle_request_unknown_context_no_op():
    strategy = CrawleeStrategy(MagicMock())
    context = MagicMock(spec=[])  # no soup, no response, not PlaywrightCrawlingContext
    result_container = {"html": ""}
    await strategy._handle_crawlee_request(context, result_container)
    assert result_container["html"] == ""


@pytest.mark.asyncio
async def test_crawlee_decorated_handlers_executed():
    """The crawlee strategy registers two decorated inner functions
    (request_handler and enable_adblock). Capture them and invoke directly so
    their bodies are covered."""
    captured: dict[str, Any] = {}

    def capture_default(fn):
        captured["default"] = fn

        return fn

    def capture_pre_nav(fn):
        captured["pre_nav"] = fn

        return fn

    with patch("src.reader.strategies.crawlee_strategy.AdaptivePlaywrightCrawler") as mock_crawler_cls:
        mock_crawler = MagicMock()
        mock_crawler.run = AsyncMock()
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
    context_playwright.page.route = AsyncMock()

    await captured["pre_nav"](context_playwright)
    context_playwright.page.route.assert_awaited_once()

    container_handler = captured["default"]
    # The default handler routes through _handle_crawlee_request which we already cover.
    soup_context = MagicMock(spec=[])
    soup_context.soup = "<html>handled</html>"
    await container_handler(soup_context)


@pytest.mark.asyncio
async def test_crawlee_extract_empty_when_trafilatura_none():
    with (
        patch("src.reader.strategies.crawlee_strategy.AdaptivePlaywrightCrawler") as mock_crawler_cls,
        patch(
            "src.reader.strategies.crawlee_strategy.trafilatura.extract",
            return_value=None,
        ),
    ):
        mock_crawler = MagicMock()
        mock_crawler.run = AsyncMock()
        mock_crawler.router.default_handler = lambda f: f
        mock_crawler.pre_navigation_hook = lambda f: f
        mock_crawler_cls.with_beautifulsoup_static_parser.return_value = mock_crawler
        strategy = CrawleeStrategy(MagicMock())
        result = await strategy.extract("http://test.com")
    assert result == ""

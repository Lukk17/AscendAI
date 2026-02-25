from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.reader.strategies.crawlee_strategy import CrawleeStrategy
from src.reader.strategies.beautifulsoup_strategy import BeautifulSoupStrategy
from src.reader.strategies.playwright_strategy import PlaywrightStrategy
from src.reader.strategies.trafilatura_strategy import TrafilaturaStrategy

SAMPLE_HTML = "<html><body><p>Text</p><script>bad</script></body></html>"


class MockResponse:
    def __init__(self):
        self.status = 200


class MockPage:
    def __init__(self, html: str = "<html></html>"):
        self.url = "http://test.com"
        self.goto = AsyncMock(return_value=MockResponse())
        self.wait_for_timeout = AsyncMock()
        self.content = AsyncMock(return_value=html)
        self.route = AsyncMock()
        self.evaluate = AsyncMock()
        self.add_init_script = AsyncMock()


class MockContext:
    def __init__(self, html: str = "<html></html>"):
        self.page = MockPage(html)
        self.new_page = AsyncMock(return_value=self.page)
        self.close = AsyncMock()


class MockBrowser:
    def __init__(self, html: str = "<html></html>"):
        self.context = MockContext(html)
        self.new_context = AsyncMock(return_value=self.context)
        self.close = AsyncMock()


def _make_httpx_mock(html: str):
    mock_response = MagicMock()
    mock_response.text = html
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.get = AsyncMock(return_value=mock_response)
    return mock_client


@pytest.mark.asyncio
async def test_trafilatura_strategy_extract():
    strategy = TrafilaturaStrategy(lambda: "test-ua")

    with patch("src.reader.strategies.trafilatura_strategy.requests.AsyncSession") as mock_cls:
        mock_cls.return_value = _make_httpx_mock(SAMPLE_HTML)
        with patch("src.reader.strategies.trafilatura_strategy.trafilatura.extract", return_value="Extracted"):
            result = await strategy.extract("http://test.com")
            assert result == "Extracted"


@pytest.mark.asyncio
async def test_trafilatura_strategy_get_html():
    strategy = TrafilaturaStrategy(lambda: "test-ua")

    with patch("src.reader.strategies.trafilatura_strategy.requests.AsyncSession") as mock_cls:
        mock_cls.return_value = _make_httpx_mock(SAMPLE_HTML)
        result = await strategy.get_html("http://test.com")
        assert result == SAMPLE_HTML


@pytest.mark.asyncio
async def test_beautifulsoup_strategy_extract():
    strategy = BeautifulSoupStrategy(lambda: "test-ua")

    with patch("src.reader.strategies.beautifulsoup_strategy.requests.AsyncSession") as mock_cls:
        mock_cls.return_value = _make_httpx_mock(SAMPLE_HTML)
        result = await strategy.extract("http://test.com")
        assert "Text" in result
        assert "bad" not in result


@pytest.mark.asyncio
async def test_beautifulsoup_strategy_get_html():
    strategy = BeautifulSoupStrategy(lambda: "test-ua")

    with patch("src.reader.strategies.beautifulsoup_strategy.requests.AsyncSession") as mock_cls:
        mock_cls.return_value = _make_httpx_mock(SAMPLE_HTML)
        result = await strategy.get_html("http://test.com")
        assert result == SAMPLE_HTML


@pytest.mark.asyncio
async def test_playwright_strategy_extract():
    strategy = PlaywrightStrategy(lambda: "test-ua", MagicMock())
    mock_browser = MockBrowser("<html><body>content</body></html>")

    with patch("src.reader.strategies.playwright_strategy.async_playwright") as mock_pw:
        mock_ctx_mgr = AsyncMock()
        mock_pw.return_value = mock_ctx_mgr
        mock_ctx_mgr.__aenter__.return_value.chromium.launch.return_value = mock_browser

        with patch("src.reader.strategies.playwright_strategy.Stealth") as mock_stealth_cls:
            mock_stealth_cls.return_value = AsyncMock()
            with patch("src.reader.strategies.playwright_strategy.trafilatura.extract", return_value="PW Extracted"):
                result = await strategy.extract("http://test.com")
                assert result == "PW Extracted"


@pytest.mark.asyncio
async def test_playwright_strategy_get_html():
    rendered_html = "<html><body>JS rendered</body></html>"
    strategy = PlaywrightStrategy(lambda: "test-ua", MagicMock())
    mock_browser = MockBrowser(rendered_html)

    with patch("src.reader.strategies.playwright_strategy.async_playwright") as mock_pw:
        mock_ctx_mgr = AsyncMock()
        mock_pw.return_value = mock_ctx_mgr
        mock_ctx_mgr.__aenter__.return_value.chromium.launch.return_value = mock_browser

        with patch("src.reader.strategies.playwright_strategy.Stealth") as mock_stealth_cls:
            mock_stealth_cls.return_value = AsyncMock()
            result = await strategy.get_html("http://test.com")
            assert result == rendered_html


@pytest.mark.asyncio
async def test_crawlee_strategy_extract():
    strategy = CrawleeStrategy(MagicMock())

    with patch("src.reader.strategies.crawlee_strategy.AdaptivePlaywrightCrawler") as mock_crawler_cls:
        mock_crawler = AsyncMock()
        mock_crawler_cls.with_beautifulsoup_static_parser.return_value = mock_crawler
        mock_crawler.run = AsyncMock()
        await strategy.extract("http://test.com")
        mock_crawler.run.assert_called()


@pytest.mark.asyncio
async def test_crawlee_strategy_get_html():
    strategy = CrawleeStrategy(MagicMock())

    with patch("src.reader.strategies.crawlee_strategy.AdaptivePlaywrightCrawler") as mock_crawler_cls:
        mock_crawler = AsyncMock()
        mock_crawler_cls.with_beautifulsoup_static_parser.return_value = mock_crawler
        mock_crawler.run = AsyncMock()
        result = await strategy.get_html("http://test.com")
        assert isinstance(result, str)
        mock_crawler.run.assert_called()

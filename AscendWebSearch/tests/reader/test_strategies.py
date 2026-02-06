from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.reader.strategies.crawlee_strategy import CrawleeStrategy
from src.reader.strategies.fallback_strategy import FallbackStrategy
from src.reader.strategies.playwright_strategy import PlaywrightStrategy
from src.reader.strategies.trafilatura_strategy import TrafilaturaStrategy


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_crawlee_strategy_success():
    mock_validator = MagicMock()
    strategy = CrawleeStrategy(mock_validator)

    # Mock the internal AdaptivePlaywrightCrawler usage
    with patch("src.reader.strategies.crawlee_strategy.AdaptivePlaywrightCrawler") as mock_crawler_cls:
        mock_crawler = AsyncMock()
        mock_crawler_cls.return_value = mock_crawler

        # Mock run method to simulate processing
        mock_crawler.run = AsyncMock()

        # We need to ensure the run call doesn't fail and we can assert on it.
        # Since logic isn't fully mocked for extraction (it's inside the crawler callbacks),
        # minimal assertion is that we instantiated it correctly and called run.
        await strategy.extract("http://test.com")

        mock_crawler.run.assert_called()


@pytest.mark.asyncio
async def test_trafilatura_strategy_success():
    mock_provider = lambda: "test-ua"
    strategy = TrafilaturaStrategy(mock_provider)

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "<html>content</html>"
        mock_get.return_value = mock_resp

        with patch("trafilatura.extract", return_value="Extracted") as mock_extract:
            result = await strategy.extract("http://test.com")
            assert result == "Extracted"


@pytest.mark.asyncio
async def test_fallback_strategy_success():
    mock_provider = lambda: "test-ua"
    strategy = FallbackStrategy(mock_provider)

    mock_html = "<html><body><p>Text</p><script>bad</script></body></html>"

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = mock_html
        mock_get.return_value = mock_resp

        result = await strategy.extract("http://test.com")
        assert "Text" in result
        assert "bad" not in result  # Script removed


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_playwright_strategy_success():
    mock_provider = lambda: "test-ua"
    mock_validator = MagicMock()
    strategy = PlaywrightStrategy(mock_provider, mock_validator)

    # Custom Mock Classes to ensure proper async behavior
    class MockPage:
        def __init__(self):
            self.goto = AsyncMock()
            self.wait_for_timeout = AsyncMock()
            self.content = AsyncMock(return_value="<html></html>")
            self.route = AsyncMock()
            # Add evaluate/add_init_script just in case, though patching Stealth should avoid their use
            self.evaluate = AsyncMock()
            self.add_init_script = AsyncMock()

    class MockContext:
        def __init__(self):
            self.page = MockPage()
            self.new_page = AsyncMock(return_value=self.page)
            self.close = AsyncMock(return_value=None)

    class MockBrowser:
        def __init__(self):
            self.context = MockContext()
            self.new_context = AsyncMock(return_value=self.context)
            self.close = AsyncMock(return_value=None)

    mock_browser_instance = MockBrowser()

    with patch("src.reader.strategies.playwright_strategy.async_playwright") as mock_pw:
        mock_ctx_mgr = AsyncMock()
        mock_pw.return_value = mock_ctx_mgr
        mock_ctx_mgr.__aenter__.return_value.chromium.launch.return_value = mock_browser_instance

        # Patch Stealth to prevent it from trying to execute scripts on our mock page (which causes hangs/errors)
        with patch("src.reader.strategies.playwright_strategy.Stealth") as mock_stealth_cls:
            mock_stealth_instance = AsyncMock()
            mock_stealth_cls.return_value = mock_stealth_instance

            with patch("trafilatura.extract", return_value="PW Extracted"):
                result = await strategy.extract("http://test.com")
                assert result == "PW Extracted"
                mock_browser_instance.context.page.goto.assert_called()
                # Verify stealth was applied
                mock_stealth_instance.apply_stealth_async.assert_called_with(mock_browser_instance.context.page)

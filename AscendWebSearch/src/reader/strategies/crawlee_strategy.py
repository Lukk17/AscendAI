import trafilatura
from crawlee.crawlers import AdaptivePlaywrightCrawler, PlaywrightCrawlingContext

from src.config.config import settings
from src.reader.strategies.base_strategy import BaseStrategy
from src.validator.url_validator import URLValidator


class CrawleeStrategy(BaseStrategy):
    def __init__(self, url_validator: URLValidator):
        self.url_validator = url_validator

    async def extract(self, url: str) -> str:
        result_container = {"content": ""}

        crawler = AdaptivePlaywrightCrawler(
            max_requests_per_crawl=settings.MAX_REQUESTS_PER_CRAWL,
            headless=True,
            browser_type='chromium',
        )

        @crawler.router.default_handler
        async def request_handler(context):
            await self._handle_crawlee_request(context, result_container)

        @crawler.pre_navigation_hook
        async def enable_adblock(context: PlaywrightCrawlingContext) -> None:
            await context.page.route("**/*", self.url_validator.route_handler)

        await crawler.run([url])
        return result_container["content"]

    async def _handle_crawlee_request(self, context, result_container) -> None:
        if isinstance(context, PlaywrightCrawlingContext):
            await self._handle_playwright_context(context, result_container)
        elif hasattr(context, 'soup'):
            result_container["content"] = trafilatura.extract(str(context.soup)) or ""
        elif hasattr(context, 'response'):
            result_container["content"] = trafilatura.extract(context.response.text) or ""

    async def _handle_playwright_context(self, context: PlaywrightCrawlingContext, result_container) -> None:
        page = context.page
        content = await page.content()
        result_container["content"] = trafilatura.extract(content) or ""

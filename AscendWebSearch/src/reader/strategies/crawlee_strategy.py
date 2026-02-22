import trafilatura
from crawlee.crawlers import AdaptivePlaywrightCrawler, PlaywrightCrawlingContext

from src.config.config import settings
from src.reader.strategies.base_strategy import BaseStrategy
from src.validator.url_validator import URLValidator


class CrawleeStrategy(BaseStrategy):
    def __init__(self, url_validator: URLValidator):
        self.url_validator = url_validator

    async def extract(self, url: str) -> str:
        html = await self.get_html(url)
        extracted = trafilatura.extract(html)
        return extracted if extracted else ""

    async def get_html(self, url: str) -> str:
        result_container: dict[str, str] = {"html": ""}

        crawler = AdaptivePlaywrightCrawler.with_beautifulsoup_static_parser(
            max_requests_per_crawl=settings.MAX_REQUESTS_PER_CRAWL,
            browser_pool_options={"headless": False}
        )

        @crawler.router.default_handler
        async def request_handler(context):
            await self._handle_crawlee_request(context, result_container)

        @crawler.pre_navigation_hook
        async def enable_adblock(context: PlaywrightCrawlingContext) -> None:
            await context.page.route("**/*", self.url_validator.route_handler)

        await crawler.run([url])
        return result_container["html"]

    async def _handle_crawlee_request(self, context, result_container: dict[str, str]) -> None:
        if isinstance(context, PlaywrightCrawlingContext):
            result_container["html"] = await context.page.content()
        elif hasattr(context, 'soup'):
            result_container["html"] = str(context.soup)
        elif hasattr(context, 'response'):
            result_container["html"] = context.response.text

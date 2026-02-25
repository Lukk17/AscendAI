from typing import Any
from crawlee.crawlers import AdaptivePlaywrightCrawler, PlaywrightCrawlingContext
from crawlee.browsers import PlaywrightBrowserPlugin

from src.config.config import settings
from src.api.exceptions import ChallengeDetectedException
from src.reader.cloudflare.challenge_detector import ChallengeDetector
from src.reader.strategies.base_strategy import BaseStrategy
from src.validator.url_validator import URLValidator

import logging
import trafilatura

logger = logging.getLogger(__name__)


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
            playwright_crawler_specific_kwargs={
                "headless": False,
                "browser_launch_options": {"chromium_sandbox": False},
                "browser_context_options": {
                    "locale": "en-US",
                    "timezone_id": "America/New_York",
                    "geolocation": {"latitude": 37.7749, "longitude": -122.4194},
                    "permissions": ["geolocation"]
                }
            }
        )

        @crawler.router.default_handler
        async def request_handler(context):
            await self._handle_crawlee_request(context, result_container)

        @crawler.pre_navigation_hook
        async def enable_adblock(context: PlaywrightCrawlingContext) -> None:
            await context.page.route("**/*", self.url_validator.route_handler)

        await crawler.run([url])
        html = result_container.get("html", "")
        
        if ChallengeDetector.is_login_required(url, html):
            logger.warning(f"CrawleeStrategy: Login wall detected on {url}")
            raise ChallengeDetectedException(intervention_type="login")
            
        if ChallengeDetector.is_blocked(200, html):
            logger.warning(f"CrawleeStrategy: WAF/Cloudflare block detected on {url}")
            raise ChallengeDetectedException(intervention_type="captcha")
            
        return html

    async def _handle_crawlee_request(self, context: Any, result_container: dict[str, str]) -> None:
        if isinstance(context, PlaywrightCrawlingContext):
            result_container["html"] = await context.page.content()
        elif hasattr(context, 'soup'):
            result_container["html"] = str(context.soup)
        elif hasattr(context, 'response'):
            result_container["html"] = context.response.text

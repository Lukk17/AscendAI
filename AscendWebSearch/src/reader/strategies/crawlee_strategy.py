import asyncio
import logging
import os
from pathlib import Path
from typing import Any

import trafilatura
from crawlee.crawlers import AdaptivePlaywrightCrawler, PlaywrightCrawlingContext

from src.api.exceptions import ChallengeDetectedException
from src.config.config import settings
from src.proxy.proxy_provider import proxy_provider
from src.reader.cloudflare.challenge_detector import ChallengeDetector
from src.reader.cloudflare.cookie_manager import cookie_manager
from src.reader.fingerprint import Fingerprint, get_default_fingerprint
from src.reader.strategies.base_strategy import BaseStrategy
from src.validator.url_validator import URLValidator

logger = logging.getLogger(__name__)


class CrawleeStrategy(BaseStrategy):
    def __init__(
        self,
        url_validator: URLValidator,
        profile: str | None = None,
        fingerprint: Fingerprint | None = None,
    ) -> None:
        self.url_validator = url_validator
        self.profile = profile
        self.fingerprint = fingerprint or get_default_fingerprint()

    async def extract(self, url: str) -> str:
        html = await self.get_html(url)
        extracted: str | None = trafilatura.extract(html)
        return extracted or ""

    async def get_html(self, url: str) -> str:
        result_container: dict[str, str] = {"html": ""}

        storage_state = await cookie_manager.get_storage_state(url, self.profile)
        fp = self.fingerprint

        browser_new_context_options: dict[str, Any] = {
            "locale": fp.locale,
            "timezone_id": fp.timezone_id,
            "geolocation": fp.geolocation,
            "permissions": ["geolocation"],
        }
        if storage_state is not None:
            browser_new_context_options["storage_state"] = storage_state

        proxy = proxy_provider.for_playwright()
        if proxy is not None:
            browser_new_context_options["proxy"] = proxy

        playwright_kwargs: Any = {
            "headless": settings.PLAYWRIGHT_HEADLESS,
            "browser_launch_options": {"chromium_sandbox": False},
            "browser_new_context_options": browser_new_context_options,
        }
        crawler = AdaptivePlaywrightCrawler.with_beautifulsoup_static_parser(
            max_requests_per_crawl=settings.MAX_REQUESTS_PER_CRAWL,
            playwright_crawler_specific_kwargs=playwright_kwargs,
        )

        @crawler.router.default_handler
        async def request_handler(context: Any) -> None:
            await self._handle_crawlee_request(context, result_container)

        @crawler.pre_navigation_hook  # type: ignore[arg-type]
        async def enable_adblock(context: PlaywrightCrawlingContext) -> None:
            await context.page.route("**/*", self.url_validator.route_handler)

        # Point Crawlee at an out-of-tree storage dir and purge stale state on each run.
        storage_dir = await asyncio.to_thread(self._prepare_storage_dir, settings.CRAWLEE_STORAGE_DIR)
        os.environ.setdefault("CRAWLEE_STORAGE_DIR", storage_dir)

        await crawler.run([url])
        html = result_container.get("html", "")

        if ChallengeDetector.is_login_required(url, html):
            logger.warning("CrawleeStrategy: Login wall detected on %s", url)
            raise ChallengeDetectedException(intervention_type="login")

        if ChallengeDetector.is_blocked(200, html):
            logger.warning("CrawleeStrategy: WAF/Cloudflare block detected on %s", url)
            raise ChallengeDetectedException(intervention_type="captcha")

        return html

    @staticmethod
    def _prepare_storage_dir(storage_dir_setting: str) -> str:
        """Resolve and create the Crawlee storage directory. Runs in a thread executor."""
        p = Path(storage_dir_setting).resolve()
        p.mkdir(parents=True, exist_ok=True)
        return str(p)

    @staticmethod
    async def _handle_crawlee_request(context: Any, result_container: dict[str, str]) -> None:
        if isinstance(context, PlaywrightCrawlingContext):
            result_container["html"] = await context.page.content()
        elif hasattr(context, "soup"):
            result_container["html"] = str(context.soup)
        elif hasattr(context, "response"):
            result_container["html"] = context.response.text

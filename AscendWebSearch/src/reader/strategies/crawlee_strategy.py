import asyncio
import logging
import os
import time
from pathlib import Path
from typing import Any

import trafilatura
from crawlee.crawlers import (
    AdaptivePlaywrightCrawler,
    AdaptivePlaywrightCrawlingContext,
    AdaptivePlaywrightPreNavCrawlingContext,
)

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
            "use_incognito_pages": True,
        }

        # Crawlee's service locator lazily builds and caches its Configuration singleton
        # the first time any crawler is constructed in this process, and never re-reads
        # the environment afterwards, so both the memory budget and the storage dir must
        # be set before that first construction to have any effect.
        if settings.CRAWLEE_MEMORY_MBYTES is not None:
            os.environ["CRAWLEE_MEMORY_MBYTES"] = str(settings.CRAWLEE_MEMORY_MBYTES)

        storage_dir = await asyncio.to_thread(self._prepare_storage_dir, settings.CRAWLEE_STORAGE_DIR)
        os.environ["CRAWLEE_STORAGE_DIR"] = storage_dir

        crawler = AdaptivePlaywrightCrawler.with_beautifulsoup_static_parser(
            max_requests_per_crawl=settings.MAX_REQUESTS_PER_CRAWL,
            playwright_crawler_specific_kwargs=playwright_kwargs,
        )

        @crawler.router.default_handler
        async def request_handler(context: AdaptivePlaywrightCrawlingContext) -> None:
            await self._handle_crawlee_request(context, result_container)

        @crawler.pre_navigation_hook
        async def enable_adblock(context: AdaptivePlaywrightPreNavCrawlingContext) -> None:
            await context.page.route("**/*", self.url_validator.route_handler)

        await self._run_crawler_bounded(crawler, url)
        html = result_container.get("html", "")

        if ChallengeDetector.is_login_required(html):
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
    async def _run_crawler_bounded(crawler: AdaptivePlaywrightCrawler, url: str) -> None:
        """Run the crawler with a hard wall-clock bound so this tier can never hang forever.

        Crawlee's autoscaler blocks all work indefinitely whenever it considers the
        system memory-overloaded (no request is ever dequeued), and BasicCrawler.run()
        catches CancelledError internally for graceful shutdown, which also swallows the
        cancellation asyncio.wait_for issues on timeout: per the asyncio docs, "if the
        task suppresses the cancellation and returns a value instead, that value is
        returned". Elapsed time is therefore checked explicitly after the call returns,
        so a permanently-overloaded autoscaler still fails this tier instead of silently
        returning empty content after burning the whole read budget.
        """
        crawl_timeout = settings.EXTRACT_TIMEOUT * 2
        started = time.perf_counter()
        try:
            await asyncio.wait_for(crawler.run([url]), timeout=crawl_timeout)
        except TimeoutError as exc:
            raise TimeoutError(
                f"CrawleeStrategy: tier exceeded its {crawl_timeout:.0f}s budget for {url}"
            ) from exc

        elapsed = time.perf_counter() - started
        if elapsed > crawl_timeout:
            raise TimeoutError(
                f"CrawleeStrategy: tier exceeded its {crawl_timeout:.0f}s budget for {url} "
                f"(ran {elapsed:.1f}s; Crawlee's autoscaler likely reports the system as "
                "permanently memory-overloaded)"
            )

    @staticmethod
    async def _handle_crawlee_request(
        context: AdaptivePlaywrightCrawlingContext, result_container: dict[str, str]
    ) -> None:
        try:
            result_container["html"] = await context.page.content()
        except Exception:
            snapshot = await context.get_snapshot()
            result_container["html"] = snapshot.html or ""

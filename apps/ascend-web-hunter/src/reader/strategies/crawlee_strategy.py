from __future__ import annotations

import asyncio
import logging
import os
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import uuid4

import trafilatura
from ascend_python_common.uri_guard import UnsafeUriError, check_fetch_uri
from crawlee import ConcurrencySettings
from crawlee.crawlers import (
    AdaptivePlaywrightCrawler,
    AdaptivePlaywrightCrawlingContext,
    AdaptivePlaywrightPreNavCrawlingContext,
    RenderingTypePrediction,
    RenderingTypePredictor,
)
from crawlee.storage_clients import MemoryStorageClient
from crawlee.storages import RequestQueue

from src.api.exceptions import ChallengeDetectedException, ExtractionFailedError
from src.config.config import settings
from src.observability.safe_address import address_without_query
from src.proxy.proxy_provider import proxy_provider
from src.reader.browser_guard import (
    BrowserFamily,
    browser_tunnel,
    chromium_guard_args,
    guard_page_goto,
    install_browser_guard,
    web_hunter_fetch_policy,
)
from src.reader.cloudflare.challenge_detector import ChallengeDetector
from src.reader.cloudflare.challenge_signals import (
    BLOCK_STATUSES,
    assess,
    log_verdict,
    record_verdict,
)
from src.reader.cloudflare.cookie_manager import cookie_manager
from src.reader.fingerprint import Fingerprint, get_default_fingerprint
from src.reader.strategies.base_strategy import BaseStrategy, FetchedHtml
from src.reader.strategies.browser_read import PageContentError, bounded_page_content
from src.reader.strategies.main_frame_response import DEFAULT_STATUS, MainFrameResponses

if TYPE_CHECKING:
    from bs4 import BeautifulSoup, Tag
    from crawlee import Request
    from crawlee.crawlers import BasicCrawlingContext, ParsedHttpCrawlingContext, RenderingType
    from crawlee.statistics import FinalStatistics

    from src.validator.url_validator import URLValidator

logger = logging.getLogger(__name__)

_CRAWLEE_TIER = "crawlee"

_ONE_TASK_AT_A_TIME = ConcurrencySettings(max_concurrency=1, desired_concurrency=1)


class _ClientOnlyRenderingTypePredictor(RenderingTypePredictor):
    """Predict the browser rendering type for every request, so the static sub-crawler is never used."""

    def predict(self, request: Request) -> RenderingTypePrediction:  # noqa: ARG002
        return RenderingTypePrediction("client only", 0.0)

    def store_result(self, request: Request, rendering_type: RenderingType) -> None:  # noqa: ARG002
        return None


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
        safe_url = address_without_query(url)
        await check_fetch_uri(url, web_hunter_fetch_policy())
        result_container: dict[str, Any] = {"html": "", "status": DEFAULT_STATUS, "headers": {}}

        storage_state = await cookie_manager.get_storage_state(url, self.profile)
        fp = self.fingerprint

        browser_new_context_options: dict[str, Any] = {
            "locale": fp.locale,
            "timezone_id": fp.timezone_id,
            "geolocation": fp.geolocation,
            "permissions": ["geolocation"],
            "service_workers": "block",
        }
        if storage_state is not None:
            browser_new_context_options["storage_state"] = storage_state

        proxy = proxy_provider.for_playwright()
        if proxy is not None:
            browser_new_context_options["proxy"] = browser_tunnel.chained_proxy(proxy)

        playwright_kwargs: Any = {
            "headless": settings.PLAYWRIGHT_HEADLESS,
            "browser_launch_options": {"chromium_sandbox": False, "args": list(chromium_guard_args())},
            "browser_new_context_options": browser_new_context_options,
            "use_incognito_pages": True,
        }

        if settings.CRAWLEE_MEMORY_MBYTES is not None:
            os.environ["CRAWLEE_MEMORY_MBYTES"] = str(settings.CRAWLEE_MEMORY_MBYTES)

        storage_dir = await asyncio.to_thread(self._prepare_storage_dir, settings.CRAWLEE_STORAGE_DIR)
        os.environ["CRAWLEE_STORAGE_DIR"] = storage_dir

        request_manager = await RequestQueue.open(
            name=f"read-{uuid4().hex}",
            storage_client=MemoryStorageClient(),
        )
        try:
            crawler = AdaptivePlaywrightCrawler.with_beautifulsoup_static_parser(
                max_requests_per_crawl=settings.MAX_REQUESTS_PER_CRAWL,
                configure_logging=False,
                concurrency_settings=_ONE_TASK_AT_A_TIME,
                retry_on_blocked=False,
                ignore_http_error_status_codes=BLOCK_STATUSES,
                rendering_type_predictor=_ClientOnlyRenderingTypePredictor(),
                request_manager=request_manager,
                playwright_crawler_specific_kwargs=playwright_kwargs,
            )

            @crawler.router.default_handler
            async def request_handler(
                context: AdaptivePlaywrightCrawlingContext[BeautifulSoup, Tag],
            ) -> None:
                await self._handle_crawlee_request(context, result_container)

            self._guard_each_navigation(crawler, result_container)
            self._stop_after_refused_navigation(crawler, result_container)

            final_statistics = await self._run_crawler_bounded(crawler, url, safe_url)
        finally:
            await request_manager.drop()
        refused_navigations: list[str] = result_container.get("refused_navigations", [])
        if refused_navigations:
            logger.warning("CrawleeStrategy: Blocked navigation detected post-render on %s", safe_url)

            raise UnsafeUriError(f"browser request refused: {refused_navigations[0]}")
        if final_statistics.requests_finished < 1:
            logger.warning(
                "CrawleeStrategy: the crawl handled no request for %s (failed %d of %d)",
                safe_url,
                final_statistics.requests_failed,
                final_statistics.requests_total,
            )

            raise ExtractionFailedError(
                f"CrawleeStrategy: the crawl handled no request for {safe_url} "
                f"(failed {final_statistics.requests_failed} of {final_statistics.requests_total})"
            )
        html: str = result_container.get("html", "")
        status: int = result_container.get("status", DEFAULT_STATUS)
        headers: dict[str, str] = result_container.get("headers", {})
        stored_cookies = (storage_state or {}).get("cookies", [])
        cookie_names = [str(cookie.get("name", "")) for cookie in stored_cookies]

        verdict = await asyncio.to_thread(assess, status, html, headers, cookie_names)
        record_verdict(verdict, _CRAWLEE_TIER)
        log_verdict(verdict, _CRAWLEE_TIER, safe_url)

        login = ChallengeDetector.login_wall_verdict(
            verdict, html, requested_url=url, final_url=result_container.get("final_url", url)
        )
        if login is not None:
            logger.warning("CrawleeStrategy: Login wall detected on %s", safe_url)

            raise ChallengeDetectedException(login)

        if verdict.wall:
            logger.warning("CrawleeStrategy: WAF/Cloudflare block detected on %s", safe_url)

            raise ChallengeDetectedException(verdict)

        return FetchedHtml(html, headers)

    @staticmethod
    def _prepare_storage_dir(storage_dir_setting: str) -> str:
        """Resolve and create the Crawlee storage directory. Runs in a thread executor."""
        p = Path(storage_dir_setting).resolve()
        p.mkdir(parents=True, exist_ok=True)

        return str(p)

    def _guard_each_navigation(
        self,
        crawler: AdaptivePlaywrightCrawler[ParsedHttpCrawlingContext[BeautifulSoup], BeautifulSoup, Tag],
        result_container: dict[str, Any],
    ) -> None:
        """Install the browser guard before each navigation, with the guarded ``page.goto``."""

        @crawler.pre_navigation_hook
        async def install_guard(context: AdaptivePlaywrightPreNavCrawlingContext) -> None:
            result_container["refused_navigations"] = await install_browser_guard(
                context.page.context, self.url_validator, family=BrowserFamily.CHROMIUM
            )
            guard_page_goto(context.page)
            result_container["responses"] = MainFrameResponses(context.page)

    @staticmethod
    def _stop_after_refused_navigation(
        crawler: AdaptivePlaywrightCrawler[ParsedHttpCrawlingContext[BeautifulSoup], BeautifulSoup, Tag],
        result_container: dict[str, Any],
    ) -> None:
        """Stop the crawl before Crawlee retries a navigation the URI guard refused."""

        @crawler.error_handler
        async def stop_crawl(_context: BasicCrawlingContext, _error: Exception) -> None:
            if result_container.get("refused_navigations"):
                crawler.stop("the URI guard refused the navigation")

    @staticmethod
    async def _run_crawler_bounded(
        crawler: AdaptivePlaywrightCrawler[ParsedHttpCrawlingContext[BeautifulSoup], BeautifulSoup, Tag],
        url: str,
        safe_url: str,
    ) -> FinalStatistics:
        """Run the crawler under a wall-clock bound and check the elapsed time after it returns.

        Returns:
            The final statistics of the crawl.

        Raises:
            TimeoutError: when the crawl exceeded its wall-clock budget.
        """
        crawl_timeout = settings.EXTRACT_TIMEOUT * 2
        started = time.perf_counter()
        try:
            final_statistics = await asyncio.wait_for(crawler.run([url]), timeout=crawl_timeout)
        except TimeoutError as exc:
            raise TimeoutError(
                f"CrawleeStrategy: tier exceeded its {crawl_timeout:.0f}s budget for {safe_url}"
            ) from exc

        elapsed = time.perf_counter() - started
        if elapsed > crawl_timeout:
            raise TimeoutError(
                f"CrawleeStrategy: tier exceeded its {crawl_timeout:.0f}s budget for {safe_url} "
                f"(ran {elapsed:.1f}s; Crawlee's autoscaler likely reports the system as "
                "permanently memory-overloaded)"
            )

        return final_statistics

    @staticmethod
    async def _handle_crawlee_request(
        context: AdaptivePlaywrightCrawlingContext[BeautifulSoup, Tag],
        result_container: dict[str, Any],
    ) -> None:
        try:
            result_container["html"] = await bounded_page_content(context.page)
            result_container["final_url"] = context.page.url
        except PageContentError:
            raise
        except Exception:
            snapshot = await context.get_snapshot()
            result_container["html"] = snapshot.html or ""
            result_container["final_url"] = context.request.loaded_url or context.request.url
        responses: MainFrameResponses | None = result_container.get("responses")
        if responses is not None:
            result_container["status"], result_container["headers"] = await responses.status_and_headers()

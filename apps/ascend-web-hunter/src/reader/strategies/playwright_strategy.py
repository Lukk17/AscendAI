from collections.abc import Callable
from typing import Any

import trafilatura
from playwright.async_api import Browser, BrowserContext, Page
from playwright.async_api import Error as PlaywrightError
from playwright_stealth import Stealth

from src.proxy.proxy_provider import proxy_provider
from src.reader.browser_guard import BrowserFamily, browser_tunnel, install_browser_guard
from src.reader.cloudflare.cookie_manager import PRODUCED_BY_PLAYWRIGHT, cookie_manager
from src.reader.fingerprint import Fingerprint, get_default_fingerprint
from src.reader.screenshot import capture_page
from src.reader.strategies.base_strategy import BaseStrategy, FetchedHtml
from src.reader.strategies.browser_read import render_and_judge
from src.reader.strategies.main_frame_response import MainFrameResponses
from src.runtime.browser_pool import browser_pool
from src.validator.url_validator import URLValidator

_PLAYWRIGHT_TIER = "playwright"


class PlaywrightStrategy(BaseStrategy):
    def __init__(
        self,
        user_agent_provider: Callable[[], str],
        url_validator: URLValidator,
        profile: str | None = None,
        fingerprint: Fingerprint | None = None,
    ) -> None:
        self.user_agent_provider = user_agent_provider
        self.url_validator = url_validator
        self.profile = profile
        self.fingerprint = fingerprint or get_default_fingerprint()

    async def extract(self, url: str) -> str:
        html = await self.get_html(url)
        extracted: str | None = trafilatura.extract(html)

        return extracted or ""

    async def screenshot_page(self, url: str) -> tuple[str, bytes] | None:
        """Capture a full-page PNG of *url* through a fresh stealth context."""
        browser = await browser_pool.get_browser()

        return await capture_page(
            lambda: self._create_stealth_context(browser, url),
            url,
            self.url_validator,
            family=BrowserFamily.CHROMIUM,
            tier=_PLAYWRIGHT_TIER,
        )

    async def get_html(self, url: str) -> FetchedHtml:
        browser = await browser_pool.get_browser()
        context = await self._create_stealth_context(browser, url)
        try:
            page = await context.new_page()
            responses = MainFrameResponses(page)
            refused_navigations = await self._apply_protections(page)

            return await render_and_judge(
                page,
                url,
                responses,
                refused_navigations,
                tier=_PLAYWRIGHT_TIER,
                error_type=PlaywrightError,
                producer=PRODUCED_BY_PLAYWRIGHT,
                profile=self.profile,
            )
        finally:
            await context.close()

    async def _create_stealth_context(self, browser: Browser, url: str) -> BrowserContext:
        fp = self.fingerprint
        stored_state = await cookie_manager.get_storage_state(url, self.profile)
        stored_ua = await cookie_manager.get_user_agent(url, self.profile)
        user_agent = stored_ua or fp.user_agent

        kwargs: dict[str, Any] = {
            "user_agent": user_agent,
            "viewport": {"width": fp.viewport_width, "height": fp.viewport_height},
            "locale": fp.locale,
            "timezone_id": fp.timezone_id,
            "geolocation": fp.geolocation,
            "permissions": ["geolocation"],
            "service_workers": "block",
        }
        if stored_state is not None:
            kwargs["storage_state"] = stored_state

        proxy = proxy_provider.for_playwright()
        if proxy is not None:
            kwargs["proxy"] = browser_tunnel.chained_proxy(proxy)

        return await browser.new_context(**kwargs)

    async def _apply_protections(self, page: Page) -> list[str]:
        stealth = Stealth()
        await stealth.apply_stealth_async(page)

        return await install_browser_guard(page.context, self.url_validator, family=BrowserFamily.CHROMIUM)

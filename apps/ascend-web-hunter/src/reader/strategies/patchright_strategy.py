from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any, cast

import trafilatura
from patchright.async_api import Browser, BrowserContext, async_playwright
from patchright.async_api import Error as PatchrightError

from src.config.config import settings
from src.proxy.proxy_provider import proxy_provider
from src.reader.browser_guard import (
    BrowserFamily,
    browser_tunnel,
    chromium_guard_args,
    install_browser_guard,
)
from src.reader.cloudflare.cookie_manager import PRODUCED_BY_PATCHRIGHT, cookie_manager
from src.reader.fingerprint import Fingerprint, get_default_fingerprint
from src.reader.screenshot import capture_page
from src.reader.strategies.base_strategy import BaseStrategy, FetchedHtml
from src.reader.strategies.browser_read import render_and_judge
from src.reader.strategies.main_frame_response import MainFrameResponses
from src.validator.url_validator import URLValidator

if TYPE_CHECKING:
    from playwright.async_api import Page as PlaywrightPage

_PATCHRIGHT_TIER = "patchright"


class PatchrightStrategy(BaseStrategy):
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
        """Capture a full-page PNG of *url* through a fresh patched browser."""
        async with self._launched_browser() as browser:
            return await capture_page(
                lambda: self._create_context(browser, url),
                url,
                self.url_validator,
                family=BrowserFamily.CHROMIUM,
                tier=_PATCHRIGHT_TIER,
            )

    async def get_html(self, url: str) -> FetchedHtml:
        async with self._launched_browser() as browser:
            context = await self._create_context(browser, url)
            try:
                page = cast("PlaywrightPage", await context.new_page())
                responses = MainFrameResponses(page)
                refused_navigations = await self._apply_protections(page)

                return await render_and_judge(
                    page,
                    url,
                    responses,
                    refused_navigations,
                    tier=_PATCHRIGHT_TIER,
                    error_type=PatchrightError,
                    producer=PRODUCED_BY_PATCHRIGHT,
                    profile=self.profile,
                )
            finally:
                await context.close()

    @asynccontextmanager
    async def _launched_browser(self) -> AsyncIterator[Browser]:
        """Launch one Patchright Chromium for a single read and close it after."""
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=settings.PLAYWRIGHT_HEADLESS,
                args=["--no-sandbox", *chromium_guard_args()],
            )
            try:
                yield browser
            finally:
                await browser.close()

    async def _create_context(self, browser: Browser, url: str) -> BrowserContext:
        fp = self.fingerprint
        stored_state = await cookie_manager.get_storage_state(url, self.profile)
        stored_ua = await cookie_manager.get_user_agent(url, self.profile)

        kwargs: dict[str, Any] = {
            "viewport": {"width": fp.viewport_width, "height": fp.viewport_height},
            "locale": fp.locale,
            "timezone_id": fp.timezone_id,
            "geolocation": fp.geolocation,
            "permissions": ["geolocation"],
            "service_workers": "block",
        }
        if stored_state is not None:
            kwargs["storage_state"] = stored_state
        if stored_ua:
            kwargs["user_agent"] = stored_ua

        proxy = proxy_provider.for_playwright()
        if proxy is not None:
            kwargs["proxy"] = browser_tunnel.chained_proxy(proxy)

        return await browser.new_context(**kwargs)

    async def _apply_protections(self, page: "PlaywrightPage") -> list[str]:
        return await install_browser_guard(page.context, self.url_validator, family=BrowserFamily.CHROMIUM)

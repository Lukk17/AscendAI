from typing import Any

import trafilatura
from camoufox.async_api import AsyncCamoufox, AsyncNewContext
from playwright.async_api import BrowserContext, Page
from playwright.async_api import Error as PlaywrightError

from src.config.config import settings
from src.proxy.proxy_provider import proxy_provider
from src.reader.browser_guard import BrowserFamily, browser_tunnel, firefox_guard_prefs, install_browser_guard
from src.reader.cloudflare.cookie_manager import PRODUCED_BY_CAMOUFOX, cookie_manager
from src.reader.fingerprint import Fingerprint, get_default_fingerprint
from src.reader.screenshot import capture_page
from src.reader.strategies.base_strategy import BaseStrategy, FetchedHtml
from src.reader.strategies.browser_read import render_and_judge
from src.reader.strategies.main_frame_response import MainFrameResponses
from src.validator.url_validator import URLValidator

_CAMOUFOX_TIER = "camoufox"


def _launch_kwargs() -> dict[str, Any]:
    return {
        "headless": settings.PLAYWRIGHT_HEADLESS,
        "firefox_user_prefs": dict(firefox_guard_prefs()),
        "main_world_eval": True,
    }


class CamoufoxStrategy(BaseStrategy):
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

    async def screenshot_page(self, url: str) -> tuple[str, bytes] | None:
        """Capture a full-page PNG of *url* through a fresh camoufox browser."""
        proxy = proxy_provider.for_playwright()
        async with AsyncCamoufox(**_launch_kwargs()) as browser:
            return await capture_page(
                lambda: self._create_context(browser, url, proxy),
                url,
                self.url_validator,
                family=BrowserFamily.FIREFOX,
                tier=_CAMOUFOX_TIER,
            )

    async def get_html(self, url: str) -> FetchedHtml:
        proxy = proxy_provider.for_playwright()
        async with AsyncCamoufox(**_launch_kwargs()) as browser:
            context = await self._create_context(browser, url, proxy)
            try:
                page = await context.new_page()
                responses = MainFrameResponses(page)
                refused_navigations = await self._apply_protections(page)

                return await render_and_judge(
                    page,
                    url,
                    responses,
                    refused_navigations,
                    tier=_CAMOUFOX_TIER,
                    error_type=PlaywrightError,
                    producer=PRODUCED_BY_CAMOUFOX,
                    profile=self.profile,
                )
            finally:
                await context.close()

    async def _create_context(self, browser: Any, url: str, proxy: dict[str, str] | None) -> BrowserContext:
        """A Camoufox context with the stored storage_state and no stored user agent."""
        fp = self.fingerprint
        stored_state = await cookie_manager.get_storage_state(url, self.profile)

        context_kwargs: dict[str, Any] = {
            "locale": fp.locale,
            "timezone_id": fp.timezone_id,
            "geolocation": {
                "latitude": fp.geolocation["latitude"],
                "longitude": fp.geolocation["longitude"],
            },
            "permissions": ["geolocation"],
            "service_workers": "block",
        }
        if stored_state is not None:
            context_kwargs["storage_state"] = stored_state

        chained = browser_tunnel.chained_proxy(proxy) if proxy is not None else None

        return await AsyncNewContext(browser, proxy=chained, **context_kwargs)

    async def _apply_protections(self, page: Page) -> list[str]:
        return await install_browser_guard(page.context, self.url_validator, family=BrowserFamily.FIREFOX)

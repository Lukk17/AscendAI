import logging
import time
from collections.abc import Callable
from typing import Any

import trafilatura
from playwright.async_api import Browser, BrowserContext, Page
from playwright.async_api import Error as PlaywrightError
from playwright_stealth import Stealth

from src.api.exceptions import ChallengeDetectedException
from src.config.config import settings
from src.proxy.proxy_provider import proxy_provider
from src.reader.cloudflare.challenge_detector import ChallengeDetector
from src.reader.cloudflare.cookie_manager import cookie_manager
from src.reader.fingerprint import Fingerprint, get_default_fingerprint
from src.reader.strategies.base_strategy import BaseStrategy
from src.runtime.browser_pool import browser_pool
from src.validator.url_validator import URLValidator

logger = logging.getLogger(__name__)

_NETWORKIDLE_POLL_MS = 1000
_MS_PER_SECOND = 1000


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

    async def get_html(self, url: str) -> str:
        browser = await browser_pool.get_browser()
        context = await self._create_stealth_context(browser, url)
        page = await context.new_page()

        await self._apply_protections(page)

        try:
            if ChallengeDetector.is_login_redirect_url(url):
                logger.warning("PlaywrightStrategy: Pre-emptive redirect login URI detected on %s", url)
                raise ChallengeDetectedException(intervention_type="login")

            timeout_ms = settings.EXTRACT_TIMEOUT * _MS_PER_SECOND
            initial_response = await page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)

            response_status = initial_response.status if initial_response else 200
            poll_start = time.perf_counter()
            extract_deadline = poll_start + settings.EXTRACT_TIMEOUT
            challenge_deadline = poll_start + settings.CHALLENGE_CLEAR_WAIT_SECONDS

            content = ""
            while time.perf_counter() < extract_deadline:
                try:
                    content = await page.content()
                except PlaywrightError:
                    await page.wait_for_timeout(_NETWORKIDLE_POLL_MS)
                    continue

                if ChallengeDetector.is_login_required(content):
                    logger.warning("PlaywrightStrategy: Login wall detected on %s (early exit)", url)

                    raise ChallengeDetectedException(intervention_type="login")

                if ChallengeDetector.is_blocked(response_status, content):
                    if time.perf_counter() >= challenge_deadline:
                        logger.warning(
                            "PlaywrightStrategy: WAF/Cloudflare challenge did not auto-clear within "
                            "%ss on %s; escalating",
                            settings.CHALLENGE_CLEAR_WAIT_SECONDS,
                            url,
                        )

                        raise ChallengeDetectedException(intervention_type="captcha")
                    await page.wait_for_timeout(_NETWORKIDLE_POLL_MS)
                    continue

                try:
                    await page.wait_for_load_state("networkidle", timeout=_NETWORKIDLE_POLL_MS)
                    break
                except PlaywrightError:
                    pass

            await page.wait_for_timeout(settings.DYNAMIC_CONTENT_WAIT)
            await self._scroll_page(page)

            content = await page.content()

            logger.info(
                "PlaywrightStrategy: Finished rendering %s. Extracted HTML Length: %d", url, len(content)
            )

            if ChallengeDetector.is_blocked(response_status, content):
                logger.warning("PlaywrightStrategy: WAF/Cloudflare block detected post-render on %s", url)

                raise ChallengeDetectedException(intervention_type="captcha")

            if ChallengeDetector.is_login_required(content):
                logger.warning(
                    "PlaywrightStrategy: Late-stage Login wall detected on %s. Content Length: %d",
                    url,
                    len(content),
                )

                raise ChallengeDetectedException(intervention_type="login")

            return content
        finally:
            await context.close()

    async def _scroll_page(self, page: Page) -> None:
        """Scroll down in increments to trigger lazy-load / infinite-scroll content."""
        for _ in range(settings.SCROLL_ITERATIONS):
            await page.evaluate(f"window.scrollBy(0, {settings.SCROLL_STEP_PX})")
            await page.wait_for_timeout(200)

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
        }
        if stored_state is not None:
            kwargs["storage_state"] = stored_state

        proxy = proxy_provider.for_playwright()
        if proxy is not None:
            kwargs["proxy"] = proxy

        return await browser.new_context(**kwargs)

    async def _apply_protections(self, page: Page) -> None:
        stealth = Stealth()
        await stealth.apply_stealth_async(page)
        await page.route("**/*", self.url_validator.route_handler)

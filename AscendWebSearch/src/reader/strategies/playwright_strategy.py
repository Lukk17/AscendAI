import logging
import random
from collections.abc import Callable

import trafilatura
from playwright.async_api import Browser, BrowserContext, Page, ViewportSize
from playwright_stealth import Stealth

from src.api.exceptions import ChallengeDetectedException
from src.config.config import settings
from src.reader.cloudflare.challenge_detector import ChallengeDetector
from src.reader.strategies.base_strategy import BaseStrategy
from src.runtime.browser_pool import browser_pool
from src.validator.url_validator import URLValidator

logger = logging.getLogger(__name__)

# Viewport jitter — desktop ranges that look human, not bot-perfect.
_VIEWPORT_MIN_WIDTH_PX = 1280
_VIEWPORT_MAX_WIDTH_PX = 1920
_VIEWPORT_MIN_HEIGHT_PX = 720
_VIEWPORT_MAX_HEIGHT_PX = 1080

# Networkidle is polled in 1-second windows so the loop can early-exit on
# detected challenge walls instead of blocking for the full extraction window.
_NETWORKIDLE_POLL_MS = 1000

# Convert the per-strategy timeout from seconds to milliseconds.
_MS_PER_SECOND = 1000


class PlaywrightStrategy(BaseStrategy):
    def __init__(
        self,
        user_agent_provider: Callable[[], str],
        url_validator: URLValidator,
    ) -> None:
        self.user_agent_provider = user_agent_provider
        self.url_validator = url_validator

    async def extract(self, url: str) -> str:
        html = await self.get_html(url)
        extracted: str | None = trafilatura.extract(html)

        return extracted or ""

    async def get_html(self, url: str) -> str:
        browser = await browser_pool.get_browser()
        context = await self._create_stealth_context(browser)
        page = await context.new_page()

        await self._apply_protections(page)

        try:
            if ChallengeDetector.is_login_redirect_url(url):
                logger.warning(f"PlaywrightStrategy: Pre-emptive redirect login URI detected on {url}")
                raise ChallengeDetectedException(intervention_type="login")

            timeout_ms = settings.EXTRACT_TIMEOUT * _MS_PER_SECOND
            initial_response = await page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)

            # Poll incrementally for networkidle to allow early-exit on known block walls
            for _ in range(int(settings.EXTRACT_TIMEOUT)):
                content = await page.content()
                response_status = initial_response.status if initial_response else 200

                if ChallengeDetector.is_login_required(page.url, content):
                    logger.warning(f"PlaywrightStrategy: Login wall detected on {url} (early exit)")
                    raise ChallengeDetectedException(intervention_type="login")

                if ChallengeDetector.is_blocked(response_status, content):
                    logger.warning(f"PlaywrightStrategy: WAF/Cloudflare block detected on {url} (early exit)")
                    raise ChallengeDetectedException(intervention_type="captcha")

                try:
                    await page.wait_for_load_state("networkidle", timeout=_NETWORKIDLE_POLL_MS)
                    break
                except Exception:
                    pass

            await page.wait_for_timeout(settings.DYNAMIC_CONTENT_WAIT)

            content = await page.content()

            logger.info(
                f"PlaywrightStrategy: Finished rendering {url}. Extracted HTML Length: {len(content)}"
            )

            if ChallengeDetector.is_login_required(page.url, content):
                logger.warning(
                    f"PlaywrightStrategy: Late-stage Login wall detected on {url}. "
                    f"Content Length: {len(content)}"
                )
                raise ChallengeDetectedException(intervention_type="login")

            return content
        finally:
            # Only the context is torn down. The browser process lives across requests.
            await context.close()

    async def _create_stealth_context(self, browser: Browser) -> BrowserContext:
        viewport: ViewportSize = {
            "width": random.randint(_VIEWPORT_MIN_WIDTH_PX, _VIEWPORT_MAX_WIDTH_PX),
            "height": random.randint(_VIEWPORT_MIN_HEIGHT_PX, _VIEWPORT_MAX_HEIGHT_PX),
        }

        return await browser.new_context(
            user_agent=self.user_agent_provider(),
            viewport=viewport,
            locale="en-US",
            timezone_id="UTC",
        )

    async def _apply_protections(self, page: Page) -> None:
        stealth = Stealth()
        await stealth.apply_stealth_async(page)
        await page.route("**/*", self.url_validator.route_handler)

import asyncio
import logging

from playwright.async_api import async_playwright

from src.api.exceptions import CaptchaRequiredException
from src.config.config import settings
from src.reader.cloudflare.cookie_manager import cookie_manager
from src.reader.strategies.base_strategy import BaseStrategy

logger = logging.getLogger(__name__)


async def _monitor_for_cookies(url: str):
    logger.info(f"Background task started to monitor cookies for {url}")
    try:
        async with async_playwright() as p:
            browser = await p.chromium.connect_over_cdp(settings.SELENIUM_BROWSER_CDP_URL)
            context = browser.contexts[0] if browser.contexts else await browser.new_context()

            page = await context.new_page()

            try:
                await page.goto(url, wait_until="commit", timeout=120000)
            except Exception as e:
                logger.warning(f"NoVNC Strategy: Initial navigation failed: {e}")

            start_time = asyncio.get_event_loop().time()
            while asyncio.get_event_loop().time() - start_time < 300:
                cookies = await context.cookies()
                cf_clearance = None
                cookie_dict = {}

                for c in cookies:
                    cookie_dict[c["name"]] = c["value"]
                    if c["name"] == "cf_clearance":
                        cf_clearance = c["value"]

                if cf_clearance:
                    logger.info("NoVNC Strategy: Successfully acquired cf_clearance via human resolution!")
                    user_agent = await page.evaluate("navigator.userAgent")
                    await cookie_manager.save_clearance_data(url, cookie_dict, user_agent)
                    break

                await asyncio.sleep(2.0)

            if not page.is_closed():
                await page.close()
            await browser.close()

    except Exception as e:
        logger.error(f"Background noVNC monitoring task failed: {e}")


class NoVNCStrategy(BaseStrategy):
    async def extract(self, url: str) -> str:
        return ""

    async def get_html(self, url: str) -> str:
        if not settings.SELENIUM_BROWSER_CDP_URL or not settings.SELENIUM_BROWSER_VNC_URL:
            logger.warning("NoVNCStrategy skipped: CDP/VNC URL not configured")
            return ""

        asyncio.create_task(_monitor_for_cookies(url))

        raise CaptchaRequiredException(vnc_url=settings.SELENIUM_BROWSER_VNC_URL)

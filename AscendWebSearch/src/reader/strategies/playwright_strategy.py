import random

import trafilatura
from playwright.async_api import async_playwright
from playwright_stealth import Stealth

from src.config.config import settings
from src.reader.strategies.base_strategy import BaseStrategy
from src.validator.url_validator import URLValidator


class PlaywrightStrategy(BaseStrategy):
    def __init__(self, user_agent_provider, url_validator: URLValidator):
        self.user_agent_provider = user_agent_provider
        self.url_validator = url_validator

    async def extract(self, url: str) -> str:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await self._create_stealth_context(browser)
            page = await context.new_page()

            await self._apply_protections(page)

            try:
                # Convert seconds to milliseconds for Playwright
                timeout_ms = settings.EXTRACT_TIMEOUT * 1000
                await page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
                await page.wait_for_timeout(settings.DYNAMIC_CONTENT_WAIT)

                content = await page.content()
                extracted = trafilatura.extract(content)
                return extracted if extracted else ""
            finally:
                await context.close()
                await browser.close()

    async def _create_stealth_context(self, browser):
        viewport = {"width": random.randint(1280, 1920), "height": random.randint(720, 1080)}
        return await browser.new_context(
            user_agent=self.user_agent_provider(),
            viewport=viewport,
            locale="en-US",
            timezone_id="UTC"
        )

    async def _apply_protections(self, page) -> None:
        stealth = Stealth()
        await stealth.apply_stealth_async(page)
        await page.route("**/*", self.url_validator.route_handler)

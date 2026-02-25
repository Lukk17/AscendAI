import random

import trafilatura
from playwright.async_api import async_playwright
from playwright_stealth import Stealth

from src.config.config import settings
from src.api.exceptions import ChallengeDetectedException
from src.reader.cloudflare.challenge_detector import ChallengeDetector
from src.reader.strategies.base_strategy import BaseStrategy
from src.validator.url_validator import URLValidator

import logging
logger = logging.getLogger(__name__)


class PlaywrightStrategy(BaseStrategy):
    def __init__(self, user_agent_provider, url_validator: URLValidator):
        self.user_agent_provider = user_agent_provider
        self.url_validator = url_validator

    async def extract(self, url: str) -> str:
        html = await self.get_html(url)
        extracted = trafilatura.extract(html)
        return extracted if extracted else ""

    async def get_html(self, url: str) -> str:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=False, args=["--no-sandbox"])
            context = await self._create_stealth_context(browser)
            page = await context.new_page()

            await self._apply_protections(page)

            try:
                if ChallengeDetector.is_login_redirect_url(url):
                    logger.warning(f"PlaywrightStrategy: Pre-emptive redirect login URI detected on {url}")
                    raise ChallengeDetectedException(intervention_type="login")

                timeout_ms = settings.EXTRACT_TIMEOUT * 1000
                response = await page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
                
                # Poll incrementally for networkidle to allow early-exit on known block walls
                for _ in range(int(settings.EXTRACT_TIMEOUT)):
                    content = await page.content()
                    status = response.status if response else 200
                    
                    if ChallengeDetector.is_login_required(page.url, content):
                        logger.warning(f"PlaywrightStrategy: Login wall detected on {url} (early exit)")
                        raise ChallengeDetectedException(intervention_type="login")
                        
                    if ChallengeDetector.is_blocked(status, content):
                        logger.warning(f"PlaywrightStrategy: WAF/Cloudflare block detected on {url} (early exit)")
                        raise ChallengeDetectedException(intervention_type="captcha")
                        
                    try:
                        await page.wait_for_load_state("networkidle", timeout=1000)
                        break  # Network idle reached perfectly
                    except Exception:
                        pass  # Still loading, loop again and re-evaluate content
                
                await page.wait_for_timeout(settings.DYNAMIC_CONTENT_WAIT)
                content = await page.content()
                
                logger.info(f"PlaywrightStrategy: Finished rendering {url}. Extracted HTML Length: {len(content)}")
                
                if ChallengeDetector.is_login_required(page.url, content):
                    logger.warning(f"PlaywrightStrategy: Late-stage Login wall detected on {url}. Content Length: {len(content)}")
                    raise ChallengeDetectedException(intervention_type="login")
                
                return content
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

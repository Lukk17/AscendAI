import asyncio
import logging

import httpx
from playwright.async_api import async_playwright

from src.api.exceptions import HumanInterventionRequiredException
from src.config.config import settings
from src.reader.cloudflare.challenge_detector import ChallengeDetector
from src.reader.cloudflare.cookie_manager import cookie_manager
from src.reader.strategies.base_strategy import BaseStrategy

logger = logging.getLogger(__name__)


async def _monitor_for_cookies(url: str, intervention_type: str = "captcha") -> None:
    logger.info(f"Background task started to monitor session for {url} ({intervention_type})")
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=False,
                args=[
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                    "--remote-debugging-port=9222",
                    "--window-position=0,0",
                    "--window-size=1920,1080"
                ]
            )
            context = await browser.new_context(
                locale="en-US",
                timezone_id="America/New_York",
                geolocation={"latitude": 37.7749, "longitude": -122.4194},
                permissions=["geolocation"]
            )

            page = await context.new_page()

            try:
                await page.goto(url, wait_until="commit", timeout=120000)
            except Exception as e:
                logger.warning(f"NoVNC Strategy: Initial navigation failed: {e}")

            start_time = asyncio.get_event_loop().time()
            while asyncio.get_event_loop().time() - start_time < settings.NOVNC_TIMEOUT_SECONDS:
                current_url = page.url
                cookies = await context.cookies()

                success = False

                if intervention_type == "login":
                    try:
                        content = await page.content()
                        if not ChallengeDetector.is_login_redirect_url(
                                current_url) and not ChallengeDetector.is_login_required(current_url,
                                                                                         content) and "about:blank" not in current_url:
                            success = True
                    except Exception as e:
                        logger.warning(f"NoVNC Strategy: Failed to evaluate page content during polling: {e}")
                else:
                    for c in cookies:
                        if c["name"] == "cf_clearance":
                            success = True
                            break

                if success:
                    logger.info("NoVNC Strategy: Successfully acquired session via human resolution!")
                    cookie_dict = {c["name"]: c["value"] for c in cookies}
                    user_agent = await page.evaluate("navigator.userAgent")
                    await cookie_manager.save_session_data(url, cookie_dict, user_agent)
                    break

                await asyncio.sleep(2.0)

            if not page.is_closed():
                await page.close()
            await browser.close()

    except Exception as e:
        logger.error(f"Background noVNC monitoring task failed: {e}")


class NoVNCStrategy(BaseStrategy):
    async def extract(self, url: str) -> str:
        await self.get_html(url)
        return ""

    async def get_html(self, url: str) -> str:
        intervention_type = "login" if ChallengeDetector.is_login_required(url,
                                                                           "") or ChallengeDetector.is_login_redirect_url(
            url) else "captcha"
        final_vnc_url = await self._resolve_public_vnc_url()

        asyncio.create_task(_monitor_for_cookies(url, intervention_type))

        raise HumanInterventionRequiredException(vnc_url=final_vnc_url, intervention_type=intervention_type)

    async def _resolve_public_vnc_url(self) -> str:
        public_vnc = settings.PUBLIC_VNC_URL
        if "api/tunnels" not in public_vnc:
            return f"{public_vnc}/vnc.html?autoconnect=true"

        return await self._fetch_ngrok_url(public_vnc)

    async def _fetch_ngrok_url(self, api_url: str) -> str:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(api_url)
                response.raise_for_status()
                return self._extract_url_from_ngrok_response(response.json(), api_url)
        except Exception as e:
            logger.warning(f"Failed to dynamically resolve PUBLIC_VNC_URL: {e}")
            return f"{settings.SELENIUM_BROWSER_VNC_URL}/vnc.html?autoconnect=true"

    def _extract_url_from_ngrok_response(self, data: dict, fallback_url: str) -> str:
        tunnels = data.get("tunnels", [])
        public_vnc = tunnels[0].get("public_url", fallback_url) if tunnels else fallback_url
        return f"{public_vnc}/vnc.html?autoconnect=true"

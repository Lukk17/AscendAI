import asyncio
import logging
from typing import Any, cast

import httpx
from playwright.async_api import Geolocation, async_playwright

from src.api.exceptions import HumanInterventionRequiredException
from src.config.config import settings
from src.reader.cloudflare.challenge_detector import ChallengeDetector
from src.reader.cloudflare.cookie_manager import cookie_manager
from src.reader.strategies.base_strategy import BaseStrategy

logger = logging.getLogger(__name__)

# Chrome DevTools Protocol port. Exposed deliberately per ADR-003 accepted
# security posture; the operator runs NoVNC on a single-tenant host.
_CDP_REMOTE_DEBUGGING_PORT = 9222
_VNC_WINDOW_WIDTH_PX = 1920
_VNC_WINDOW_HEIGHT_PX = 1080

# Two minutes for the initial navigation to the challenge URL. Anything slower
# than that is almost certainly a stuck page rather than a slow CAPTCHA load.
_INITIAL_NAV_TIMEOUT_MS = 120_000

# Cookie-sync poll interval. Five seconds keeps Redis write rate sane while still
# catching the moment the human finishes the challenge.
_COOKIE_SYNC_POLL_SECONDS = 5.0

# Ngrok API call budget. Failure falls back to SELENIUM_BROWSER_VNC_URL.
_NGROK_API_TIMEOUT_SECONDS = 5.0

_active_monitor_tasks: set[asyncio.Task[None]] = set()


async def _monitor_for_cookies(url: str, intervention_type: str = "captcha") -> None:
    logger.info(f"Background task started to monitor session for {url} ({intervention_type})")
    browser = None

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=False,
                args=[
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                    f"--remote-debugging-port={_CDP_REMOTE_DEBUGGING_PORT}",
                    "--window-position=0,0",
                    f"--window-size={_VNC_WINDOW_WIDTH_PX},{_VNC_WINDOW_HEIGHT_PX}",
                ],
            )
            context = await browser.new_context(
                locale="en-US",
                timezone_id="America/New_York",
                geolocation=cast("Geolocation", {"latitude": 37.7749, "longitude": -122.4194}),
                permissions=["geolocation"],
            )

            page = await context.new_page()

            try:
                await page.goto(url, wait_until="commit", timeout=_INITIAL_NAV_TIMEOUT_MS)
            except Exception as e:
                logger.warning(f"NoVNC Strategy: Initial navigation failed: {e}")

            loop = asyncio.get_running_loop()
            start_time = loop.time()
            while loop.time() - start_time < settings.NOVNC_TIMEOUT_SECONDS:
                try:
                    cookies = await context.cookies()
                    # Playwright's Cookie TypedDict marks `name` and `value` as
                    # optional even though every real cookie has both. Skip the
                    # rare entries missing either rather than crashing on KeyError.
                    cookie_dict = {c["name"]: c["value"] for c in cookies if "name" in c and "value" in c}
                    user_agent = await page.evaluate("navigator.userAgent")

                    await cookie_manager.save_session_data(url, cookie_dict, user_agent)

                    # Early exit once the user has navigated away from the login/challenge page.
                    # Without this, we keep overwriting Redis every 5 s for the full timeout window
                    # even though the human finished the challenge in the first 30 s.
                    current_url = page.url or ""
                    if not ChallengeDetector.is_login_redirect_url(current_url) and current_url != url:
                        logger.info(
                            f"NoVNC Strategy: challenge appears resolved (now at {current_url}), "
                            f"stopping monitor early"
                        )
                        break
                except Exception as e:
                    logger.debug(f"NoVNC Strategy: Transient error syncing session cookies: {e}")

                await asyncio.sleep(_COOKIE_SYNC_POLL_SECONDS)
    except Exception:
        logger.exception("Background noVNC monitoring task failed")
    finally:
        if browser is not None:
            try:
                await browser.close()
            except Exception as e:
                logger.debug(f"NoVNC Strategy: browser close failed during cleanup: {e}")


class NoVNCStrategy(BaseStrategy):
    async def extract(self, url: str) -> str:
        # get_html always raises HumanInterventionRequiredException; we never
        # reach the post-call path. The explicit raise satisfies the type checker
        # without leaving a dead "return ''" that PyCharm flags as redundant.
        await self.get_html(url)
        raise AssertionError("unreachable: NoVNCStrategy.get_html always raises")  # pragma: no cover

    async def get_html(self, url: str) -> str:
        # is_login_required short-circuits on empty html, so only the URL-pattern check
        # can ever flip this branch. Keep the URL check; the is_login_required("") call
        # was dead logic that never contributed.
        intervention_type = "login" if ChallengeDetector.is_login_redirect_url(url) else "captcha"
        final_vnc_url = await self._resolve_public_vnc_url()

        # Hold a strong reference so the event loop's weak set doesn't GC the task mid-flight,
        # which silently kills the cookie sync and leaves users stuck re-logging.
        task = asyncio.create_task(_monitor_for_cookies(url, intervention_type))
        _active_monitor_tasks.add(task)
        task.add_done_callback(_active_monitor_tasks.discard)

        raise HumanInterventionRequiredException(vnc_url=final_vnc_url, intervention_type=intervention_type)

    async def _resolve_public_vnc_url(self) -> str:
        public_vnc = settings.PUBLIC_VNC_URL
        if "api/tunnels" not in public_vnc:
            return f"{public_vnc}/vnc.html?autoconnect=true"

        return await self._fetch_ngrok_url(public_vnc)

    async def _fetch_ngrok_url(self, api_url: str) -> str:
        try:
            async with httpx.AsyncClient(timeout=_NGROK_API_TIMEOUT_SECONDS) as client:
                response = await client.get(api_url)
                response.raise_for_status()
                return self._extract_url_from_ngrok_response(response.json(), api_url)
        except Exception as e:
            logger.warning(f"Failed to dynamically resolve PUBLIC_VNC_URL: {e}")
            return f"{settings.SELENIUM_BROWSER_VNC_URL}/vnc.html?autoconnect=true"

    @staticmethod
    def _extract_url_from_ngrok_response(data: dict[str, Any], fallback_url: str) -> str:
        tunnels = data.get("tunnels", [])
        public_vnc = tunnels[0].get("public_url", fallback_url) if tunnels else fallback_url

        return f"{public_vnc}/vnc.html?autoconnect=true"

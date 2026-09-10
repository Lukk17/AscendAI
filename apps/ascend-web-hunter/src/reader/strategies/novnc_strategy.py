import asyncio
import logging
import time
from typing import Any, cast

import httpx
from playwright.async_api import async_playwright

from src.api.exceptions import HumanInterventionRequiredException, NoVNCFlowBusyException
from src.config.config import settings
from src.observability.domain_label import domain_label
from src.observability.metrics import STRATEGY_ATTEMPTS_TOTAL
from src.reader.cloudflare.challenge_detector import ChallengeDetector
from src.reader.cloudflare.cookie_manager import PRODUCED_BY_NOVNC, cookie_manager
from src.reader.fingerprint import get_default_fingerprint
from src.reader.strategies.base_strategy import BaseStrategy

logger = logging.getLogger(__name__)

_CDP_REMOTE_DEBUGGING_PORT = 9222
_VNC_WINDOW_WIDTH_PX = 1920
_VNC_WINDOW_HEIGHT_PX = 1080
_INITIAL_NAV_TIMEOUT_MS = 120_000
_NGROK_API_TIMEOUT_SECONDS = 5.0

# Grace period added on top of NOVNC_TIMEOUT_SECONDS before a held lock is
# treated as stale and reclaimed. Covers the gap between the monitor's own
# timeout firing and its `finally` block actually running (browser.close()
# and the outer async-with teardown), not a second full timeout window.
_NOVNC_LOCK_LEASE_GRACE_SECONDS = 30.0

_active_monitor_tasks: set[asyncio.Task[None]] = set()

_MONITOR_STRATEGY_LABEL = "6-novnc-monitor"


class _NoVNCFlowLock:
    """Serializes access to the single shared NoVNC browser, VNC display and
    CDP port (see docker-entrypoint.sh: one Xvfb display, one dbus session
    bus). Both the manual `session/establish` endpoint and WebReader's
    automatic escalation to this tier go through the same `get_html()`, so
    the lock is acquired there regardless of caller.

    The lock is global, not per (url, profile): only one physical browser
    window exists for a human to interact with, so a second flow for a
    *different* site genuinely cannot run concurrently, and a second flow
    for the *same* site is not safely joinable either -- the human already
    driving the first window has no way to know a second, unrelated caller
    is now also expecting that window's outcome.

    A lease timestamp bounds how long the lock can be held. If the flow that
    acquired it dies without releasing (a wedged browser subprocess, a hang
    with no exception), the lock self-heals once the lease expires rather
    than making the endpoint permanently unavailable.
    """

    def __init__(self) -> None:
        self._holder_url: str | None = None
        self._holder_profile: str | None = None
        self._acquired_at: float = 0.0

    def _lease_expired(self, now: float) -> bool:
        lease_seconds = settings.NOVNC_TIMEOUT_SECONDS + _NOVNC_LOCK_LEASE_GRACE_SECONDS

        return now - self._acquired_at >= lease_seconds

    def try_acquire(self, url: str, profile: str) -> None:
        """Raise NoVNCFlowBusyException if another flow currently holds the lock."""
        now = time.monotonic()
        if self._holder_url is not None and self._holder_profile is not None and not self._lease_expired(now):
            raise NoVNCFlowBusyException(self._holder_url, self._holder_profile)

        if self._holder_url is not None:
            logger.warning(
                "NoVNC Strategy: lock held by %s (profile=%s) exceeded its lease, reclaiming",
                self._holder_url,
                self._holder_profile,
            )

        self._holder_url = url
        self._holder_profile = profile
        self._acquired_at = now

    def release(self, url: str, profile: str) -> None:
        if self._holder_url == url and self._holder_profile == profile:
            self._holder_url = None
            self._holder_profile = None
            self._acquired_at = 0.0


_novnc_flow_lock = _NoVNCFlowLock()


def _has_clearance_cookie(storage_state: dict[str, Any]) -> bool:
    """True once a Cloudflare clearance cookie is present in the captured state."""
    return any(c.get("name") == "cf_clearance" for c in storage_state.get("cookies", []))


def _timeout_outcome(intervention_type: str, last_page_blocked: bool) -> str:
    """Label a monitor timeout as 'rejected' when the last observed page was
    still an actively known block page, or 'timeout' when inconclusive."""
    return "rejected" if intervention_type == "captcha" and last_page_blocked else "timeout"


async def _poll_captcha(
    page: Any,
    url: str,
    storage_state: dict[str, Any],
    profile: str | None,
) -> tuple[bool, bool]:
    """Run one captcha-branch poll. Returns (resolved, page_blocked).

    `is_content_accepted` is the single shared decision point for whether a
    page counts as real, unblocked content (see ChallengeDetector). A session
    is captured as soon as that is true, whether or not this monitor run ever
    observed a block first: `session/establish` is the proactive counterpart
    to passive capture and must persist a record for an ordinary,
    never-challenged page too, not only for a solved captcha. A Cloudflare
    clearance cookie is independent evidence a real challenge was solved.
    """
    page_content = await page.content()
    page_blocked = ChallengeDetector.is_blocked(200, page_content)
    cleared = ChallengeDetector.is_content_accepted(200, page_content)
    if cleared or _has_clearance_cookie(storage_state):
        user_agent = await page.evaluate("navigator.userAgent")
        await cookie_manager.save_storage_state(url, storage_state, user_agent, profile, PRODUCED_BY_NOVNC)
        logger.info("NoVNC Strategy: captcha solved for %s, captured session and stopping", url)

        return True, page_blocked

    return False, page_blocked


async def _poll_login(page: Any, url: str, storage_state: dict[str, Any], profile: str | None) -> bool:
    """Run one login-branch poll. Returns whether the login has resolved."""
    current_url = page.url or ""
    user_agent = await page.evaluate("navigator.userAgent")
    await cookie_manager.save_storage_state(url, storage_state, user_agent, profile, PRODUCED_BY_NOVNC)
    if not ChallengeDetector.is_login_redirect_url(current_url) and current_url != url:
        logger.info("NoVNC Strategy: login resolved (now at %s), stopping monitor", current_url)

        return True

    return False


async def _poll_once(
    page: Any,
    context: Any,
    url: str,
    intervention_type: str,
    profile: str | None,
) -> tuple[bool, bool]:
    """Run a single monitor poll. Returns (resolved, page_blocked); page_blocked
    is only meaningful for the captcha branch and defaults to True on a
    transient error so an all-errors timeout is labeled 'rejected'-safe."""
    try:
        storage_state = cast("dict[str, Any]", await context.storage_state())
        if intervention_type == "captcha":
            return await _poll_captcha(page, url, storage_state, profile)

        return await _poll_login(page, url, storage_state, profile), True
    except Exception as e:
        logger.debug("NoVNC Strategy: Transient error syncing session cookies: %s", e)

        return False, True


async def _monitor_for_cookies(
    url: str,
    intervention_type: str = "captcha",
    profile: str | None = None,
) -> None:
    logger.info("Background task started to monitor session for %s (%s)", url, intervention_type)
    browser = None
    fp = get_default_fingerprint()
    dlabel = domain_label(url)
    outcome = "timeout"
    effective_profile = profile or settings.SESSION_DEFAULT_PROFILE

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
                locale=fp.locale,
                timezone_id=fp.timezone_id,
                geolocation=fp.geolocation,
                permissions=["geolocation"],
            )

            page = await context.new_page()

            try:
                await page.goto(url, wait_until="commit", timeout=_INITIAL_NAV_TIMEOUT_MS)
            except Exception as e:
                logger.warning("NoVNC Strategy: Initial navigation failed: %s", e)

            loop = asyncio.get_running_loop()
            start_time = loop.time()
            last_page_blocked = True
            while loop.time() - start_time < settings.NOVNC_TIMEOUT_SECONDS:
                resolved, last_page_blocked = await _poll_once(page, context, url, intervention_type, profile)
                if resolved:
                    outcome = "resolved"

                    break

                await asyncio.sleep(settings.NOVNC_COOKIE_SYNC_POLL_SECONDS)
            else:
                # The while condition became false without a break: the human never
                # completed the flow within NOVNC_TIMEOUT_SECONDS.
                outcome = _timeout_outcome(intervention_type, last_page_blocked)
                logger.warning(
                    "NoVNC Strategy: %s intervention for %s timed out after %ss (outcome=%s); "
                    "no session was written",
                    intervention_type,
                    url,
                    settings.NOVNC_TIMEOUT_SECONDS,
                    outcome,
                )
    except Exception:
        logger.exception("Background noVNC monitoring task failed")
        outcome = "timeout"
    finally:
        if browser is not None:
            try:
                await browser.close()
            except Exception as e:
                logger.debug("NoVNC Strategy: browser close failed during cleanup: %s", e)
        _novnc_flow_lock.release(url, effective_profile)
        STRATEGY_ATTEMPTS_TOTAL.labels(strategy=_MONITOR_STRATEGY_LABEL, outcome=outcome, domain=dlabel).inc()


class NoVNCStrategy(BaseStrategy):
    def __init__(self, profile: str | None = None) -> None:
        self.profile = profile

    async def extract(self, url: str) -> str:
        return await self.get_html(url)

    async def get_html(self, url: str) -> str:
        intervention_type = "login" if ChallengeDetector.is_login_redirect_url(url) else "captcha"
        effective_profile = self.profile or settings.SESSION_DEFAULT_PROFILE

        _novnc_flow_lock.try_acquire(url, effective_profile)
        try:
            final_vnc_url = await self._resolve_public_vnc_url()
        except Exception:
            _novnc_flow_lock.release(url, effective_profile)
            raise

        task = asyncio.create_task(_monitor_for_cookies(url, intervention_type, self.profile))
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
            logger.warning("Failed to dynamically resolve PUBLIC_VNC_URL: %s", e)

            return f"{settings.SELENIUM_BROWSER_VNC_URL}/vnc.html?autoconnect=true"

    @staticmethod
    def _extract_url_from_ngrok_response(data: dict[str, Any], fallback_url: str) -> str:
        tunnels = data.get("tunnels", [])
        public_vnc = tunnels[0].get("public_url", fallback_url) if tunnels else fallback_url

        return f"{public_vnc}/vnc.html?autoconnect=true"

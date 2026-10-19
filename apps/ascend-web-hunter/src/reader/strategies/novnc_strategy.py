import asyncio
import logging
import socket
from typing import Any, cast

import httpx
from playwright.async_api import async_playwright

from src.api.exceptions import HumanInterventionRequiredException
from src.config.config import settings
from src.observability.domain_label import domain_label
from src.observability.metrics import STRATEGY_ATTEMPTS_TOTAL
from src.reader.cloudflare.challenge_detector import ChallengeDetector
from src.reader.cloudflare.challenge_signals import assess, log_verdict, record_verdict
from src.reader.cloudflare.cookie_manager import PRODUCED_BY_NOVNC, cookie_manager
from src.reader.fingerprint import get_default_fingerprint
from src.reader.novnc.flow_registry import NoVNCFlow, flow_key_for, novnc_flow_registry
from src.reader.strategies.base_strategy import BaseStrategy

logger = logging.getLogger(__name__)

_INITIAL_NAV_TIMEOUT_MS = 120_000
_NGROK_API_TIMEOUT_SECONDS = 5.0

_MONITOR_STRATEGY_LABEL = "6-novnc-monitor"


def _has_clearance_cookie(storage_state: dict[str, Any]) -> bool:
    """True once a Cloudflare clearance cookie is present in the captured state."""
    return any(c.get("name") == "cf_clearance" for c in storage_state.get("cookies", []))


def _timeout_outcome(intervention_type: str, last_page_blocked: bool) -> str:
    """Label a monitor timeout as 'rejected' when the last observed page was
    still an actively known block page, or 'timeout' when inconclusive."""
    return "rejected" if intervention_type == "captcha" and last_page_blocked else "timeout"


def _window_to_dict(flow: NoVNCFlow) -> dict[str, int]:
    return {
        "slot": flow.window.slot,
        "x": flow.window.x,
        "y": flow.window.y,
        "width": flow.window.width,
        "height": flow.window.height,
    }


def _join_exc(flow: NoVNCFlow) -> HumanInterventionRequiredException:
    return HumanInterventionRequiredException(
        vnc_url=flow.vnc_url,
        intervention_type=flow.intervention_type,
        flow_id=flow.flow_id,
        joined=True,
        window=_window_to_dict(flow),
    )


async def _poll_captcha(
    page: Any,
    url: str,
    storage_state: dict[str, Any],
    profile: str | None,
    flow: NoVNCFlow | None = None,
) -> tuple[bool, bool]:
    """Run one captcha-branch poll. Returns (resolved, page_blocked).

    One assess call over the rendered content with the storage state's cookie
    names: page_blocked and cleared are two reads of the same verdict.
    `is_content_accepted` is the single shared decision point for whether a
    page counts as real, unblocked content (see ChallengeDetector). A session
    is captured as soon as that is true, whether or not this monitor run ever
    observed a block first: `session/establish` is the proactive counterpart
    to passive capture and must persist a record for an ordinary,
    never-challenged page too, not only for a solved captcha. A Cloudflare
    clearance cookie is independent evidence a real challenge was solved.
    """
    page_content = await page.content()
    cookie_names = [str(cookie.get("name", "")) for cookie in storage_state.get("cookies", [])]
    verdict = assess(200, page_content, None, cookie_names)
    record_verdict(verdict, "novnc-monitor")
    log_verdict(verdict, "novnc-monitor", url)
    page_blocked = verdict.wall
    cleared = verdict.accepted
    if cleared or _has_clearance_cookie(storage_state):
        user_agent = await page.evaluate("navigator.userAgent")
        await cookie_manager.save_storage_state(url, storage_state, user_agent, profile, PRODUCED_BY_NOVNC)
        if flow is not None:
            logger.info(
                "NoVNC Strategy: captcha solved for %s flow_id=%s slot=%s, captured session and stopping",
                url,
                flow.flow_id,
                flow.window.slot,
            )
        else:
            logger.info("NoVNC Strategy: captcha solved for %s, captured session and stopping", url)

        return True, page_blocked

    return False, page_blocked


async def _poll_login(
    page: Any, url: str, storage_state: dict[str, Any], profile: str | None, flow: NoVNCFlow | None = None
) -> bool:
    """Run one login-branch poll. Returns whether the login has resolved."""
    current_url = page.url or ""
    user_agent = await page.evaluate("navigator.userAgent")
    await cookie_manager.save_storage_state(url, storage_state, user_agent, profile, PRODUCED_BY_NOVNC)
    if not ChallengeDetector.is_login_redirect_url(current_url) and current_url != url:
        if flow is not None:
            logger.info(
                "NoVNC Strategy: login resolved (now at %s) flow_id=%s slot=%s, stopping monitor",
                current_url,
                flow.flow_id,
                flow.window.slot,
            )
        else:
            logger.info("NoVNC Strategy: login resolved (now at %s), stopping monitor", current_url)

        return True

    return False


async def _poll_once(
    page: Any,
    context: Any,
    url: str,
    intervention_type: str,
    profile: str | None,
    flow: NoVNCFlow | None = None,
) -> tuple[bool, bool]:
    """Run a single monitor poll. Returns (resolved, page_blocked); page_blocked
    is only meaningful for the captcha branch and defaults to True on a
    transient error so an all-errors timeout is labeled 'rejected'-safe."""
    try:
        storage_state = cast("dict[str, Any]", await context.storage_state())
        if intervention_type == "captcha":
            return await _poll_captcha(page, url, storage_state, profile, flow)

        return await _poll_login(page, url, storage_state, profile, flow), True
    except Exception as e:
        logger.debug("NoVNC Strategy: Transient error syncing session cookies: %s", e)

        return False, True


async def _monitor_for_cookies(flow: NoVNCFlow) -> None:
    logger.info(
        "Background task started to monitor session for %s (%s) flow_id=%s slot=%s",
        flow.url,
        flow.intervention_type,
        flow.flow_id,
        flow.window.slot,
    )
    browser = None
    fp = get_default_fingerprint()
    dlabel = domain_label(flow.url)
    outcome = "timeout"

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=False,
                args=[
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                    "--remote-debugging-port=0",
                    "--remote-debugging-address=127.0.0.1",
                    f"--window-position={flow.window.x},{flow.window.y}",
                    f"--window-size={flow.window.width},{flow.window.height}",
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
                await page.goto(flow.url, wait_until="commit", timeout=_INITIAL_NAV_TIMEOUT_MS)
            except Exception as e:
                logger.warning(
                    "NoVNC Strategy: Initial navigation failed for flow_id=%s slot=%s: %s",
                    flow.flow_id,
                    flow.window.slot,
                    e,
                )

            loop = asyncio.get_running_loop()
            start_time = loop.time()
            last_page_blocked = True
            while loop.time() - start_time < settings.NOVNC_TIMEOUT_SECONDS:
                resolved, last_page_blocked = await _poll_once(
                    page, context, flow.url, flow.intervention_type, flow.profile, flow
                )
                if resolved:
                    outcome = "resolved"

                    break

                await asyncio.sleep(settings.NOVNC_COOKIE_SYNC_POLL_SECONDS)
            else:
                # The while condition became false without a break: the human never
                # completed the flow within NOVNC_TIMEOUT_SECONDS.
                outcome = _timeout_outcome(flow.intervention_type, last_page_blocked)
                logger.warning(
                    "NoVNC Strategy: %s intervention for %s timed out after %ss "
                    "(outcome=%s flow_id=%s slot=%s); no session was written",
                    flow.intervention_type,
                    flow.url,
                    settings.NOVNC_TIMEOUT_SECONDS,
                    outcome,
                    flow.flow_id,
                    flow.window.slot,
                )
    except asyncio.CancelledError:
        outcome = "cancelled"
        raise
    except Exception:
        logger.exception(
            "Background noVNC monitoring task failed for flow_id=%s slot=%s",
            flow.flow_id,
            flow.window.slot,
        )
        outcome = "timeout"
    finally:
        if browser is not None:
            try:
                await browser.close()
            except Exception as e:
                logger.debug(
                    "NoVNC Strategy: browser close failed for flow_id=%s slot=%s: %s",
                    flow.flow_id,
                    flow.window.slot,
                    e,
                )
        await novnc_flow_registry.release(flow.flow_id)
        STRATEGY_ATTEMPTS_TOTAL.labels(strategy=_MONITOR_STRATEGY_LABEL, outcome=outcome, domain=dlabel).inc()


class NoVNCStrategy(BaseStrategy):
    def __init__(self, profile: str | None = None) -> None:
        self.profile = profile

    async def extract(self, url: str) -> str:
        return await self.get_html(url)

    async def get_html(self, url: str) -> str:
        intervention_type = "login" if ChallengeDetector.is_login_redirect_url(url) else "captcha"
        effective_profile = self.profile or settings.SESSION_DEFAULT_PROFILE
        key = flow_key_for(url, effective_profile)

        existing = await novnc_flow_registry.find(key)
        if existing is not None:
            logger.info(
                "NoVNC Strategy: joining live flow flow_id=%s slot=%s key=%s",
                existing.flow_id,
                existing.window.slot,
                key,
            )
            raise _join_exc(existing)

        flow = await novnc_flow_registry.reserve(
            key=key, url=url, profile=effective_profile, intervention_type=intervention_type
        )
        if not novnc_flow_registry.is_local(flow.flow_id):
            logger.info(
                "NoVNC Strategy: joining live flow flow_id=%s slot=%s key=%s",
                flow.flow_id,
                flow.window.slot,
                key,
            )
            raise _join_exc(flow)

        logger.info(
            "NoVNC Strategy: reserved flow flow_id=%s slot=%s key=%s",
            flow.flow_id,
            flow.window.slot,
            key,
        )
        try:
            final_vnc_url = await self._resolve_public_vnc_url()
        except Exception as exc:
            logger.warning(
                "NoVNC Strategy: VNC resolution failed for flow_id=%s slot=%s: %s",
                flow.flow_id,
                flow.window.slot,
                exc,
            )
            await novnc_flow_registry.release(flow.flow_id)
            raise

        await novnc_flow_registry.set_vnc_url(flow.flow_id, final_vnc_url)
        task = asyncio.create_task(_monitor_for_cookies(flow))
        novnc_flow_registry.attach_task(flow.flow_id, task)

        raise HumanInterventionRequiredException(
            vnc_url=final_vnc_url,
            intervention_type=intervention_type,
            flow_id=flow.flow_id,
            joined=False,
            window=_window_to_dict(flow),
        )

    async def _resolve_public_vnc_url(self) -> str:
        base_url = settings.NOVNC_PUBLIC_URL
        if base_url:
            hostname = socket.gethostname()

            return f"{base_url}/novnc/{hostname}/vnc.html?autoconnect=true&path=novnc/{hostname}/websockify"
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

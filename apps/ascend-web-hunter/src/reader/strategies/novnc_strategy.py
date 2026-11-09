import asyncio
import logging
import socket
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from importlib.metadata import version as package_version
from typing import Any
from urllib.parse import urlsplit

import httpx
from patchright.async_api import async_playwright

from src.api.exceptions import HumanInterventionRequiredException
from src.config.config import settings
from src.observability.domain_label import domain_label
from src.observability.metrics import STRATEGY_ATTEMPTS_TOTAL
from src.observability.safe_address import address_without_query
from src.proxy.proxy_provider import proxy_provider
from src.reader.browser_guard import (
    BrowserFamily,
    browser_tunnel,
    chromium_guard_args,
    guarded_goto,
    install_browser_guard,
    looks_like_browser_gone,
)
from src.reader.cloudflare.challenge_detector import ChallengeDetector
from src.reader.cloudflare.challenge_signals import (
    ChallengeVerdict,
    assess,
    log_verdict,
    record_window_verdict,
)
from src.reader.cloudflare.cookie_manager import (
    PRODUCED_BY_NOVNC,
    CookieManager,
    SiteEntry,
    belongs_to_site,
    cookie_manager,
    is_login_state_name,
    site_local_storage_entries,
)
from src.reader.fingerprint import get_default_fingerprint
from src.reader.novnc.flow_registry import (
    CANCELLED_OUTCOME,
    NoVNCFlow,
    flow_key_for,
    novnc_flow_registry,
)
from src.reader.strategies.base_strategy import BaseStrategy
from src.reader.strategies.browser_read import bounded_page_content
from src.reader.strategies.main_frame_response import MainFrameResponses
from src.validator.url_validator import url_validator as shared_url_validator

logger = logging.getLogger(__name__)

_SERVICE_VERSION = package_version("ascend-web-hunter")

_INITIAL_NAV_TIMEOUT_MS = 120_000
_NGROK_API_TIMEOUT_SECONDS = 5.0

_MONITOR_STRATEGY_LABEL = "6-novnc-monitor"

_VERDICT_TIER = "novnc-monitor"

_RESOLVED_OUTCOME = "resolved"

_ALREADY_AUTHENTICATED_OUTCOME = "already_authenticated"

_VISIBLE_CREDENTIAL_INPUT = "input[type=password]:visible"

_WEB_SCHEMES = frozenset({"http", "https"})

_READ_FRAME_LOCAL_STORAGE = """() => {
  try {
    const storage = window.localStorage;
    const items = [];
    for (let index = 0; index < storage.length; index += 1) {
      const name = storage.key(index);
      items.push({name: name, value: storage.getItem(name)});
    }
    return {origin: location.origin, localStorage: items};
  } catch (error) {
    if (error.name === "SecurityError") {
      return null;
    }
    throw error;
  }
}"""


def _timeout_outcome(intervention_type: str, last_page_blocked: bool) -> str:
    """Label a monitor timeout as 'rejected' when the last observed page was
    still an actively known block page, or 'timeout' when inconclusive."""
    return "rejected" if intervention_type == "captcha" and last_page_blocked else "timeout"


_BROWSER_GONE_OUTCOME = "browser_closed"
_UNSAFE_URI_OUTCOME = "unsafe_uri"


class _BrowserGoneError(Exception):
    """The flow's Chromium died mid-poll, so the slot must be released."""


def _is_browser_gone(browser: Any, page: Any) -> bool:
    """True when the flow's Chromium is observably dead.

    Either the connection is down or its only page is closed. Both probes
    read local flags, so an absent probe is skipped, never treated as death.
    """
    is_connected = getattr(browser, "is_connected", None)
    if callable(is_connected) and is_connected() is False:
        return True
    is_closed = getattr(page, "is_closed", None)

    return bool(callable(is_closed) and is_closed() is True)


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


@dataclass
class _FlowProgress:
    """What a flow has seen so far.

    `site` is the registrable domain of the flow's target. `starts_logged_in`
    says the window opened on a stored login that is still valid.
    `login_wall_entries` holds the site's own login state at the last login
    wall seen on the site, or None while no such wall has been seen.
    `login_addresses` holds the origin and path of every login address the
    window saw as a login wall. `last_verdict` is the verdict of the latest
    page check, counted once when the window ends. `site_storage` holds the
    localStorage of the site's own origins as last read, by origin, and
    `last_poll_address` the main-frame address of the poll that last read them whole.
    `refused_navigations` holds the refused navigations of the window's main frame.
    """

    site: str
    starts_logged_in: bool = False
    login_wall_seen: bool = False
    login_wall_entries: frozenset[SiteEntry] | None = None
    login_addresses: set[str] = field(default_factory=set)
    last_verdict: ChallengeVerdict | None = None
    site_storage: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    last_poll_address: str | None = None
    refused_navigations: list[str] = field(default_factory=list)


def _site_cookie_entries(storage_state: dict[str, Any], site: str) -> set[SiteEntry]:
    entries: set[SiteEntry] = set()
    for cookie in storage_state.get("cookies", []):
        name = str(cookie.get("name", ""))
        domain = str(cookie.get("domain", "")).lstrip(".").lower()
        if is_login_state_name(name) and belongs_to_site(domain, site):
            entries.add(("cookie", f"{domain}{cookie.get('path', '/')}", name, str(cookie.get("value", ""))))

    return entries


def _site_login_entries(storage_state: dict[str, Any], site: str) -> frozenset[SiteEntry]:
    """The cookies and localStorage entries the site set on its own registrable
    domain, minus WAF clearance and known analytics or consent entries."""
    return frozenset(
        _site_cookie_entries(storage_state, site) | site_local_storage_entries(storage_state, site)
    )


def _on_site_storage(storage_state: dict[str, Any], site: str) -> dict[str, list[dict[str, Any]]]:
    return {
        str(origin.get("origin", "")): list(origin.get("localStorage", []))
        for origin in storage_state.get("origins", [])
        if belongs_to_site(str(origin.get("origin", "")), site)
    }


async def _read_frame_storage(frame: Any, flow: NoVNCFlow) -> dict[str, Any] | None:
    try:
        stored: dict[str, Any] | None = await frame.evaluate(_READ_FRAME_LOCAL_STORAGE)
    except Exception as e:
        logger.debug(
            "NoVNC Strategy: a frame could not be read for flow_id=%s slot=%s: %s",
            flow.flow_id,
            flow.window.slot,
            type(e).__name__,
        )

        return None

    return stored


async def _live_site_storage(context: Any, flow: NoVNCFlow, site: str) -> list[dict[str, Any]]:
    """The localStorage of every live frame on *site*, in every page of the window, popups included."""
    site_frames = [
        frame for page in context.pages for frame in page.frames if belongs_to_site(frame.url, site)
    ]
    read = [await _read_frame_storage(frame, flow) for frame in site_frames]

    return [stored for stored in read if stored is not None]


async def _captcha_poll_state(context: Any) -> dict[str, Any]:
    return {"cookies": await context.cookies(), "origins": []}


async def _login_poll_state(
    page: Any, context: Any, flow: NoVNCFlow, progress: _FlowProgress
) -> dict[str, Any]:
    """Build the state one login poll judges, without the helper tabs of a whole-state read.

    The whole state is read once per main-frame address, so a token written on
    one origin just before a redirect to another is still seen. Live frames are
    laid over it on every poll.
    """
    cookies = await context.cookies()
    address = page.url or ""
    if address != progress.last_poll_address:
        progress.site_storage = _on_site_storage(await context.storage_state(), progress.site)
        progress.last_poll_address = address
    for stored in await _live_site_storage(context, flow, progress.site):
        progress.site_storage[str(stored["origin"])] = stored["localStorage"]

    return {
        "cookies": cookies,
        "origins": [
            {"origin": origin, "localStorage": items} for origin, items in progress.site_storage.items()
        ],
    }


def _cookie_names(storage_state: dict[str, Any]) -> list[str]:
    return [str(cookie.get("name", "")) for cookie in storage_state.get("cookies", [])]


async def _assess_page(
    page_content: str,
    responses: MainFrameResponses,
    storage_state: dict[str, Any],
    flow: NoVNCFlow,
    progress: _FlowProgress,
) -> ChallengeVerdict:
    status, headers = await responses.status_and_headers()
    verdict = await asyncio.to_thread(
        assess, status, page_content, headers, _cookie_names(storage_state), record_metrics=False
    )
    progress.last_verdict = verdict
    log_verdict(verdict, f"{_VERDICT_TIER} flow_id={flow.flow_id} slot={flow.window.slot}", flow.url)

    return verdict


def _record_final_verdict(progress: _FlowProgress | None) -> None:
    if progress is not None and progress.last_verdict is not None:
        record_window_verdict(progress.last_verdict, _VERDICT_TIER)


async def _poll_captcha(
    page: Any,
    responses: MainFrameResponses,
    context: Any,
    storage_state: dict[str, Any],
    flow: NoVNCFlow,
    progress: _FlowProgress,
) -> tuple[bool, bool]:
    """Run one captcha-branch poll. Returns (resolved, page_blocked).

    One assess call over the rendered content with the latest main-frame
    response's status and headers and the poll state's cookie names:
    page_blocked and cleared are two reads of the same verdict. The save reads
    the whole storage state and never drops a valid stored login (see
    CookieManager).
    """
    verdict = await _assess_page(await bounded_page_content(page), responses, storage_state, flow, progress)
    if not verdict.accepted:
        return False, verdict.wall

    user_agent = await page.evaluate("navigator.userAgent")
    full_state = await context.storage_state()
    await cookie_manager.save_storage_state(flow.url, full_state, user_agent, flow.profile, PRODUCED_BY_NOVNC)
    logger.info(
        "NoVNC Strategy: captcha solved for %s flow_id=%s slot=%s, captured session and stopping",
        address_without_query(flow.url),
        flow.flow_id,
        flow.window.slot,
    )

    return True, verdict.wall


def _is_login_address(flow_url: str, current_url: str, page_content: str) -> bool:
    return ChallengeDetector.is_login_redirect_url(current_url) or ChallengeDetector.is_login_landing(
        flow_url, current_url, page_content
    )


async def _has_password_input(page: Any) -> bool:
    """True when the page shows a visible password input, in its markup or inside an open shadow root."""
    return bool(await page.locator(_VISIBLE_CREDENTIAL_INPUT).count() > 0)


def _is_login_page(
    page_content: str, verdict: ChallengeVerdict, *, counts_as_login_address: bool, has_password_input: bool
) -> bool:
    if counts_as_login_address or has_password_input:
        return True
    if ChallengeDetector.is_login_required(page_content):
        return True

    return verdict.wall


def _already_authenticated(verdict: ChallengeVerdict, flow: NoVNCFlow, progress: _FlowProgress) -> str | None:
    if not progress.starts_logged_in or not verdict.accepted:
        return None
    logger.info(
        "NoVNC Strategy: %s is already logged in (profile=%s) flow_id=%s slot=%s, "
        "keeping the stored session and releasing the window",
        address_without_query(flow.url),
        flow.profile,
        flow.flow_id,
        flow.window.slot,
    )

    return _ALREADY_AUTHENTICATED_OUTCOME


async def _poll_login(
    page: Any,
    responses: MainFrameResponses,
    context: Any,
    storage_state: dict[str, Any],
    flow: NoVNCFlow,
    progress: _FlowProgress,
) -> str | None:
    """Run one login-branch poll. Returns the outcome once the flow is settled, else None.

    A login has resolved once a login wall was seen on the target's site, the
    window is on a page of that site that is not a login wall, and the site's
    own login state (see `_site_login_entries`) gained or changed an entry since
    that wall. Only then is the whole storage state read and saved, replacing any stored login. After
    the first wall a login address still counts as a wall only when its origin
    and path are one the window already saw as a wall. A window opened on a
    valid stored login whose first rendered page of the site is content, not a
    login wall, settles as already authenticated.
    """
    current_url = page.url or ""
    page_content = await bounded_page_content(page)
    verdict = await _assess_page(page_content, responses, storage_state, flow, progress)
    on_site = belongs_to_site(current_url, progress.site)
    entries = _site_login_entries(storage_state, progress.site)
    address = address_without_query(current_url)
    at_login_address = _is_login_address(flow.url, current_url, page_content)
    counts_as_login_address = at_login_address and (
        not progress.login_wall_seen or address in progress.login_addresses
    )
    has_password_input = await _has_password_input(page)
    if _is_login_page(
        page_content,
        verdict,
        counts_as_login_address=counts_as_login_address,
        has_password_input=has_password_input,
    ):
        progress.login_wall_seen = True
        if at_login_address:
            progress.login_addresses.add(address)
        if on_site:
            progress.login_wall_entries = entries

        return None
    if not on_site:
        return None
    if not progress.login_wall_seen:
        return _already_authenticated(verdict, flow, progress)
    if progress.login_wall_entries is None or entries <= progress.login_wall_entries:
        return None

    user_agent = await page.evaluate("navigator.userAgent")
    full_state = await context.storage_state()
    await cookie_manager.save_storage_state(
        flow.url, full_state, user_agent, flow.profile, PRODUCED_BY_NOVNC, replaces_login=True
    )
    logger.info(
        "NoVNC Strategy: login resolved (now at %s) flow_id=%s slot=%s, captured session and stopping",
        address,
        flow.flow_id,
        flow.window.slot,
    )

    return _RESOLVED_OUTCOME


def _page_has_loaded(page: Any) -> bool:
    """True once the window shows a web document, not the blank start page or the browser's error page."""
    return urlsplit(page.url or "").scheme in _WEB_SCHEMES


async def _poll_once(
    page: Any, responses: MainFrameResponses, context: Any, flow: NoVNCFlow, progress: _FlowProgress
) -> tuple[str | None, bool]:
    """Run a single monitor poll. Returns (outcome, page_blocked): outcome is
    None while the flow is unsettled, page_blocked is only meaningful for the
    captcha branch and defaults to True on a transient error so an all-errors
    timeout is labeled 'rejected'-safe. A window that shows no web document is
    not judged and saves nothing, and page_blocked is False because nothing
    was observed, so the human can still reload it and a timeout is 'timeout'."""
    if not _page_has_loaded(page):
        return None, False
    try:
        if flow.intervention_type == "captcha":
            captcha_state = await _captcha_poll_state(context)
            resolved, page_blocked = await _poll_captcha(
                page, responses, context, captcha_state, flow, progress
            )

            return (_RESOLVED_OUTCOME if resolved else None), page_blocked

        login_state = await _login_poll_state(page, context, flow, progress)

        return await _poll_login(page, responses, context, login_state, flow, progress), True
    except Exception as e:
        if looks_like_browser_gone(e):
            raise _BrowserGoneError("flow browser is gone") from e
        logger.debug(
            "NoVNC Strategy: Transient error syncing session cookies for flow_id=%s slot=%s: %s",
            flow.flow_id,
            flow.window.slot,
            e,
        )

        return None, True


def _navigation_timeout_ms(deadline: float) -> int:
    remaining_ms = int((deadline - time.monotonic()) * 1000)

    return max(1, min(_INITIAL_NAV_TIMEOUT_MS, remaining_ms))


def _log_browser_closed(flow: NoVNCFlow, outcome: str) -> None:
    if outcome == _BROWSER_GONE_OUTCOME:
        logger.warning(
            "NoVNC Strategy: browser closed for %s flow_id=%s slot=%s; releasing slot",
            address_without_query(flow.url),
            flow.flow_id,
            flow.window.slot,
        )


async def _close_browser(browser: Any, flow: NoVNCFlow) -> None:
    if browser is None:
        return
    try:
        await browser.close()
    except Exception as e:
        logger.debug(
            "NoVNC Strategy: browser close failed for flow_id=%s slot=%s: %s",
            flow.flow_id,
            flow.window.slot,
            e,
        )


async def _poll_until_settled(
    browser: Any,
    page: Any,
    responses: MainFrameResponses,
    context: Any,
    flow: NoVNCFlow,
    progress: _FlowProgress,
    deadline: float,
) -> str:
    """Poll the flow's page until it settles, its browser goes, or the
    deadline passes. Returns the outcome label."""
    last_page_blocked = True
    while time.monotonic() < deadline:
        if await novnc_flow_registry.cancel_requested(flow.flow_id):
            logger.info(
                "NoVNC Strategy: close of flow_id=%s slot=%s was asked; no session was written",
                flow.flow_id,
                flow.window.slot,
            )

            return CANCELLED_OUTCOME
        if progress.refused_navigations:
            return _UNSAFE_URI_OUTCOME
        if _is_browser_gone(browser, page):
            return _BROWSER_GONE_OUTCOME
        try:
            outcome, last_page_blocked = await _poll_once(page, responses, context, flow, progress)
        except _BrowserGoneError:
            return _BROWSER_GONE_OUTCOME
        if outcome is not None:
            return outcome

        await asyncio.sleep(
            min(settings.NOVNC_COOKIE_SYNC_POLL_SECONDS, max(0.0, deadline - time.monotonic()))
        )

    outcome = _timeout_outcome(flow.intervention_type, last_page_blocked)
    logger.warning(
        "NoVNC Strategy: %s intervention for %s timed out after %ss "
        "(outcome=%s flow_id=%s slot=%s); no session was written",
        flow.intervention_type,
        address_without_query(flow.url),
        settings.NOVNC_TIMEOUT_SECONDS,
        outcome,
        flow.flow_id,
        flow.window.slot,
    )

    return outcome


@dataclass
class _OpenedWindow:
    """What `_run_window` has opened so far, for the teardown of `_monitor_for_cookies`."""

    browser: Any = None
    progress: _FlowProgress | None = None


@asynccontextmanager
async def _started_playwright() -> AsyncIterator[Any]:
    """Run the Playwright driver for the block, and stop it even when its start is cancelled."""
    manager = async_playwright()
    start = asyncio.ensure_future(manager.__aenter__())
    try:
        playwright = await asyncio.shield(start)
    except asyncio.CancelledError:
        await asyncio.wait({start})
        if start.exception() is None:
            await manager.__aexit__(None, None, None)
        raise
    try:
        yield playwright
    finally:
        await manager.__aexit__(None, None, None)


def _vnc_page_address(base: str) -> str:
    """The NoVNC page under *base*, addressed by service version so an update never opens a saved copy."""
    return f"{base}/vnc.html?autoconnect=true&v={_SERVICE_VERSION}"


async def _run_window(playwright: Any, flow: NoVNCFlow, opened: _OpenedWindow, deadline: float) -> str:
    """Open the flow's browser and poll its page until the flow settles. Returns the outcome label."""
    fp = get_default_fingerprint()
    opened.browser = browser = await playwright.chromium.launch(
        headless=False,
        args=[
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-gpu",
            "--remote-debugging-port=0",
            "--remote-debugging-address=127.0.0.1",
            f"--window-position={flow.window.x},{flow.window.y}",
            f"--window-size={flow.window.width},{flow.window.height}",
            *chromium_guard_args(),
        ],
    )
    context_kwargs: dict[str, Any] = {
        "locale": fp.locale,
        "timezone_id": fp.timezone_id,
        "geolocation": fp.geolocation,
        "permissions": ["geolocation"],
        "service_workers": "block",
    }
    stored_state = await cookie_manager.get_storage_state(flow.url, flow.profile)
    if stored_state is not None:
        context_kwargs["storage_state"] = stored_state
    opened.progress = progress = _FlowProgress(
        site=CookieManager.registrable_domain(flow.url),
        starts_logged_in=await cookie_manager.has_valid_login(flow.url, flow.profile),
    )
    proxy = proxy_provider.for_playwright()
    if proxy is not None:
        context_kwargs["proxy"] = browser_tunnel.chained_proxy(proxy)
    context = await browser.new_context(**context_kwargs)
    progress.refused_navigations = await install_browser_guard(
        context, shared_url_validator, family=BrowserFamily.CHROMIUM
    )

    page = await context.new_page()
    responses = MainFrameResponses(page)

    try:
        responses.seed(
            await guarded_goto(page, flow.url, wait_until="commit", timeout=_navigation_timeout_ms(deadline))
        )
    except Exception as e:
        logger.warning(
            "NoVNC Strategy: Initial navigation failed for flow_id=%s slot=%s: %s",
            flow.flow_id,
            flow.window.slot,
            e,
        )

    outcome = await _poll_until_settled(browser, page, responses, context, flow, progress, deadline)
    _log_browser_closed(flow, outcome)

    return outcome


async def _monitor_for_cookies(flow: NoVNCFlow) -> None:
    logger.info(
        "Background task started to monitor session for %s (%s) flow_id=%s slot=%s",
        address_without_query(flow.url),
        flow.intervention_type,
        flow.flow_id,
        flow.window.slot,
    )
    dlabel = domain_label(flow.url)
    outcome = CANCELLED_OUTCOME
    deadline = flow.lease_started + settings.NOVNC_TIMEOUT_SECONDS
    opened = _OpenedWindow()

    try:
        async with _started_playwright() as playwright:
            try:
                outcome = await asyncio.create_task(_run_window(playwright, flow, opened, deadline))
            finally:
                await _close_browser(opened.browser, flow)
    except Exception:
        logger.exception(
            "Background noVNC monitoring task failed for flow_id=%s slot=%s",
            flow.flow_id,
            flow.window.slot,
        )
        outcome = "timeout"
    finally:
        _record_final_verdict(opened.progress)
        await novnc_flow_registry.finish(flow, outcome)
        STRATEGY_ATTEMPTS_TOTAL.labels(strategy=_MONITOR_STRATEGY_LABEL, outcome=outcome, domain=dlabel).inc()


class NoVNCStrategy(BaseStrategy):
    def __init__(self, profile: str | None = None) -> None:
        self.profile = profile

    async def extract(self, url: str) -> str:
        return await self.get_html(url)

    async def get_html(
        self,
        url: str,
        last_verdict: ChallengeVerdict | None = None,
        *,
        intervention_type: str | None = None,
    ) -> str:
        """Open or join the intervention flow for *url*; never returns normally.

        Raises:
            HumanInterventionRequiredException: always, naming the flow's window.
            NoVNCFlowBusyException: when every local window slot is taken.
        """
        if intervention_type is None:
            if last_verdict is not None:
                intervention_type = last_verdict.intervention_type
            else:
                intervention_type = "login" if ChallengeDetector.is_login_redirect_url(url) else "captcha"
        effective_profile = self.profile or settings.SESSION_DEFAULT_PROFILE
        key = flow_key_for(url, effective_profile)

        existing = await novnc_flow_registry.find(key)
        if existing is not None:
            self._log_join(existing, key)

            raise _join_exc(existing)

        flow = await novnc_flow_registry.reserve(
            key=key,
            url=url,
            profile=effective_profile,
            intervention_type=intervention_type,
            resolve_vnc_url=self._resolve_public_vnc_url,
        )
        if not novnc_flow_registry.owns(flow):
            self._log_join(flow, key)

            raise _join_exc(flow)

        logger.info(
            "NoVNC Strategy: reserved flow flow_id=%s slot=%s key=%s",
            flow.flow_id,
            flow.window.slot,
            key,
        )
        task = asyncio.create_task(_monitor_for_cookies(flow))
        novnc_flow_registry.attach_task(flow.flow_id, task)

        raise HumanInterventionRequiredException(
            vnc_url=flow.vnc_url,
            intervention_type=intervention_type,
            flow_id=flow.flow_id,
            joined=False,
            window=_window_to_dict(flow),
        )

    @staticmethod
    def _log_join(flow: NoVNCFlow, key: str) -> None:
        logger.info(
            "NoVNC Strategy: joining live flow flow_id=%s slot=%s key=%s",
            flow.flow_id,
            flow.window.slot,
            key,
        )

    async def _resolve_public_vnc_url(self, flow: NoVNCFlow) -> str:
        base_url = settings.NOVNC_PUBLIC_URL
        if base_url:
            hostname = socket.gethostname()

            return f"{_vnc_page_address(f'{base_url}/novnc/{hostname}')}&path=novnc/{hostname}/websockify"
        public_vnc = settings.PUBLIC_VNC_URL
        if "api/tunnels" not in public_vnc:
            return _vnc_page_address(public_vnc)

        return await self._fetch_ngrok_url(public_vnc, flow)

    async def _fetch_ngrok_url(self, api_url: str, flow: NoVNCFlow) -> str:
        try:
            async with httpx.AsyncClient(timeout=_NGROK_API_TIMEOUT_SECONDS) as client:
                response = await client.get(api_url)
                response.raise_for_status()

                return self._extract_url_from_ngrok_response(response.json(), api_url)
        except Exception as e:
            logger.warning(
                "Failed to dynamically resolve PUBLIC_VNC_URL for flow_id=%s slot=%s: %s",
                flow.flow_id,
                flow.window.slot,
                e,
            )

            return _vnc_page_address(settings.SELENIUM_BROWSER_VNC_URL)

    @staticmethod
    def _extract_url_from_ngrok_response(data: dict[str, Any], fallback_url: str) -> str:
        tunnels = data.get("tunnels", [])
        public_vnc = tunnels[0].get("public_url", fallback_url) if tunnels else fallback_url

        return _vnc_page_address(public_vnc)

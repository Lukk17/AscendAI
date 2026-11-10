"""The navigate, poll, render and judge steps every browser tier shares."""

import asyncio
import logging
import time

from ascend_python_common.uri_guard import UnsafeUriError
from playwright.async_api import BrowserContext, Page

from src.api.exceptions import ChallengeDetectedException
from src.config.config import settings
from src.observability.safe_address import address_without_query
from src.reader.browser_guard import guarded_goto
from src.reader.cloudflare.challenge_detector import ChallengeDetector
from src.reader.cloudflare.challenge_signals import (
    ChallengeVerdict,
    as_login_verdict,
    assess,
    log_verdict,
    record_window_verdict,
)
from src.reader.cloudflare.cookie_manager import belongs_to_site, cookie_manager, is_waf_cookie
from src.reader.strategies.base_strategy import FetchedHtml
from src.reader.strategies.main_frame_response import MainFrameResponses

logger = logging.getLogger(__name__)

_MS_PER_SECOND = 1000
_HTML_LENGTH_SCRIPT = "document.documentElement.outerHTML.length"
_USER_AGENT_SCRIPT = "navigator.userAgent"
_CLEARANCE_COOKIE = "cf_clearance"


class PageContentError(Exception):
    """The rendered page was not copied out of the browser."""


class PageTooLargeError(PageContentError):
    """The rendered page is above ``BROWSER_RESPONSE_MAX_BYTES``."""


class PageNotMeasuredError(PageContentError):
    """The size of the rendered page could not be read."""


class ReadVerdict:
    """The one verdict a browser read records: the first one recorded, else the last one kept."""

    def __init__(self, tier: str) -> None:
        self.tier = tier
        self._last: ChallengeVerdict | None = None
        self._recorded = False
        self.saw_wall = False

    def keep(self, verdict: ChallengeVerdict) -> None:
        self._last = verdict
        self.saw_wall = self.saw_wall or verdict.wall

    def record(self, verdict: ChallengeVerdict) -> None:
        if self._recorded:
            return
        record_window_verdict(verdict, self.tier)
        self._recorded = True

    def record_kept(self) -> None:
        if self._last is not None:
            self.record(self._last)


async def _page_html_length(page: Page) -> int:
    try:
        length = await page.evaluate(_HTML_LENGTH_SCRIPT)
    except Exception as exc:
        raise PageNotMeasuredError(f"measuring the page failed: {type(exc).__name__}") from exc
    if not isinstance(length, int):
        raise PageNotMeasuredError("the page has no markup to measure")

    return length


async def bounded_page_content(page: Page) -> str:
    """Measure *page* inside its renderer, and copy its markup out only when it is within the cap.

    Raises:
        PageTooLargeError: when the markup is above ``BROWSER_RESPONSE_MAX_BYTES``.
        PageNotMeasuredError: when the measurement failed.
    """
    length = await _page_html_length(page)
    if length > settings.BROWSER_RESPONSE_MAX_BYTES:
        raise PageTooLargeError(f"the page holds {length} characters of markup, above the cap")

    return await page.content()


def raise_if_refused(refused_navigations: list[str], cause: BaseException | None = None) -> None:
    """End the read when the guard or the tunnel refused a navigation of its main frame.

    Raises:
        UnsafeUriError: when a refusal was recorded.
    """
    if refused_navigations:
        raise UnsafeUriError(f"browser request refused: {refused_navigations[0]}") from cause


def _label(tier: str) -> str:
    return f"{tier.capitalize()}Strategy"


async def context_cookie_names(context: BrowserContext) -> list[str]:
    """Names of the cookies *context* holds now."""
    cookies = await context.cookies()

    return [str(cookie.get("name", "")) for cookie in cookies]


async def assess_content(
    page: Page,
    url: str,
    responses: MainFrameResponses,
    content: str,
    *,
    tier: str,
) -> ChallengeVerdict:
    """One logged, unrecorded verdict over *content* with the latest main-frame
    response's status and headers and the context's current cookie names."""
    response_status, headers = await responses.status_and_headers()
    verdict = await asyncio.to_thread(
        assess,
        response_status,
        content,
        headers,
        await context_cookie_names(page.context),
        record_metrics=False,
    )
    log_verdict(verdict, tier, url)

    return verdict


async def judge_rendered_page(
    page: Page,
    url: str,
    responses: MainFrameResponses,
    content: str,
    verdicts: ReadVerdict,
    refused_navigations: list[str],
) -> ChallengeVerdict:
    """Record one verdict over the rendered *content* and return it.

    Raises:
        UnsafeUriError: when a navigation of the read's main frame was refused.
        ChallengeDetectedException: when the page is a login wall.
    """
    verdict = await assess_content(page, url, responses, content, tier=verdicts.tier)
    verdicts.record(verdict)
    raise_if_refused(refused_navigations)

    login = ChallengeDetector.login_wall_verdict(verdict, content, requested_url=url, final_url=page.url)
    if login is not None:
        logger.warning(
            "%s: Late-stage Login wall detected on %s. Content Length: %d",
            _label(verdicts.tier),
            address_without_query(url),
            len(content),
        )

        raise ChallengeDetectedException(login)

    return verdict


async def initial_navigation(
    page: Page,
    url: str,
    refused_navigations: list[str],
    responses: MainFrameResponses,
    *,
    error_type: type[Exception],
) -> None:
    """Navigate to *url* and seed the main-frame record with its response.

    Raises:
        UnsafeUriError: when the guard refused the navigation.
    """
    timeout_ms = settings.EXTRACT_TIMEOUT * _MS_PER_SECOND
    try:
        initial_response = await guarded_goto(page, url, wait_until="domcontentloaded", timeout=timeout_ms)
    except error_type as exc:
        raise_if_refused(refused_navigations, exc)

        raise

    raise_if_refused(refused_navigations)
    responses.seed(initial_response)


async def scroll_page(page: Page) -> None:
    """Scroll down in increments to trigger lazy-load / infinite-scroll content."""
    for _ in range(settings.SCROLL_ITERATIONS):
        await page.evaluate(f"window.scrollBy(0, {settings.SCROLL_STEP_PX})")
        await page.wait_for_timeout(settings.SCROLL_PAUSE_MS)


async def _refuse_login_redirect_url(page: Page, url: str, verdicts: ReadVerdict) -> None:
    if not ChallengeDetector.is_login_redirect_url(url):
        return
    logger.warning(
        "%s: Pre-emptive redirect login URI detected on %s", _label(verdicts.tier), address_without_query(url)
    )
    verdict = as_login_verdict(
        assess(200, "", None, await context_cookie_names(page.context), record_metrics=False)
    )
    verdicts.record(verdict)
    raise ChallengeDetectedException(verdict)


async def _poll_until_settled(
    page: Page,
    url: str,
    responses: MainFrameResponses,
    refused_navigations: list[str],
    verdicts: ReadVerdict,
    *,
    error_type: type[Exception],
) -> None:
    label = _label(verdicts.tier)
    poll_start = time.perf_counter()
    extract_deadline = poll_start + settings.EXTRACT_TIMEOUT
    challenge_deadline = poll_start + settings.CHALLENGE_CLEAR_WAIT_SECONDS

    while time.perf_counter() < extract_deadline:
        try:
            content = await bounded_page_content(page)
        except (error_type, PageNotMeasuredError) as exc:
            raise_if_refused(refused_navigations, exc)
            await page.wait_for_timeout(settings.NETWORKIDLE_POLL_MS)
            continue

        verdict = await assess_content(page, url, responses, content, tier=verdicts.tier)
        verdicts.keep(verdict)
        raise_if_refused(refused_navigations)

        login = ChallengeDetector.login_wall_verdict(verdict, content, requested_url=url, final_url=page.url)
        if login is not None:
            logger.warning("%s: Login wall detected on %s (early exit)", label, address_without_query(url))

            verdicts.record(login)
            raise ChallengeDetectedException(login)

        if verdict.wall:
            if time.perf_counter() >= challenge_deadline:
                logger.warning(
                    "%s: WAF/Cloudflare challenge did not auto-clear within %ss on %s; escalating",
                    label,
                    settings.CHALLENGE_CLEAR_WAIT_SECONDS,
                    address_without_query(url),
                )

                verdicts.record(verdict)
                raise ChallengeDetectedException(verdict)
            await page.wait_for_timeout(settings.NETWORKIDLE_POLL_MS)
            continue

        try:
            await page.wait_for_load_state("networkidle", timeout=settings.NETWORKIDLE_POLL_MS)
            break
        except error_type:
            pass


async def _save_earned_clearance(
    page: Page, url: str, producer: str, profile: str | None, error_type: type[Exception]
) -> None:
    """Store the WAF cookies of a read that cleared a wall, never its other cookies or storage."""
    try:
        state = await page.context.storage_state()
        user_agent = await page.evaluate(_USER_AGENT_SCRIPT)
    except error_type as exc:
        logger.warning(
            "Browser tier %s: could not read the cleared session of %s: %s",
            producer,
            address_without_query(url),
            type(exc).__name__,
        )

        return

    site = cookie_manager.registrable_domain(url)
    waf_cookies = [
        cookie
        for cookie in state["cookies"]
        if is_waf_cookie(cookie["name"]) and belongs_to_site(cookie["domain"], site)
    ]
    if any(cookie["name"] == _CLEARANCE_COOKIE for cookie in waf_cookies):
        await cookie_manager.save_storage_state(
            url, {"cookies": waf_cookies, "origins": []}, user_agent, profile, producer
        )


async def render_and_judge(
    page: Page,
    url: str,
    responses: MainFrameResponses,
    refused_navigations: list[str],
    *,
    tier: str,
    error_type: type[Exception],
    producer: str,
    profile: str | None,
) -> FetchedHtml:
    """Navigate, wait for a challenge to clear, render, and return the accepted page.

    Every read records at most one verdict, the last check's when the read fails after a check.

    Raises:
        ChallengeDetectedException: when the page is a login wall, a wall or carries no content.
        UnsafeUriError: when the guard refused the navigation or a later main-frame navigation.
    """
    verdicts = ReadVerdict(tier)
    label = _label(tier)
    try:
        await _refuse_login_redirect_url(page, url, verdicts)
        await initial_navigation(page, url, refused_navigations, responses, error_type=error_type)
        await _poll_until_settled(page, url, responses, refused_navigations, verdicts, error_type=error_type)

        await page.wait_for_timeout(settings.DYNAMIC_CONTENT_WAIT)
        await scroll_page(page)

        content = await bounded_page_content(page)

        logger.info(
            "%s: Finished rendering %s. Extracted HTML Length: %d",
            label,
            address_without_query(url),
            len(content),
        )

        verdict = await judge_rendered_page(page, url, responses, content, verdicts, refused_navigations)
    finally:
        verdicts.record_kept()

    if not verdict.accepted:
        logger.warning(
            "%s: WAF/Cloudflare block detected post-render on %s", label, address_without_query(url)
        )

        raise ChallengeDetectedException(verdict)

    if verdicts.saw_wall:
        await _save_earned_clearance(page, url, producer, profile, error_type)

    return await responses.page_html(content)

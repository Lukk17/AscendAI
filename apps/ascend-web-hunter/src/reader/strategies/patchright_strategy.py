import logging
import time
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any, cast

import trafilatura
from ascend_python_common.uri_guard import UnsafeUriError
from patchright.async_api import Browser, BrowserContext, Page, async_playwright
from patchright.async_api import Error as PatchrightError

from src.api.exceptions import ChallengeDetectedException
from src.config.config import settings
from src.proxy.proxy_provider import proxy_provider
from src.reader.browser_guard import install_browser_guard
from src.reader.cloudflare.challenge_detector import ChallengeDetector
from src.reader.cloudflare.challenge_signals import (
    ChallengeVerdict,
    as_login_verdict,
    assess,
    log_verdict,
    record_verdict,
)
from src.reader.cloudflare.cookie_manager import cookie_manager
from src.reader.fingerprint import Fingerprint, get_default_fingerprint
from src.reader.screenshot import capture_page
from src.reader.strategies.base_strategy import BaseStrategy
from src.validator.url_validator import URLValidator

if TYPE_CHECKING:
    from playwright.async_api import BrowserContext as PlaywrightBrowserContext

logger = logging.getLogger(__name__)

_PATCHRIGHT_TIER = "patchright"

_MS_PER_SECOND = 1000


class PatchrightStrategy(BaseStrategy):
    def __init__(
        self,
        user_agent_provider: Callable[[], str],
        url_validator: URLValidator,
        profile: str | None = None,
        fingerprint: Fingerprint | None = None,
    ) -> None:
        self.user_agent_provider = user_agent_provider
        self.url_validator = url_validator
        self.profile = profile
        self.fingerprint = fingerprint or get_default_fingerprint()

    async def extract(self, url: str) -> str:
        html = await self.get_html(url)
        extracted: str | None = trafilatura.extract(html)

        return extracted or ""

    async def screenshot_page(self, url: str) -> tuple[str, bytes] | None:
        """Capture a full-page PNG of *url* through a fresh patched browser."""
        async with self._launched_browser() as browser:
            return await capture_page(lambda: self._create_context(browser, url), url)

    async def get_html(self, url: str) -> str:
        async with self._launched_browser() as browser:
            context = await self._create_context(browser, url)
            page = await context.new_page()

            refused_navigations = await self._apply_protections(page)

            try:
                if ChallengeDetector.is_login_redirect_url(url):
                    logger.warning(
                        "PatchrightStrategy: Pre-emptive redirect login URI detected on %s",
                        url,
                    )
                    raise ChallengeDetectedException(
                        as_login_verdict(
                            assess(200, "", None, await self._context_cookie_names(context))
                        )
                    )

                response_status, initial_headers = await self._initial_navigation(
                    page, url, refused_navigations
                )
                poll_start = time.perf_counter()
                extract_deadline = poll_start + settings.EXTRACT_TIMEOUT
                challenge_deadline = poll_start + settings.CHALLENGE_CLEAR_WAIT_SECONDS

                content = ""
                while time.perf_counter() < extract_deadline:
                    try:
                        content = await page.content()
                    except PatchrightError:
                        await page.wait_for_timeout(settings.NETWORKIDLE_POLL_MS)
                        continue

                    verdict = await self._assess_content(
                        page, url, response_status, initial_headers, content
                    )

                    if verdict.wall and verdict.intervention_type == "login":
                        logger.warning(
                            "PatchrightStrategy: Login wall detected on %s (early exit)", url
                        )

                        raise ChallengeDetectedException(verdict)

                    if verdict.wall:
                        if time.perf_counter() >= challenge_deadline:
                            logger.warning(
                                "PatchrightStrategy: WAF/Cloudflare challenge did not auto-clear within "
                                "%ss on %s; escalating",
                                settings.CHALLENGE_CLEAR_WAIT_SECONDS,
                                url,
                            )

                            raise ChallengeDetectedException(verdict)
                        await page.wait_for_timeout(settings.NETWORKIDLE_POLL_MS)
                        continue

                    try:
                        await page.wait_for_load_state(
                            "networkidle", timeout=settings.NETWORKIDLE_POLL_MS
                        )
                        break
                    except PatchrightError:
                        pass

                await page.wait_for_timeout(settings.DYNAMIC_CONTENT_WAIT)
                await self._scroll_page(page)

                content = await page.content()

                logger.info(
                    "PatchrightStrategy: Finished rendering %s. Extracted HTML Length: %d",
                    url,
                    len(content),
                )

                return await self._assess_post_render(
                    page, url, response_status, initial_headers, content, refused_navigations
                )
            finally:
                await context.close()

    @asynccontextmanager
    async def _launched_browser(self) -> AsyncIterator[Browser]:
        """Launch one Patchright Chromium for a single read and close it after."""
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=settings.PLAYWRIGHT_HEADLESS,
                args=["--no-sandbox"],
            )
            try:
                yield browser
            finally:
                await browser.close()

    async def _assess_post_render(
        self,
        page: Page,
        url: str,
        response_status: int,
        initial_headers: dict[str, str],
        content: str,
        refused_navigations: list[str],
    ) -> str:
        """One verdict over the rendered content, then the refusal check: a
        page whose script navigated to a refused address fails the tier even
        when the rendered content itself looks clean."""
        verdict = await self._assess_content(
            page, url, response_status, initial_headers, content
        )

        if verdict.wall and verdict.intervention_type == "login":
            logger.warning(
                "PatchrightStrategy: Late-stage Login wall detected on %s. Content Length: %d",
                url,
                len(content),
            )

            raise ChallengeDetectedException(verdict)

        if not verdict.accepted:
            logger.warning(
                "PatchrightStrategy: WAF/Cloudflare block detected post-render on %s", url
            )

            raise ChallengeDetectedException(verdict)

        if refused_navigations:
            logger.warning(
                "PatchrightStrategy: Blocked navigation detected post-render on %s", url
            )

            raise UnsafeUriError(f"browser request refused: {refused_navigations[0]}")

        return content

    async def _initial_navigation(
        self, page: Page, url: str, refused_navigations: list[str]
    ) -> tuple[int, dict[str, str]]:
        """The initial navigation: response status and headers every later
        verdict reuses, because a challenge that clears on its own changes the
        body and the cookies but not the headers of the response that started it.
        A navigation the guard refused ends here with `UnsafeUriError` instead of
        a bare transport error."""
        timeout_ms = settings.EXTRACT_TIMEOUT * _MS_PER_SECOND
        try:
            initial_response = await page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
        except PatchrightError as exc:
            if refused_navigations:
                raise UnsafeUriError(f"browser request refused: {refused_navigations[0]}") from exc

            raise

        response_status = initial_response.status if initial_response else 200
        initial_headers = await initial_response.all_headers() if initial_response else {}

        return response_status, initial_headers

    async def _context_cookie_names(self, context: BrowserContext) -> list[str]:
        cookies = await context.cookies()

        return [str(cookie.get("name", "")) for cookie in cookies]

    async def _assess_content(
        self,
        page: Page,
        url: str,
        response_status: int,
        initial_headers: dict[str, str],
        content: str,
    ) -> ChallengeVerdict:
        """One verdict over the rendered content with the initial response's
        status and headers and the context's current cookie names."""
        verdict = assess(
            response_status,
            content,
            initial_headers,
            await self._context_cookie_names(page.context),
        )
        record_verdict(verdict, _PATCHRIGHT_TIER)
        log_verdict(verdict, _PATCHRIGHT_TIER, url)

        return verdict

    async def _scroll_page(self, page: Page) -> None:
        """Scroll down in increments to trigger lazy-load / infinite-scroll content."""
        for _ in range(settings.SCROLL_ITERATIONS):
            await page.evaluate(f"window.scrollBy(0, {settings.SCROLL_STEP_PX})")
            await page.wait_for_timeout(settings.SCROLL_PAUSE_MS)

    async def _create_context(self, browser: Browser, url: str) -> BrowserContext:
        fp = self.fingerprint
        stored_state = await cookie_manager.get_storage_state(url, self.profile)
        stored_ua = await cookie_manager.get_user_agent(url, self.profile)
        user_agent = stored_ua or fp.user_agent

        kwargs: dict[str, Any] = {
            "user_agent": user_agent,
            "viewport": {"width": fp.viewport_width, "height": fp.viewport_height},
            "locale": fp.locale,
            "timezone_id": fp.timezone_id,
            "geolocation": fp.geolocation,
            "permissions": ["geolocation"],
            "service_workers": "block",
        }
        if stored_state is not None:
            kwargs["storage_state"] = stored_state

        proxy = proxy_provider.for_playwright()
        if proxy is not None:
            kwargs["proxy"] = proxy

        return await browser.new_context(**kwargs)

    async def _apply_protections(self, page: Page) -> list[str]:
        return await install_browser_guard(
            cast("PlaywrightBrowserContext", page.context), self.url_validator
        )

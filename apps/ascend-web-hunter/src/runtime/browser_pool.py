import asyncio
import logging

from playwright.async_api import Browser, Playwright, async_playwright

from src.config.config import settings

logger = logging.getLogger(__name__)


class BrowserPool:
    """
    Single long-lived Chromium process shared across PlaywrightStrategy requests.

    Per-request browser launch was 600-1500 ms of cold start. With a singleton browser
    the per-request cost drops to ~50 ms of BrowserContext creation. The browser process
    is recreated transparently if it disconnects (Chromium OOM, crash, etc.).
    """

    def __init__(self) -> None:
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        async with self._lock:
            if self._browser is not None and self._browser.is_connected():
                return

            await self._launch_locked()

    async def stop(self) -> None:
        async with self._lock:
            if self._browser is not None:
                try:
                    await self._browser.close()
                except Exception as e:
                    logger.warning(f"BrowserPool: error closing browser on shutdown: {e}")
                self._browser = None

            if self._playwright is not None:
                try:
                    await self._playwright.stop()
                except Exception as e:
                    logger.warning(f"BrowserPool: error stopping playwright on shutdown: {e}")
                self._playwright = None

    async def get_browser(self) -> Browser:
        if self._browser is not None and self._browser.is_connected():
            return self._browser

        async with self._lock:
            if self._browser is not None and self._browser.is_connected():
                return self._browser

            logger.warning("BrowserPool: browser is None or disconnected, relaunching.")
            await self._launch_locked()
            assert self._browser is not None

            return self._browser

    async def _launch_locked(self) -> None:
        # Stop the previous driver subprocess on relaunch; without this the Node bridge
        # process orphans every time get_browser() detects a disconnected browser.
        if self._playwright is not None:
            try:
                await self._playwright.stop()
            except Exception as e:
                logger.warning(f"BrowserPool: error stopping prior playwright on relaunch: {e}")
            self._playwright = None

        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=settings.PLAYWRIGHT_HEADLESS,
            args=["--no-sandbox"],
        )
        logger.info(
            f"BrowserPool: launched Chromium (headless={settings.PLAYWRIGHT_HEADLESS}, "
            f"connected={self._browser.is_connected()})"
        )


browser_pool = BrowserPool()

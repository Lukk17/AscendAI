"""Full-page screenshot capture for the `screenshot` output format (design D7).

One helper serves the three real browser strategies: it opens a fresh page
through the strategy's own context factory, navigates once, and returns the
rendered HTML with a full-page PNG. A capture failure returns None so the tier
fails over instead of failing the read. One navigation per read keeps the
fake-site request log at one entry per screenshot read.
"""

import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any

from src.config.config import settings

logger = logging.getLogger(__name__)

_MS_PER_SECOND = 1000


@asynccontextmanager
async def _use_context(
    opener: Callable[[], Awaitable[Any]],
) -> AsyncIterator[Any]:
    context = await opener()
    try:
        yield context
    finally:
        await context.close()


async def capture_page(
    open_context: Callable[[], Awaitable[Any]],
    url: str,
) -> tuple[str, bytes] | None:
    """Navigate once and return the rendered HTML with a full-page PNG."""
    try:
        async with _use_context(open_context) as context:
            page = await context.new_page()
            await page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=settings.EXTRACT_TIMEOUT * _MS_PER_SECOND,
            )
            html = await page.content()
            png = await page.screenshot(full_page=True)

            return html, bytes(png)
    except Exception as exc:
        logger.warning("screenshot: capture failed for %s: %s", url, exc)

        return None

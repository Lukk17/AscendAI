"""Full-page screenshot capture for the `screenshot` output format, one navigation per read."""

import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any

from ascend_python_common.uri_guard import UnsafeUriError

from src.api.exceptions import ChallengeDetectedException
from src.config.config import settings
from src.observability.safe_address import address_without_query, exception_text_without_queries
from src.reader.browser_guard import BrowserFamily, guarded_goto, install_browser_guard
from src.reader.strategies.browser_read import (
    ReadVerdict,
    bounded_page_content,
    judge_rendered_page,
    raise_if_refused,
)
from src.reader.strategies.main_frame_response import MainFrameResponses
from src.validator.url_validator import URLValidator

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
    url_validator: URLValidator,
    *,
    family: BrowserFamily,
    tier: str,
) -> tuple[str, bytes] | None:
    """Navigate once, record one verdict under *tier*, and return the rendered HTML with a full-page PNG.

    Any other capture failure returns None, so the tier fails over instead of failing the read.

    Raises:
        UnsafeUriError: when the guard refused the navigation or a later main-frame navigation.
        ChallengeDetectedException: when the rendered page is a login wall or a wall.
    """
    try:
        async with _use_context(open_context) as context:
            refused_navigations = await install_browser_guard(context, url_validator, family=family)
            page = await context.new_page()
            responses = MainFrameResponses(page)
            try:
                navigation = await guarded_goto(
                    page,
                    url,
                    wait_until="domcontentloaded",
                    timeout=settings.EXTRACT_TIMEOUT * _MS_PER_SECOND,
                )
            except Exception as exc:
                raise_if_refused(refused_navigations, exc)

                raise
            raise_if_refused(refused_navigations)
            responses.seed(navigation)
            content = await bounded_page_content(page)
            verdict = await judge_rendered_page(
                page, url, responses, content, ReadVerdict(tier), refused_navigations
            )
            if verdict.wall:
                raise ChallengeDetectedException(verdict)
            html = await responses.page_html(content)
            png = await page.screenshot(full_page=True)
            raise_if_refused(refused_navigations)

            return html, bytes(png)
    except (UnsafeUriError, ChallengeDetectedException):
        raise
    except Exception as exc:
        logger.warning(
            "screenshot: capture failed for %s: %s",
            address_without_query(url),
            exception_text_without_queries(exc),
        )

        return None

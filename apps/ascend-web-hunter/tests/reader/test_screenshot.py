"""Task 5.2: full-page screenshot capture for the `screenshot` output format."""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.reader.screenshot import capture_page

_PNG = b"\x89PNG\r\n\x1afake-png-bytes"
_HTML = "<html><head><title>Shot</title></head><body><p>Shot.</p></body></html>"


def _page(
    html: str = _HTML,
    screenshot: Any = _PNG,
    goto_error: Exception | None = None,
) -> MagicMock:
    page = MagicMock()
    if goto_error is not None:
        page.goto = AsyncMock(side_effect=goto_error)
    else:
        page.goto = AsyncMock()
    page.content = AsyncMock(return_value=html)
    page.screenshot = AsyncMock(return_value=screenshot)

    return page


def _context(page: MagicMock) -> MagicMock:
    context = MagicMock()
    context.new_page = AsyncMock(return_value=page)
    context.close = AsyncMock()

    return context


@pytest.mark.asyncio
async def test_capture_page_returns_html_and_png() -> None:
    # given
    page = _page()
    context = _context(page)

    async def opener() -> MagicMock:
        return context

    # when
    captured = await capture_page(opener, "https://example.com/")

    # then
    assert captured is not None
    assert captured[0] == _HTML
    assert captured[1] == _PNG
    page.goto.assert_awaited_once()
    assert page.screenshot.await_args is not None
    assert page.screenshot.await_args.kwargs.get("full_page") is True
    context.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_capture_failure_returns_none_and_closes() -> None:
    # given
    page = _page(goto_error=RuntimeError("navigation blew up"))
    context = _context(page)

    async def opener() -> MagicMock:
        return context

    # when
    captured = await capture_page(opener, "https://example.com/")

    # then
    assert captured is None
    context.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_playwright_strategy_screenshot_page() -> None:
    # given
    from src.reader.strategies.playwright_strategy import PlaywrightStrategy

    strategy = PlaywrightStrategy(lambda: "ua", MagicMock())
    context = _context(_page())

    # when
    with (
        patch(
            "src.reader.strategies.playwright_strategy.browser_pool.get_browser",
            new=AsyncMock(return_value=MagicMock()),
        ),
        patch.object(strategy, "_create_stealth_context", new=AsyncMock(return_value=context)),
    ):
        captured = await strategy.screenshot_page("https://example.com/")

    # then
    assert captured is not None
    assert captured[0] == _HTML
    assert captured[1] == _PNG


@pytest.mark.asyncio
async def test_patchright_strategy_screenshot_page() -> None:
    # given
    from src.reader.strategies.patchright_strategy import PatchrightStrategy

    strategy = PatchrightStrategy(lambda: "ua", MagicMock())
    browser = MagicMock()
    context = _context(_page())

    # when
    with (
        patch.object(strategy, "_launched_browser") as launched,
        patch.object(strategy, "_create_context", new=AsyncMock(return_value=context)),
    ):
        launched.return_value.__aenter__ = AsyncMock(return_value=browser)
        launched.return_value.__aexit__ = AsyncMock(return_value=False)
        captured = await strategy.screenshot_page("https://example.com/")

    # then
    assert captured is not None
    assert captured[0] == _HTML
    assert captured[1] == _PNG


@pytest.mark.asyncio
async def test_camoufox_strategy_screenshot_page() -> None:
    # given
    from src.reader.strategies.camoufox_strategy import CamoufoxStrategy

    strategy = CamoufoxStrategy(MagicMock())
    browser = MagicMock()
    context = _context(_page())

    # when
    with (
        patch("src.reader.strategies.camoufox_strategy.AsyncCamoufox") as factory,
        patch.object(strategy, "_create_context", new=AsyncMock(return_value=context)),
    ):
        factory.return_value.__aenter__ = AsyncMock(return_value=browser)
        factory.return_value.__aexit__ = AsyncMock(return_value=False)
        captured = await strategy.screenshot_page("https://example.com/")

    # then
    assert captured is not None
    assert captured[0] == _HTML
    assert captured[1] == _PNG

"""The size check that keeps an inflated page in the renderer."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from playwright.async_api import Error as PlaywrightError

from src.config.config import settings
from src.reader.strategies.browser_read import (
    PageNotMeasuredError,
    PageTooLargeError,
    bounded_page_content,
)

_HTML = "<html></html>"


@pytest.fixture
def stub_page_measure() -> None:
    """The real measurement runs here, in place of the unit-suite stub."""


def _page(measured: object) -> MagicMock:
    page = MagicMock()
    page.evaluate = AsyncMock(return_value=measured)
    page.content = AsyncMock(return_value=_HTML)

    return page


async def test_a_page_within_the_cap_is_copied_after_it_is_measured_in_the_renderer() -> None:
    # given
    page = _page(settings.BROWSER_RESPONSE_MAX_BYTES)

    # when
    html = await bounded_page_content(page)

    # then
    assert html == _HTML
    assert page.evaluate.await_args.args == ("document.documentElement.outerHTML.length",)


async def test_a_page_above_the_cap_is_never_copied() -> None:
    # given
    page = _page(settings.BROWSER_RESPONSE_MAX_BYTES + 1)

    # when / then
    with pytest.raises(PageTooLargeError):
        await bounded_page_content(page)

    page.content.assert_not_awaited()


async def test_a_measurement_that_throws_is_never_copied() -> None:
    # given
    page = _page(0)
    page.evaluate = AsyncMock(side_effect=PlaywrightError("Execution context was destroyed"))

    # when / then
    with pytest.raises(PageNotMeasuredError):
        await bounded_page_content(page)

    page.content.assert_not_awaited()


@pytest.mark.parametrize("measured", [None, "12", 1.5], ids=["null", "text", "float"])
async def test_a_measurement_that_is_not_a_length_is_never_copied(measured: object) -> None:
    # given
    page = _page(measured)

    # when / then
    with pytest.raises(PageNotMeasuredError):
        await bounded_page_content(page)

    page.content.assert_not_awaited()

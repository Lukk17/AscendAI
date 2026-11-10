"""Every browser tier launches with the guard settings and installs the guard for its browser family."""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.reader.browser_guard import BrowserFamily, chromium_guard_args, firefox_guard_prefs
from src.reader.strategies.camoufox_strategy import CamoufoxStrategy
from src.reader.strategies.patchright_strategy import PatchrightStrategy
from src.reader.strategies.playwright_strategy import PlaywrightStrategy


class _StopReadError(Exception):
    pass


def _validator() -> MagicMock:
    return MagicMock(should_block=MagicMock(return_value=False))


@pytest.mark.asyncio
async def test_patchright_launches_chromium_with_the_guard_arguments() -> None:
    # given
    driver = MagicMock()
    driver.chromium.launch = AsyncMock(return_value=MagicMock(close=AsyncMock()))
    entered = MagicMock()
    entered.__aenter__ = AsyncMock(return_value=driver)
    entered.__aexit__ = AsyncMock(return_value=False)

    # when
    with patch("src.reader.strategies.patchright_strategy.async_playwright", return_value=entered):
        async with PatchrightStrategy(lambda: "ua", _validator())._launched_browser():
            pass

    # then
    assert driver.chromium.launch.await_args.kwargs["args"] == ["--no-sandbox", *chromium_guard_args()]


@pytest.mark.asyncio
async def test_camoufox_launches_firefox_with_the_guard_preferences() -> None:
    # given
    launcher = MagicMock(side_effect=_StopReadError())

    # when
    with (
        patch("src.reader.strategies.camoufox_strategy.AsyncCamoufox", new=launcher),
        patch("src.reader.strategies.camoufox_strategy.proxy_provider.for_playwright", return_value=None),
        pytest.raises(_StopReadError),
    ):
        await CamoufoxStrategy(_validator()).get_html("https://example.com/")

    # then
    assert launcher.call_args.kwargs["firefox_user_prefs"] == dict(firefox_guard_prefs())


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("strategy", "module", "family"),
    [
        (PlaywrightStrategy(lambda: "ua", _validator()), "playwright_strategy", BrowserFamily.CHROMIUM),
        (PatchrightStrategy(lambda: "ua", _validator()), "patchright_strategy", BrowserFamily.CHROMIUM),
        (CamoufoxStrategy(_validator()), "camoufox_strategy", BrowserFamily.FIREFOX),
    ],
)
async def test_tier_installs_the_guard_for_its_browser_family(
    strategy: Any, module: str, family: BrowserFamily
) -> None:
    # given
    page = MagicMock()
    install = AsyncMock(return_value=[])

    # when
    with (
        patch(f"src.reader.strategies.{module}.install_browser_guard", new=install),
        patch(
            "src.reader.strategies.playwright_strategy.Stealth",
            return_value=MagicMock(apply_stealth_async=AsyncMock()),
        ),
    ):
        await strategy._apply_protections(page)

    # then
    assert install.await_args is not None
    assert install.await_args.kwargs["family"] is family

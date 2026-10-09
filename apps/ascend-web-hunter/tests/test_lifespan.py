from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from asgi_lifespan import LifespanManager
from fastapi import FastAPI


def _no_banner_network() -> tuple[Any, ...]:
    from ascend_python_common.startup_banner import BannerCheck

    return (
        patch(
            "src.config.startup_banner._searxng_check_sync",
            return_value=BannerCheck(
                label="SearXNG", target="http://localhost:9020/healthz", status="Connected"
            ),
        ),
        patch(
            "src.config.startup_banner._flaresolverr_check_sync",
            return_value=BannerCheck(
                label="FlareSolverr", target="http://localhost:8191", status="Connected"
            ),
        ),
        patch(
            "src.config.startup_banner._redis_check_sync",
            return_value=BannerCheck(label="Redis", target="redis://127.0.0.1:6379/0", status="Connected"),
        ),
    )


@pytest.mark.asyncio
async def test_lifespan_raises_when_blocklist_not_loaded() -> None:
    """The lifespan must fail hard if the blocklist singleton was somehow never loaded."""
    # given
    from src import main as main_module
    from src.config.blocklist_loader import blocklist_loader

    original_state = blocklist_loader.state

    # when
    with patch.object(blocklist_loader, "_state", None):
        # Build a fresh app so we exercise the new lifespan.
        app = main_module.create_app()
        with pytest.raises(RuntimeError):
            async with LifespanManager(app):
                pass

    # then
    assert blocklist_loader.state == original_state


@pytest.mark.asyncio
async def test_lifespan_logs_warning_when_rest_search_client_close_fails() -> None:
    # given
    from src import main as main_module

    # when / then
    with (
        patch.object(
            main_module.rest_search_client,  # type: ignore[attr-defined]
            "aclose",
            new=AsyncMock(side_effect=RuntimeError("rest close failed")),
        ),
        patch.object(
            main_module.mcp_search_client,  # type: ignore[attr-defined]
            "aclose",
            new=AsyncMock(),
        ),
        _no_banner_network()[0],
        _no_banner_network()[1],
        _no_banner_network()[2],
    ):
        app: FastAPI = main_module.create_app()
        async with LifespanManager(app):
            pass


@pytest.mark.asyncio
async def test_lifespan_logs_warning_when_browser_pool_stop_fails() -> None:
    # given
    from src import main as main_module
    from src.runtime.browser_pool import browser_pool

    # when / then
    with (
        patch.object(
            browser_pool,
            "stop",
            new=AsyncMock(side_effect=RuntimeError("stop failed")),
        ),
        _no_banner_network()[0],
        _no_banner_network()[1],
        _no_banner_network()[2],
    ):
        app: FastAPI = main_module.create_app()
        async with LifespanManager(app):
            pass


@pytest.mark.asyncio
async def test_lifespan_logs_warning_when_mcp_search_client_close_fails() -> None:
    # given
    from src import main as main_module

    # when / then
    with (
        patch.object(
            main_module.rest_search_client,  # type: ignore[attr-defined]
            "aclose",
            new=AsyncMock(),
        ),
        patch.object(
            main_module.mcp_search_client,  # type: ignore[attr-defined]
            "aclose",
            new=AsyncMock(side_effect=RuntimeError("mcp close failed")),
        ),
        _no_banner_network()[0],
        _no_banner_network()[1],
        _no_banner_network()[2],
    ):
        app: FastAPI = main_module.create_app()
        async with LifespanManager(app):
            pass

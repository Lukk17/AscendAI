from unittest.mock import AsyncMock, patch

import pytest
from asgi_lifespan import LifespanManager
from fastapi import FastAPI


@pytest.mark.asyncio
async def test_lifespan_raises_when_blocklist_not_loaded():
    """The lifespan must fail hard if the blocklist singleton was somehow never loaded."""
    from src import main as main_module
    from src.config.blocklist_loader import blocklist_loader

    original_state = blocklist_loader.state
    with patch.object(blocklist_loader, "_state", None):
        # Build a fresh app so we exercise the new lifespan.
        app = main_module.create_app()
        with pytest.raises(RuntimeError):
            async with LifespanManager(app):
                pass
    assert blocklist_loader.state == original_state


@pytest.mark.asyncio
async def test_lifespan_logs_warning_when_rest_search_client_close_fails():
    from src import main as main_module

    with (
        patch.object(
            main_module.rest_search_client,
            "aclose",
            new=AsyncMock(side_effect=RuntimeError("rest close failed")),
        ),
        patch.object(
            main_module.mcp_search_client,
            "aclose",
            new=AsyncMock(),
        ),
    ):
        app: FastAPI = main_module.create_app()
        async with LifespanManager(app):
            pass


@pytest.mark.asyncio
async def test_lifespan_logs_warning_when_mcp_search_client_close_fails():
    from src import main as main_module

    with (
        patch.object(
            main_module.rest_search_client,
            "aclose",
            new=AsyncMock(),
        ),
        patch.object(
            main_module.mcp_search_client,
            "aclose",
            new=AsyncMock(side_effect=RuntimeError("mcp close failed")),
        ),
    ):
        app: FastAPI = main_module.create_app()
        async with LifespanManager(app):
            pass

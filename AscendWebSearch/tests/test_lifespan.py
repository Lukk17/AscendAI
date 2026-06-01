from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from asgi_lifespan import LifespanManager
from fastapi import FastAPI


@pytest.mark.asyncio
async def test_lifespan_raises_when_blocklist_load_fails():
    """The lifespan must fail hard if BlocklistLoader cannot initialise."""
    from src import main as main_module

    with patch(
        "src.main.BlocklistLoader",
    ) as mock_loader_cls:
        mock_loader = MagicMock()
        mock_loader.load_rules.side_effect = RuntimeError("network down")
        mock_loader_cls.return_value = mock_loader

        # Build a fresh app so we exercise the new lifespan.
        app = main_module.create_app()
        with pytest.raises(RuntimeError):
            async with LifespanManager(app):
                pass


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

import sys
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import anyio
import pytest
import pytest_asyncio
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient

mock_fastmcp = MagicMock()
mock_instance = MagicMock()


async def mock_asgi_app(_scope, _receive, _send):
    """Stub ASGI application — discards every call. The FastMCP HTTP mount
    needs *something* with the ASGI signature even though we never invoke it
    in tests."""


class MockRouter:
    @asynccontextmanager
    async def lifespan_context(self, _app):
        """No-op lifespan; the real MCP lifespan is patched per session."""
        yield


mock_asgi_app.router = MockRouter()  # type: ignore[attr-defined]

mock_instance.sse_app.return_value = mock_asgi_app
mock_instance.streamable_http_app.return_value = mock_asgi_app
mock_instance.http_app.return_value = mock_asgi_app
mock_instance.tool.return_value = lambda f: f
mock_fastmcp.FastMCP.return_value = mock_instance
sys.modules["mcp.server.fastmcp"] = mock_fastmcp
sys.modules["fastmcp"] = mock_fastmcp

from src.main import app  # noqa: E402
from src.reader.cloudflare.cookie_manager import CookieManager  # noqa: E402


@pytest.fixture(autouse=True)
def reset_cookie_manager_singleton():
    """Cookie singleton bleeds state across tests. Reset before every test."""
    CookieManager._instance = None
    yield
    CookieManager._instance = None


@pytest.fixture(autouse=True)
def stub_browser_pool(monkeypatch):
    """Replace the real BrowserPool with mocks; no Chromium launched in unit tests."""
    from src.runtime import browser_pool as bp_module

    bp = bp_module.browser_pool
    monkeypatch.setattr(bp, "start", AsyncMock())
    monkeypatch.setattr(bp, "stop", AsyncMock())

    mock_browser = MagicMock()
    mock_browser.is_connected = MagicMock(return_value=True)
    mock_browser.close = AsyncMock()
    monkeypatch.setattr(bp, "get_browser", AsyncMock(return_value=mock_browser))


@pytest.fixture(scope="session", autouse=True)
def mock_mcp_lifespan_global():
    import src.main as main_module

    if not hasattr(main_module, "mcp"):
        yield
        return

    original_run = main_module.mcp.session_manager.run

    @asynccontextmanager
    async def _mock_run():
        async with anyio.create_task_group() as tg:
            setattr(main_module.mcp.session_manager, "_task_group", tg)
            try:
                yield tg
            finally:
                tg.cancel_scope.cancel()
                if hasattr(main_module.mcp.session_manager, "_task_group"):
                    delattr(main_module.mcp.session_manager, "_task_group")

    main_module.mcp.session_manager.run = _mock_run

    yield

    main_module.mcp.session_manager.run = original_run


@pytest_asyncio.fixture(scope="function")
async def client() -> AsyncGenerator[AsyncClient, None]:
    async with LifespanManager(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
            yield ac

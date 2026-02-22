import sys
from unittest.mock import MagicMock

# Global Mock for FastMCP to prevent RuntimeErrors during testing
mock_fastmcp = MagicMock()
mock_instance = MagicMock()

from contextlib import asynccontextmanager


# Mock sse_app to return a valid-ish ASGI app (callable)
async def mock_asgi_app(scope, receive, send):
    pass


class MockRouter:
    @asynccontextmanager
    async def lifespan_context(self, app):
        yield


mock_asgi_app.router = MockRouter()

mock_instance.sse_app.return_value = mock_asgi_app
mock_instance.streamable_http_app.return_value = mock_asgi_app
mock_instance.http_app.return_value = mock_asgi_app
mock_instance.tool.return_value = lambda f: f
mock_fastmcp.FastMCP.return_value = mock_instance
sys.modules["mcp.server.fastmcp"] = mock_fastmcp
sys.modules["fastmcp"] = mock_fastmcp

import pytest
import pytest_asyncio
import anyio
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from httpx import AsyncClient, ASGITransport
from asgi_lifespan import LifespanManager

from src.main import app


# Global session-scoped patch for MCP session manager.
# Prevents ALL tests from launching the persistent background loop.
@pytest.fixture(scope="session", autouse=True)
def mock_mcp_lifespan_global():
    # Lazy import to avoid collection-time side effects
    import src.main as main_module

    # Check if mcp is actually defined in main (it should be)
    if not hasattr(main_module, 'mcp'):
        yield
        return

    original_run = main_module.mcp.session_manager.run

    @asynccontextmanager
    async def _mock_run():
        # FastMCP requires an active TaskGroup for tool execution
        async with anyio.create_task_group() as tg:
            # Manually inject the task group into the session manager so it can spawn tasks
            setattr(main_module.mcp.session_manager, "_task_group", tg)
            try:
                yield tg
            finally:
                # Force cancel all tasks to ensure instant teardown and prevent Timeouts
                tg.cancel_scope.cancel()

                # Cleanup task group immediately after context exits to allow re-entry
                if hasattr(main_module.mcp.session_manager, "_task_group"):
                    delattr(main_module.mcp.session_manager, "_task_group")

    # Apply patch
    main_module.mcp.session_manager.run = _mock_run

    yield

    # Restore patch
    main_module.mcp.session_manager.run = original_run


@pytest_asyncio.fixture(scope="function")
async def client() -> AsyncGenerator[AsyncClient, None]:
    """
    Creates an async test client with Lifespan support.
    """
    async with LifespanManager(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
            yield ac

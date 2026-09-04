import sys
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock
from unittest.mock import patch as _patch

import anyio
import httpx
import pytest
import pytest_asyncio
from adblockparser import AdblockRules
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient

from src.config.blocklist_loader import BlocklistLoader


def _blocked_handle_request(*_args: object, **_kwargs: object) -> None:
    raise RuntimeError(
        "Unit test attempted a real network call via httpx.HTTPTransport. "
        "Mock the client/method under test instead of letting it reach the network."
    )


async def _blocked_handle_async_request(*_args: object, **_kwargs: object) -> None:
    raise RuntimeError(
        "Unit test attempted a real network call via httpx.AsyncHTTPTransport. "
        "Mock the client/method under test instead of letting it reach the network."
    )


# Enforced for the entire test session, from collection onward: every unit test in
# this suite mocks httpx at the client method level (`.get`, `.client.get`, ...),
# never at the transport, and the ASGI test client uses the unrelated
# `ASGITransport` class. A real `httpx.Client`/`AsyncClient` reaching this default
# transport means a mock is missing. Fail immediately and loudly instead of
# actually dialing out and eating the network's real latency.
httpx.HTTPTransport.handle_request = _blocked_handle_request  # type: ignore[method-assign]
httpx.AsyncHTTPTransport.handle_async_request = _blocked_handle_async_request  # type: ignore[method-assign]

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


def _stub_blocklist_download(self: BlocklistLoader) -> None:
    """`rest_endpoints.py` and `mcp_server.py` build a module-level `WebReader()`
    at import time, which calls `BlocklistLoader().load_rules()` immediately.
    Stub the network fetch for the duration of this one import so collecting
    the test suite never reaches the real blocklist URL."""
    self.blocklist_path.write_bytes(b"! test fixture, no live blocklist\n||example-blocked.test^\n")


with _patch.object(BlocklistLoader, "_download_blocklist", _stub_blocklist_download):
    from src.main import app

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


@pytest.fixture(autouse=True)
def stub_blocklist_loader(monkeypatch):
    """`main.py`'s lifespan and every direct `WebReader()` construction build a
    fresh `BlocklistLoader` and re-download the live blocklist over the real
    network — there is no on-disk cache check. Under `asgi_lifespan.LifespanManager`'s
    default 5s startup timeout that live download intermittently times out and
    fails whichever test happens to trigger it; outside that timeout it is still a
    real, unmocked network call on every `WebReader()` construction. Replace it
    with a canned rule set at both use sites so no test ever touches the network."""
    fake_rules = AdblockRules(["||example-blocked.test^"])

    class _StubBlocklistLoader:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        def load_rules(self) -> AdblockRules:
            return fake_rules

    monkeypatch.setattr("src.main.BlocklistLoader", _StubBlocklistLoader)
    monkeypatch.setattr("src.reader.web_reader.BlocklistLoader", _StubBlocklistLoader)


@pytest.fixture(autouse=True)
def stub_startup_banner(monkeypatch):
    """`log_startup_banner()` probes SearXNG, FlareSolverr and Redis over real
    sockets during app startup. Stub it so tests never depend on those
    services being reachable, and never spend the 2s-per-probe timeout."""
    monkeypatch.setattr("src.main.log_startup_banner", AsyncMock())


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
            main_module.mcp.session_manager._task_group = tg
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

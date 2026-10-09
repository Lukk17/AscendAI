import sys
from collections.abc import AsyncGenerator, AsyncIterator, Iterator
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from urllib.parse import urlparse

import anyio
import httpx
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient


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
httpx.HTTPTransport.handle_request = _blocked_handle_request  # type: ignore[method-assign, assignment]
httpx.AsyncHTTPTransport.handle_async_request = _blocked_handle_async_request  # type: ignore[method-assign, assignment]

mock_fastmcp = MagicMock()
mock_instance = MagicMock()

# The library (ascend_python_common) imports the real FastMCP middleware and
# ToolError for its log config, rate limit and refusal mapping, so keep the
# real submodules importable while the top-level FastMCP class stays mocked
# for the service's own MCP server below.
import fastmcp.exceptions as _real_fastmcp_exceptions  # noqa: E402, F401
import fastmcp.server.middleware as _real_fastmcp_middleware  # noqa: E402, F401

_real_fastmcp_submodules = {
    name: module
    for name, module in sys.modules.items()
    if name == "fastmcp.server" or name.startswith("fastmcp.server.") or name == "fastmcp.exceptions"
}


async def mock_asgi_app(_scope: Any, _receive: Any, _send: Any) -> None:
    """Stub ASGI application - discards every call. The FastMCP HTTP mount
    needs *something* with the ASGI signature even though we never invoke it
    in tests."""


class MockRouter:
    @asynccontextmanager
    async def lifespan_context(self, _app: Any) -> AsyncIterator[None]:
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
sys.modules.update(_real_fastmcp_submodules)


from src.main import app  # noqa: E402
from src.reader.cloudflare.cookie_manager import CookieManager  # noqa: E402


@pytest.fixture(autouse=True)
def reset_cookie_manager_singleton() -> Iterator[None]:
    """Cookie singleton bleeds state across tests. Reset before every test."""
    CookieManager._instance = None
    yield
    CookieManager._instance = None


@pytest.fixture(autouse=True)
def stub_browser_pool(monkeypatch: pytest.MonkeyPatch) -> None:
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
def mock_mcp_lifespan_global() -> Iterator[None]:
    import src.main as main_module

    mcp_server: Any = getattr(main_module, "mcp", None)
    if mcp_server is None:
        yield
        return

    original_run = mcp_server.session_manager.run

    @asynccontextmanager
    async def _mock_run() -> AsyncIterator[Any]:
        async with anyio.create_task_group() as tg:
            mcp_server.session_manager._task_group = tg
            try:
                yield tg
            finally:
                tg.cancel_scope.cancel()
                if hasattr(mcp_server.session_manager, "_task_group"):
                    delattr(mcp_server.session_manager, "_task_group")

    mcp_server.session_manager.run = _mock_run

    yield

    mcp_server.session_manager.run = original_run


@pytest.fixture
def pinned_public_host() -> Iterator[None]:
    """Stub the URI fetch guard so unit tests resolve no real name.

    Every host passes with one public address. Tests that exercise the
    guard itself patch `check_fetch_uri` instead and do not take this fixture.
    """
    from ascend_python_common.uri_guard import FetchTarget

    async def _allow(uri: str, policy: object) -> FetchTarget:
        parsed = urlparse(uri)
        port = parsed.port or (443 if parsed.scheme == "https" else 80)

        return FetchTarget(url=uri, host=parsed.hostname or "", port=port, addresses=("93.184.216.34",))

    with (
        patch(
            "src.reader.strategies.curl_cffi_fetcher.check_fetch_uri",
            side_effect=_allow,
        ),
        patch("ascend_python_common.uri_guard.check_fetch_uri", side_effect=_allow),
    ):
        yield


@pytest_asyncio.fixture(scope="function")
async def client() -> AsyncGenerator[AsyncClient, None]:
    # raise_app_exceptions=False lets the registered catch-all Exception
    # handler produce its problem 500 envelope instead of bubbling the
    # exception out of the ASGI app and failing the test client.
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac

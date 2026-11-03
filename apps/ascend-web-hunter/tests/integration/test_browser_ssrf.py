"""Live-browser SSRF guard integration (task 2.6).

Real Chromium (`4-playwright_stealth`, `4a-patchright`, `5-crawlee_adaptive`) and
real Firefox (`4b-camoufox`) against a local test server. The server listens on
127.0.0.1 and is reached through the `localhost` name, allow-listed through
`ALLOWED_PRIVATE_HOSTS` for these tests only, so the guard lets the test pages
through but refuses everything private they point at.

For each browser tier: a public page that redirects to 169.254.169.254, a page
that loads an image from 10.0.0.5, and a page whose script navigates to
127.0.0.1:6379. The two non-routable addresses accept no listener by
construction (binding them fails without the address assigned to an interface),
and 127.0.0.1:6379 is the shared development Redis, so connection silence is
additionally proven by a sentinel listener on 127.0.0.1 that a second script
page targets: it must record zero connections. The redirect and the script
navigation answer `unsafe_uri` on REST and as a tool error on MCP, and the page
with the private image is still returned with its canary sentence.

For the Playwright, Patchright and Camoufox tiers every page gets its own test.
Crawlee keeps process-global loop-bound state across runs, so its four pages
run sequentially inside one test instead (see below). `6-novnc` is out of
scope: it needs a human at the NoVNC window.

Not part of the unit gate: excluded through `--ignore=tests/integration` in
`pyproject.toml`, run alone as `python -m pytest tests/integration -q`.
"""

import logging
import socket
import threading
import time
from collections.abc import AsyncIterator, Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from unittest.mock import patch

import pytest
from ascend_python_common.uri_guard import UnsafeUriError
from fastmcp.exceptions import ToolError
from httpx import AsyncClient

from src.reader.web_reader import TIER_ORDER, WebReader

logger = logging.getLogger(__name__)

pytestmark = pytest.mark.filterwarnings("ignore:Implicitly cleaning up:ResourceWarning")
"""Crawlee launches persistent browser contexts in temp dirs it never closes
itself; their GC-time cleanup warning is third-party noise. The unit gate
excludes this directory."""


@pytest.fixture(autouse=True)
def _reset_crawlee_globals() -> None:
    """Crawlee's global service locator caches a storage client and an event
    manager bound to the first test's event loop; a later test reusing them
    fails with "bound to a different event loop". Drop the cached instances so
    each test builds its own. (conftest's function-scoped async fixture keeps
    every test on its own loop, so sharing is not an option.)"""
    from crawlee import service_locator

    service_locator._storage_client = None
    service_locator._event_manager = None
    service_locator._configuration = None


_CANARY = (
    "The QUARRY-THRUSH survey logged 47 nesting pairs along the basalt cliffs of Lake Mirell on June 9th."
)

_BROWSER_TIERS = [
    "4-playwright_stealth",
    "4a-patchright",
    "4b-camoufox",
    "5-crawlee_adaptive",
]

# Playwright, Patchright and Camoufox hold no cross-read state, so every page
# gets its own test. Crawlee keeps process-global loop-bound state (storage
# client, event manager, autoscaler) that a second pytest test on a new event
# loop cannot reuse; its four pages run sequentially inside one test instead.
_PARAM_TIERS = [
    "4-playwright_stealth",
    "4a-patchright",
    "4b-camoufox",
]


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"
    sentinel_port = 0

    def log_message(self, *args: object) -> None:
        pass

    def do_GET(self) -> None:
        if self.path == "/redirect-private":
            self.send_response(302)
            self.send_header("Location", "http://169.254.169.254/")
            self.end_headers()

            return
        if self.path == "/image-private":
            body = (
                "<html><head><title>Pixels</title></head><body><article><p>"
                + _CANARY
                + '</p><img src="http://10.0.0.5/pixel.png"></article></body></html>'
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

            return
        if self.path == "/script-nav":
            body = (
                "<html><head><title>Nav</title></head><body><article><p>"
                + _CANARY
                + "</p><script>window.location='http://127.0.0.1:6379/';</script>"
                + "</article></body></html>"
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

            return
        if self.path == "/script-nav-sentinel":
            body = (
                "<html><head><title>Nav</title></head><body><article><p>"
                + _CANARY
                + "</p><script>window.location='http://127.0.0.1:"
                + str(type(self).sentinel_port)
                + "/';</script>"
                + "</article></body></html>"
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

            return
        body = (
            "<html><head><title>Plain</title></head><body><article><p>"
            + _CANARY
            + "</p></article></body></html>"
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture(scope="module")
def web_server() -> Iterator[str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://localhost:{port}"
    server.shutdown()
    server.server_close()


@pytest.fixture(scope="module")
def sentinel() -> Iterator[tuple[int, list[str]]]:
    seen: list[str] = []
    listener = socket.socket()
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    listener.listen(5)
    stop = threading.Event()

    def _accept() -> None:
        listener.settimeout(0.2)
        while not stop.is_set():
            try:
                conn, _ = listener.accept()
            except OSError:
                return
            seen.append("connection")
            conn.close()

    thread = threading.Thread(target=_accept, daemon=True)
    thread.start()
    _Handler.sentinel_port = listener.getsockname()[1]
    yield listener.getsockname()[1], seen
    stop.set()
    listener.close()


@pytest.fixture(autouse=True)
async def _real_browser_pool(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[None]:
    """Undo the unit-suite browser-pool stub: these tests drive the real Chromium.

    The stubbed `stop` is a no-op, so close the real browser after each test
    through the real `stop`, or leaked driver sockets fail the suite.
    """
    from src.runtime.browser_pool import BrowserPool, browser_pool

    monkeypatch.setattr(
        browser_pool, "get_browser", BrowserPool.get_browser.__get__(browser_pool, BrowserPool)
    )
    yield
    await BrowserPool.stop(browser_pool)


@pytest.fixture(autouse=True)
def allow_localhost(monkeypatch: pytest.MonkeyPatch) -> None:
    # Every consumer reads the same settings singleton, so one patch covers them all.
    monkeypatch.setattr("src.config.config.settings.ALLOWED_PRIVATE_HOSTS", ("localhost",))
    monkeypatch.setattr("src.reader.web_reader.settings.PLAYWRIGHT_HEADLESS", True)


def _read(base: str, path: str, tier: str) -> Any:
    return WebReader().read(f"{base}{path}", tier=tier)  # type: ignore[arg-type]


@pytest.mark.asyncio
@pytest.mark.parametrize("tier", _PARAM_TIERS)
async def test_redirect_to_private_answers_unsafe_uri(tier: str, web_server: str) -> None:
    # when / then
    with pytest.raises(UnsafeUriError):
        await _read(web_server, "/redirect-private", tier)


@pytest.mark.asyncio
@pytest.mark.parametrize("tier", _PARAM_TIERS)
async def test_page_with_private_image_is_still_returned(tier: str, web_server: str) -> None:
    # when
    result = await _read(web_server, "/image-private", tier)

    # then
    assert result["status"] == "success"
    assert _CANARY in result["content"]


@pytest.mark.asyncio
@pytest.mark.parametrize("tier", _PARAM_TIERS)
async def test_script_navigation_to_private_answers_unsafe_uri(tier: str, web_server: str) -> None:
    # when / then
    with pytest.raises(UnsafeUriError):
        await _read(web_server, "/script-nav", tier)


@pytest.mark.asyncio
@pytest.mark.parametrize("tier", _PARAM_TIERS)
async def test_script_navigation_reaches_no_listener(
    tier: str, web_server: str, sentinel: tuple[int, list[str]]
) -> None:
    # given
    _, seen = sentinel

    # when / then
    with pytest.raises(UnsafeUriError):
        await _read(web_server, "/script-nav-sentinel", tier)
    assert seen == []


@pytest.mark.asyncio
async def test_crawlee_tier_covers_all_pages(web_server: str, sentinel: tuple[int, list[str]]) -> None:
    """The four pages sequentially through `5-crawlee_adaptive`.

    Crawlee keeps process-global loop-bound state across `crawler.run` calls
    that a new pytest test on a fresh event loop cannot reuse, so unlike the
    other browser tiers its pages run back to back inside one test instead of
    one test per page.
    """
    # given
    _, seen = sentinel

    # when / then: redirect to a private address is refused before any connection
    with pytest.raises(UnsafeUriError):
        await _read(web_server, "/redirect-private", "5-crawlee_adaptive")

    # when / then: the page with a private image is still returned with its canary
    result = await _read(web_server, "/image-private", "5-crawlee_adaptive")
    assert result["status"] == "success"
    assert _CANARY in result["content"]

    # when / then: a script navigation to a private address is refused
    with pytest.raises(UnsafeUriError):
        await _read(web_server, "/script-nav", "5-crawlee_adaptive")

    # when / then: the refused script navigation reaches no listener
    with pytest.raises(UnsafeUriError):
        await _read(web_server, "/script-nav-sentinel", "5-crawlee_adaptive")
    assert seen == []


@pytest.mark.asyncio
async def test_redirect_answers_unsafe_uri_on_rest(web_server: str, client: AsyncClient) -> None:
    # when
    with patch("src.api.rest.rest_endpoints.check_fetch_uri", return_value=True):
        resp = await client.post(
            "/api/v2/web/read", json={"url": f"{web_server}/redirect-private", "tier": "4-playwright_stealth"}
        )

    # then
    assert resp.status_code == 400
    assert resp.json()["code"] == "unsafe_uri"


@pytest.mark.asyncio
async def test_script_navigation_answers_unsafe_uri_on_rest(web_server: str, client: AsyncClient) -> None:
    # when
    with patch("src.api.rest.rest_endpoints.check_fetch_uri", return_value=True):
        resp = await client.post(
            "/api/v2/web/read", json={"url": f"{web_server}/script-nav", "tier": "4-playwright_stealth"}
        )

    # then
    assert resp.status_code == 400
    assert resp.json()["code"] == "unsafe_uri"


@pytest.mark.asyncio
async def test_redirect_answers_tool_error_on_mcp(web_server: str) -> None:
    # given
    from src.api.mcp.mcp_server import web_read

    # when / then
    with (
        patch("src.api.mcp.mcp_server.check_fetch_uri", return_value=True),
        pytest.raises(ToolError) as exc_info,
    ):
        await web_read(f"{web_server}/redirect-private", tier="4b-camoufox")

    assert str(exc_info.value).startswith("unsafe_uri: ")


@pytest.mark.asyncio
async def test_script_navigation_answers_tool_error_on_mcp(web_server: str) -> None:
    # given
    from src.api.mcp.mcp_server import web_read

    # when / then
    with (
        patch("src.api.mcp.mcp_server.check_fetch_uri", return_value=True),
        pytest.raises(ToolError) as exc_info,
    ):
        await web_read(f"{web_server}/script-nav", tier="4b-camoufox")

    assert str(exc_info.value).startswith("unsafe_uri: ")


@pytest.mark.asyncio
async def test_guarded_and_unguarded_read_time_is_recorded(web_server: str) -> None:
    # given
    url = f"{web_server}/plain"

    async def _no_guard(context: Any, validator: Any) -> list[str]:
        async def _pass(route: Any) -> None:
            await route.continue_()

        await context.route("**/*", _pass)

        return []

    # when
    started = time.perf_counter()
    guarded = await WebReader().read(url, tier="4-playwright_stealth")
    guarded_ms = (time.perf_counter() - started) * 1000

    with patch("src.reader.strategies.playwright_strategy.install_browser_guard", new=_no_guard):
        started = time.perf_counter()
        unguarded = await WebReader().read(url, tier="4-playwright_stealth")
        unguarded_ms = (time.perf_counter() - started) * 1000

    # then
    assert guarded["status"] == "success"
    assert unguarded["status"] == "success"
    logger.info(
        "browser_guard read time: guarded=%.0fms unguarded=%.0fms url=%s", guarded_ms, unguarded_ms, url
    )


def test_tier_names_cover_every_browser_tier() -> None:
    # when / then
    for tier in _BROWSER_TIERS:
        assert tier in TIER_ORDER

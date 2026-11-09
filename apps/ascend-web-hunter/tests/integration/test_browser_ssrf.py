"""Live-browser SSRF guard integration (task 2.6).

Real Chromium (`4-playwright_stealth`, `4a-patchright`, `5-crawlee_adaptive`) and
real Firefox (`4b-camoufox`) against a local test server. The server listens on
127.0.0.1 and is reached through the `localhost` name, allow-listed through
`ALLOWED_PRIVATE_HOSTS` for these tests only, so the guard lets the test pages
through but refuses everything private they point at.

For each browser tier: a public page that redirects to 169.254.169.254, a page
that loads an image from 10.0.0.5, a page whose script navigates to
127.0.0.1:6379, pages whose sub-frame or popup is refused directly, after a
redirect or after a script navigation, plus one whose sub-frame sends the main
frame to a private address. A popup opened straight to an allowed address loads
through the guard: a script opens it on the Chromium tiers, and on Camoufox,
whose popup blocker stops a popup no click opened, a click opens it. The two
non-routable addresses accept no listener by construction (binding them fails
without the address assigned to an interface),
and 127.0.0.1:6379 is the shared development Redis, so connection silence is
additionally proven by a sentinel listener on 127.0.0.1 that a second script
page targets: it must record zero connections. The redirect and the script
navigation answer `unsafe_uri` on REST and as a tool error on MCP, and the page
with the private image is still returned with its canary sentence.

The rebinding test runs two servers on one port, the checked one on 127.0.0.2
and the rebound one on 127.0.0.1, with the guard's name lookup answering
127.0.0.2 as a public address. Every browser tier, Crawlee included, must read
the page and its subresource from 127.0.0.2, which proves the browser request
goes through the pinned tunnel instead of resolving `localhost` again.

For the Playwright, Patchright and Camoufox tiers every page gets its own test.
Crawlee keeps process-global loop-bound state across runs, so its four pages
run sequentially inside one test instead (see below). `6-novnc` is out of
scope: it needs a human at the NoVNC window.

Not part of the unit gate: excluded through `--ignore=tests/integration` in
`pyproject.toml`, run alone as `python -m pytest tests/integration -q --no-cov`.
"""

import asyncio
import gzip
import logging
import socket
import ssl
import threading
import time
from collections.abc import AsyncIterator, Callable, Iterator
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, ClassVar, cast
from unittest.mock import patch

import pytest
from ascend_python_common.uri_guard import UnsafeUriError
from camoufox.async_api import AsyncCamoufox
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID
from fastmcp.exceptions import ToolError
from httpx import AsyncClient
from patchright.async_api import Error as PatchrightError
from playwright.async_api import Error as PlaywrightError

from src.config.config import settings
from src.reader.browser_guard import BrowserFamily, browser_tunnel, guarded_goto, install_browser_guard
from src.reader.strategies.browser_read import render_and_judge
from src.reader.strategies.camoufox_strategy import _launch_kwargs
from src.reader.strategies.main_frame_response import MainFrameResponses
from src.reader.web_reader import TIER_ORDER, WebReader
from src.validator.url_validator import url_validator as shared_url_validator
from tests.integration.test_browser_guard_fetch import _launched

logger = logging.getLogger(__name__)

pytestmark = pytest.mark.filterwarnings("ignore:Implicitly cleaning up:ResourceWarning")
"""Crawlee launches persistent browser contexts in temp dirs it never closes
itself; their GC-time cleanup warning is third-party noise. The unit gate
excludes this directory."""


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


_SUB_FRAME_PAGES = {
    "/frame-private": '<iframe src="{sentinel}/"></iframe>',
    "/frame-redirect-private": '<iframe src="/redirect-sentinel"></iframe>',
    "/frame-script-nav": '<iframe src="/frame-body-script-nav"></iframe>',
}
_HOLD_READ_OPEN = '<img src="/slow-pixel">'
_POPUP_PAGES = {
    "/popup-private": "<script>window.open('{sentinel}/');</script>",
    "/popup-redirect-private": "<script>window.open('/redirect-sentinel');</script>" + _HOLD_READ_OPEN,
    "/popup-script-nav": "<script>window.open('/frame-body-script-nav');</script>",
    "/popup-then-private": (
        "<script>var popup = window.open('about:blank'); popup.location = '{sentinel}/';</script>"
    ),
}
_POPUP_LOADED_PATH = "/popup-target-loaded"
_POPUP_TARGET_BODY = f'<img src="{_POPUP_LOADED_PATH}">'
_POPUP_ALLOWED_PAGES = {
    "/popup-allowed": f"<script>window.open('/popup-target');</script>{_HOLD_READ_OPEN}",
    "/popup-allowed-redirect": f"<script>window.open('/redirect-popup-target');</script>{_HOLD_READ_OPEN}",
}
_SLOW_PIXEL_SECONDS = 2.0
_POPUP_LINK_PAGES = {
    "/popup-link-allowed": '<a id="open" target="_blank" href="/popup-target">open</a>',
    "/popup-link-allowed-redirect": '<a id="open" target="_blank" href="/redirect-popup-target">open</a>',
    "/popup-link-private": '<a id="open" target="_blank" href="{sentinel}/">open</a>',
    "/popup-link-redirect-private": '<a id="open" target="_blank" href="/redirect-sentinel">open</a>',
}
_SCRIPT_POPUP_TIERS = ["4-playwright_stealth", "4a-patchright"]
_POPUP_HELPER_PATHS = frozenset({"/slow-pixel", "/redirect-popup-target"})
_FRAME_AND_POPUP_PAGES = {
    **_SUB_FRAME_PAGES,
    **_POPUP_PAGES,
    **_POPUP_ALLOWED_PAGES,
    **_POPUP_LINK_PAGES,
    "/popup-target": _POPUP_TARGET_BODY,
}
_SUB_FRAME_NAVIGATES_TOP_PAGE = '<iframe src="/frame-body-top-nav"></iframe>'
_FRAME_BODIES = {
    "/frame-body-script-nav": "<script>window.location='{sentinel}/';</script>",
    "/frame-body-top-nav": "<script>window.top.location='{sentinel}/';</script>",
}


_PRIVATE_HTTPS_HOP = "https://169.254.169.254/"
_ENGINES = ["playwright", "patchright", "camoufox"]


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"
    sentinel_port = 0
    requested_paths: ClassVar[list[str]] = []

    def log_message(self, *args: object) -> None:
        pass

    def _sentinel_address(self) -> str:
        return f"http://127.0.0.1:{type(self).sentinel_port}"

    def _send_html(self, inner: str) -> None:
        body = (
            "<html><head><title>Frames</title></head><body><article><p>"
            + _CANARY
            + "</p>"
            + inner.format(sentinel=self._sentinel_address())
            + "</article></body></html>"
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_popup_helper(self) -> None:
        if self.path == "/slow-pixel":
            time.sleep(_SLOW_PIXEL_SECONDS)
            self.send_response(204)
        else:
            self.send_response(302)
            self.send_header("Location", "/popup-target")
        self.end_headers()

    def do_GET(self) -> None:
        type(self).requested_paths.append(self.path)
        if self.path in _FRAME_AND_POPUP_PAGES:
            self._send_html(_FRAME_AND_POPUP_PAGES[self.path])

            return
        if self.path in _POPUP_HELPER_PATHS:
            self._send_popup_helper()

            return
        if self.path == "/frame-navigates-top":
            self._send_html(_SUB_FRAME_NAVIGATES_TOP_PAGE)

            return
        if self.path in _FRAME_BODIES:
            self._send_html(_FRAME_BODIES[self.path])

            return
        if self.path == "/redirect-sentinel":
            self.send_response(302)
            self.send_header("Location", f"{self._sentinel_address()}/")
            self.end_headers()

            return
        if self.path == "/redirect-private-https":
            self.send_response(302)
            self.send_header("Location", _PRIVATE_HTTPS_HOP)
            self.end_headers()

            return
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


def _self_signed_context(folder: Path) -> ssl.SSLContext:
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    now = datetime.now(UTC)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=1))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost")]), critical=False)
        .sign(key, hashes.SHA256())
    )
    chain = folder / "chain.pem"
    chain.write_bytes(
        certificate.public_bytes(serialization.Encoding.PEM)
        + key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(chain)

    return context


@pytest.fixture(scope="module")
def tls_server(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    context = _self_signed_context(tmp_path_factory.mktemp("tls"))
    server.socket = context.wrap_socket(server.socket, server_side=True, do_handshake_on_connect=False)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"https://localhost:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


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


def _redirect_hits() -> int:
    return _Handler.requested_paths.count("/redirect-private")


@pytest.mark.asyncio
@pytest.mark.parametrize("tier", ["1-beautifulsoup", "2-trafilatura", *_PARAM_TIERS])
async def test_refused_redirect_reaches_the_site_once_per_read(tier: str, web_server: str) -> None:
    # given
    hits_before = _redirect_hits()

    # when
    with pytest.raises(UnsafeUriError):
        await _read(web_server, "/redirect-private", tier)

    # then
    assert _redirect_hits() - hits_before == 1


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
@pytest.mark.parametrize("tier", _PARAM_TIERS)
@pytest.mark.parametrize("path", sorted(_SUB_FRAME_PAGES))
async def test_refused_sub_frame_navigation_does_not_fail_the_read(
    tier: str, path: str, web_server: str, sentinel: tuple[int, list[str]]
) -> None:
    # given
    _, seen = sentinel

    # when
    result = await _read(web_server, path, tier)

    # then
    assert result["status"] == "success"
    assert _CANARY in result["content"]
    assert seen == []


@pytest.mark.asyncio
@pytest.mark.parametrize("tier", _PARAM_TIERS)
@pytest.mark.parametrize("path", sorted(_POPUP_PAGES))
async def test_refused_popup_navigation_does_not_fail_the_read(
    tier: str, path: str, web_server: str, sentinel: tuple[int, list[str]]
) -> None:
    # given
    _, seen = sentinel

    # when
    result = await _read(web_server, path, tier)

    # then
    assert result["status"] == "success"
    assert _CANARY in result["content"]
    assert seen == []


def _popup_loads() -> int:
    return _Handler.requested_paths.count(_POPUP_LOADED_PATH)


@pytest.mark.asyncio
@pytest.mark.parametrize("tier", _SCRIPT_POPUP_TIERS)
@pytest.mark.parametrize("path", sorted(_POPUP_ALLOWED_PAGES))
async def test_popup_opened_straight_to_an_allowed_address_loads(
    tier: str, path: str, web_server: str
) -> None:
    # given
    loads_before = _popup_loads()

    # when
    result = await _read(web_server, path, tier)

    # then
    assert result["status"] == "success"
    assert _popup_loads() > loads_before


async def _click_popup_link_in_camoufox(
    base: str, path: str, *, refused_url: str | None = None
) -> tuple[str, list[str]]:
    launch = cast("Callable[..., Any]", AsyncCamoufox)
    async with launch(**_launch_kwargs()) as browser:
        context = await browser.new_context()
        refused = await install_browser_guard(context, shared_url_validator, family=BrowserFamily.FIREFOX)
        page = await context.new_page()
        await guarded_goto(page, f"{base}{path}", wait_until="load")
        if refused_url is None:
            async with page.expect_popup() as popup_info:
                await page.click("#open")
            popup = await popup_info.value
            await popup.wait_for_load_state("load")
        else:
            async with context.expect_event("requestfailed", lambda request: request.url == refused_url):
                await page.click("#open")
        content = await page.content()
        await context.close()

    return content, refused


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/popup-link-allowed", "/popup-link-allowed-redirect"])
async def test_camoufox_popup_opened_by_a_click_on_an_allowed_address_loads(
    path: str, web_server: str
) -> None:
    # given
    loads_before = _popup_loads()

    # when
    content, refused = await _click_popup_link_in_camoufox(web_server, path)

    # then
    assert _CANARY in content
    assert refused == []
    assert _popup_loads() > loads_before


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/popup-link-private", "/popup-link-redirect-private"])
async def test_camoufox_popup_opened_by_a_click_on_a_private_address_is_refused_by_the_guard(
    path: str, web_server: str, sentinel: tuple[int, list[str]], caplog: pytest.LogCaptureFixture
) -> None:
    # given
    port, seen = sentinel

    # when
    with caplog.at_level(logging.WARNING, logger="src.reader.browser_guard"):
        content, refused = await _click_popup_link_in_camoufox(
            web_server, path, refused_url=f"http://127.0.0.1:{port}/"
        )

    # then
    assert _CANARY in content
    assert refused == []
    assert seen == []
    assert f"refusing http://127.0.0.1:{port}/" in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("tier", _SCRIPT_POPUP_TIERS)
async def test_popup_whose_first_navigation_redirects_to_a_private_address_is_refused_by_the_guard(
    tier: str, web_server: str, sentinel: tuple[int, list[str]], caplog: pytest.LogCaptureFixture
) -> None:
    # given
    port, seen = sentinel

    # when
    with caplog.at_level(logging.WARNING, logger="src.reader.browser_guard"):
        result = await _read(web_server, "/popup-redirect-private", tier)

    # then
    assert result["status"] == "success"
    assert _CANARY in result["content"]
    assert seen == []
    assert f"refusing http://127.0.0.1:{port}/" in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("tier", _SCRIPT_POPUP_TIERS)
async def test_popup_opened_straight_to_a_private_address_is_refused_by_the_guard(
    tier: str, web_server: str, sentinel: tuple[int, list[str]], caplog: pytest.LogCaptureFixture
) -> None:
    # given
    port, seen = sentinel

    # when
    with caplog.at_level(logging.WARNING, logger="src.reader.browser_guard"):
        result = await _read(web_server, "/popup-private", tier)

    # then
    assert result["status"] == "success"
    assert _CANARY in result["content"]
    assert seen == []
    assert f"refusing http://127.0.0.1:{port}/" in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("tier", _PARAM_TIERS)
async def test_sub_frame_navigating_the_main_frame_to_private_answers_unsafe_uri(
    tier: str, web_server: str, sentinel: tuple[int, list[str]]
) -> None:
    # given
    _, seen = sentinel

    # when / then
    with pytest.raises(UnsafeUriError):
        await _read(web_server, "/frame-navigates-top", tier)
    assert seen == []


@pytest.mark.asyncio
async def test_crawlee_tier_covers_all_pages(web_server: str, sentinel: tuple[int, list[str]]) -> None:
    """Every page sequentially through `5-crawlee_adaptive`.

    Crawlee keeps process-global loop-bound state across `crawler.run` calls
    that a new pytest test on a fresh event loop cannot reuse, so unlike the
    other browser tiers its pages run back to back inside one test instead of
    one test per page.
    """
    # given
    _, seen = sentinel

    hits_before = _redirect_hits()

    # when / then: redirect to a private address is refused before any connection
    with pytest.raises(UnsafeUriError):
        await _read(web_server, "/redirect-private", "5-crawlee_adaptive")

    # then: the refused navigation reached the site once, with no crawlee retry
    assert _redirect_hits() - hits_before == 1

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

    # when / then: a refused sub-frame navigation leaves the read intact and reaches no listener
    for path in sorted(_SUB_FRAME_PAGES):
        framed = await _read(web_server, path, "5-crawlee_adaptive")
        assert framed["status"] == "success"
        assert _CANARY in framed["content"]
    assert seen == []

    # when / then: a refused popup navigation leaves the read intact and reaches no listener
    for path in sorted(_POPUP_PAGES):
        popped = await _read(web_server, path, "5-crawlee_adaptive")
        assert popped["status"] == "success"
        assert _CANARY in popped["content"]
    assert seen == []

    # when / then: a popup opened straight to an allowed address loads, directly and after a redirect
    for path in sorted(_POPUP_ALLOWED_PAGES):
        loads_before = _popup_loads()
        await _read(web_server, path, "5-crawlee_adaptive")
        assert _popup_loads() > loads_before

    # when / then: a sub-frame sending the main frame to a private address is refused
    with pytest.raises(UnsafeUriError):
        await _read(web_server, "/frame-navigates-top", "5-crawlee_adaptive")
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

    no_guard_installs: list[Any] = []

    async def _no_guard(context: Any, validator: Any, *, family: Any) -> list[str]:
        async def _pass(route: Any) -> None:
            await route.continue_()

        no_guard_installs.append(family)
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
    assert no_guard_installs == [BrowserFamily.CHROMIUM]
    logger.info(
        "browser_guard read time: guarded=%.0fms unguarded=%.0fms url=%s", guarded_ms, unguarded_ms, url
    )


def test_tier_names_cover_every_browser_tier() -> None:
    # when / then
    for tier in _BROWSER_TIERS:
        assert tier in TIER_ORDER


_CHECKED_ADDRESS = "127.0.0.2"
_REBOUND_ADDRESS = "127.0.0.1"
_SERVER_BIND_ATTEMPTS = 20


def _labelled_handler(label: str, requested: list[str]) -> type[BaseHTTPRequestHandler]:
    class _Labelled(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.0"

        def log_message(self, *args: object) -> None:
            pass

        def _answer(self, content_type: str, body: bytes) -> None:
            if "gzip" in self.headers.get("Accept-Encoding", ""):
                body = gzip.compress(body)
                self.send_response(200)
                self.send_header("Content-Encoding", "gzip")
            else:
                self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            requested.append(self.path)
            if self.path == "/rebind":
                self.send_response(302)
                self.send_header("Location", "/rebind-page")
                self.send_header("Set-Cookie", "hop=from-redirect; Path=/")
                self.end_headers()

                return
            if self.path == "/rebind-data":
                self._answer("text/plain", f"The {label} server answered the script.".encode())

                return
            cookie = self.headers.get("Cookie", "none")
            body = (
                "<html><head><title>Rebind</title></head><body><article><p>"
                + _CANARY
                + f"</p><p>The {label} server answered the page with cookie {cookie}.</p>"
                + "<script>fetch('/rebind-data').then(r => r.text()).then(t => {"
                + "const p = document.createElement('p'); p.textContent = t;"
                + "document.querySelector('article').appendChild(p); });</script>"
                + "</article></body></html>"
            ).encode()
            self._answer("text/html", body)

    return _Labelled


@pytest.fixture
def rebinding_sites() -> Iterator[tuple[int, list[str], list[str]]]:
    """Two sites on one port: the checked one on 127.0.0.2, the rebound one on 127.0.0.1."""
    checked_paths: list[str] = []
    rebound_paths: list[str] = []
    for _ in range(_SERVER_BIND_ATTEMPTS):
        checked = ThreadingHTTPServer((_CHECKED_ADDRESS, 0), _labelled_handler("checked", checked_paths))
        port = checked.server_address[1]
        try:
            rebound = ThreadingHTTPServer(
                (_REBOUND_ADDRESS, port), _labelled_handler("rebound", rebound_paths)
            )
        except OSError:
            checked.server_close()
            continue
        break
    else:
        pytest.fail("no port is free on both loopback addresses")
    servers = (checked, rebound)
    for server in servers:
        threading.Thread(target=server.serve_forever, daemon=True).start()
    yield port, checked_paths, rebound_paths
    for server in servers:
        server.shutdown()
        server.server_close()


@pytest.fixture
def localhost_checks_as_public(monkeypatch: pytest.MonkeyPatch) -> None:
    """The guard's own lookup answers `localhost` with 127.0.0.2, which stands for a public
    address, while every other resolver on this machine still answers 127.0.0.1."""
    from ascend_python_common import uri_guard

    real_lookup = uri_guard._lookup
    real_is_blocked = uri_guard._is_blocked

    async def _checked_lookup(host: str, port: int) -> Any:
        if host == "localhost":
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (_CHECKED_ADDRESS, port))]

        return await real_lookup(host, port)

    def _is_blocked(address: Any) -> bool:
        return str(address) != _CHECKED_ADDRESS and real_is_blocked(address)

    monkeypatch.setattr("src.config.config.settings.ALLOWED_PRIVATE_HOSTS", ())
    monkeypatch.setattr(uri_guard, "_lookup", _checked_lookup)
    monkeypatch.setattr(uri_guard, "_is_blocked", _is_blocked)


@pytest.mark.asyncio
@pytest.mark.parametrize("tier", _BROWSER_TIERS)
async def test_name_rebound_to_a_private_address_is_still_read_from_the_checked_address(
    tier: str, rebinding_sites: tuple[int, list[str], list[str]], localhost_checks_as_public: None
) -> None:
    # given
    port, checked_paths, rebound_paths = rebinding_sites

    # when
    result = await _read(f"http://localhost:{port}", "/rebind", tier)

    # then
    assert result["status"] == "success"
    assert "The checked server answered the page with cookie hop=from-redirect." in result["content"]
    assert "The checked server answered the script." in result["content"]
    assert "rebound" not in result["content"]
    assert checked_paths[:2] == ["/rebind", "/rebind-page"]
    assert "/rebind-data" in checked_paths
    assert rebound_paths == []


_ENGINE_ERRORS: dict[str, type[Exception]] = {
    "playwright": PlaywrightError,
    "patchright": PatchrightError,
    "camoufox": PlaywrightError,
}


@pytest.mark.parametrize("engine", _ENGINES)
async def test_https_redirect_to_a_private_address_is_a_connect_403_that_ends_as_unsafe_uri(
    engine: str, tls_server: str
) -> None:
    # given
    failed: list[str] = []
    answered: list[str] = []

    async with _launched(engine) as (browser, family):
        context = await browser.new_context(service_workers="block", ignore_https_errors=True)
        refused = await install_browser_guard(context, shared_url_validator, family=family)
        context.on("requestfailed", lambda request: failed.append(request.url))
        context.on("response", lambda response: answered.append(response.url))
        page = await context.new_page()

        # when / then
        with pytest.raises(UnsafeUriError, match=r"169\.254\.169\.254"):
            await render_and_judge(
                page,
                f"{tls_server}/redirect-private-https",
                MainFrameResponses(page),
                refused,
                tier="tls",
                error_type=_ENGINE_ERRORS[engine],
                producer="tls",
                profile=None,
            )
        await context.close()

    assert _PRIVATE_HTTPS_HOP in failed
    assert _PRIVATE_HTTPS_HOP not in answered
    assert browser_tunnel.was_refused(_PRIVATE_HTTPS_HOP)


class _CustomerProxy:
    """A forward proxy that records each CONNECT and carries it to the local address the name stands for."""

    def __init__(self) -> None:
        self.connects: list[str] = []
        self._server: asyncio.Server | None = None
        self._relays: set[asyncio.Task[None]] = set()

    async def start(self) -> str:
        self._server = await asyncio.start_server(self._serve, "127.0.0.1", 0)

        return f"http://127.0.0.1:{self._server.sockets[0].getsockname()[1]}"

    async def stop(self) -> None:
        assert self._server is not None
        self._server.close()
        for relay in list(self._relays):
            relay.cancel()
        await asyncio.gather(*self._relays, return_exceptions=True)
        await self._server.wait_closed()

    async def _serve(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        task = asyncio.current_task()
        assert task is not None
        self._relays.add(task)
        try:
            head = await reader.readuntil(b"\r\n\r\n")
            authority = head.split(b" ", 2)[1].decode()
            self.connects.append(authority)
            site_reader, site_writer = await asyncio.open_connection(
                "127.0.0.1", int(authority.rsplit(":", 1)[1])
            )
            writer.write(b"HTTP/1.1 200 OK\r\n\r\n")
            await writer.drain()
            await asyncio.gather(self._copy(reader, site_writer), self._copy(site_reader, writer))
        except (OSError, asyncio.IncompleteReadError):
            pass
        finally:
            self._relays.discard(task)
            writer.close()

    @staticmethod
    async def _copy(source: asyncio.StreamReader, target: asyncio.StreamWriter) -> None:
        try:
            while chunk := await source.read(65536):
                target.write(chunk)
                await target.drain()
        finally:
            target.close()


@pytest.fixture
async def customer_proxy(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[tuple[_CustomerProxy, str]]:
    proxy = _CustomerProxy()
    proxy_url = await proxy.start()
    await browser_tunnel.stop()
    monkeypatch.setattr(settings, "PROXY_URL", proxy_url)
    await browser_tunnel.start()
    yield proxy, proxy_url
    await proxy.stop()


@pytest.mark.parametrize("engine", _ENGINES)
async def test_a_chained_proxy_read_reaches_the_site_through_the_customer_proxy(
    engine: str, tls_server: str, customer_proxy: tuple[_CustomerProxy, str]
) -> None:
    # given
    proxy, proxy_url = customer_proxy
    authority = tls_server.removeprefix("https://")

    # when
    async with _launched(engine) as (browser, family):
        context = await browser.new_context(
            service_workers="block",
            ignore_https_errors=True,
            proxy=browser_tunnel.chained_proxy({"server": proxy_url}),
        )
        refused = await install_browser_guard(context, shared_url_validator, family=family)
        page = await context.new_page()
        html = await render_and_judge(
            page,
            f"{tls_server}/plain",
            MainFrameResponses(page),
            refused,
            tier="tls",
            error_type=_ENGINE_ERRORS[engine],
            producer="tls",
            profile=None,
        )
        await context.close()

    # then
    assert _CANARY in str(html)
    assert authority in proxy.connects

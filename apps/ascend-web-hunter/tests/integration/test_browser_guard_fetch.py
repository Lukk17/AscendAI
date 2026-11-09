"""Live-browser behaviour of a guarded browser behind the pinned tunnel (security fix 19 follow-up).

Two sites, `a.test` on 127.0.0.2 and `www.b.test` on 127.0.0.3, stand for two
public hosts: the guard's own lookup answers them and every request reaches
them only through the pinned tunnel, because no other resolver knows the names.

The redirect tests drive each browser engine the tiers launch (Playwright
Chromium, Patchright Chromium, Camoufox Firefox) through a cross-host redirect
chain and a form post, and check what a page sees: its address, its relative
links and subresources, the cookies every hop set, the latest main-frame
response, the history, and the method a 303 and a 307 continue with. The tier
test reads the same chain through every browser tier, Crawlee included.

The last test loads a page with fifty images on one host.

Not part of the unit gate: excluded through `--ignore=tests/integration` in
`pyproject.toml`, run alone as `python -m pytest tests/integration -q --no-cov`.
"""

import socket
import threading
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from email.message import Message
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import pytest

from src.reader.browser_guard import BrowserFamily, guarded_goto, install_browser_guard
from src.reader.strategies.main_frame_response import MainFrameResponses
from src.reader.web_reader import WebReader
from src.validator.url_validator import url_validator

pytestmark = pytest.mark.filterwarnings("ignore:Implicitly cleaning up:ResourceWarning")

_A_HOST = "a.test"
_B_HOST = "www.b.test"
_A_ADDRESS = "127.0.0.2"
_B_ADDRESS = "127.0.0.3"
_SUBRESOURCES = 50
_ENGINES = ["playwright", "patchright", "camoufox"]
_CHROMIUM_ENGINES = ["playwright", "patchright"]
_SAVED_COOKIE_PAIR = "saved=fixture-value"
_SAVED_STATE = {
    "cookies": [
        {
            "name": "saved",
            "value": "fixture-value",
            "domain": _A_HOST,
            "path": "/",
            "expires": -1,
            "httpOnly": False,
            "secure": False,
            "sameSite": "Lax",
        }
    ],
    "origins": [],
}
_BROWSER_TIERS = ["4-playwright_stealth", "4a-patchright", "4b-camoufox", "5-crawlee_adaptive"]
_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
    "1f15c4890000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082"
)
_CANARY = "The HERON-LANTERN census counted 31 wading birds along the reed beds of Lake Ostra on May 2nd."


@dataclass
class _Site:
    port: int = 0
    other: str = ""
    requests: list[tuple[str, str, bytes, Message]] = field(default_factory=list)
    connections: list[str] = field(default_factory=list)

    @property
    def paths(self) -> list[str]:
        return [path for _, path, _, _ in self.requests]

    @property
    def calls(self) -> list[tuple[str, str, bytes]]:
        return [(method, path, body) for method, path, body, _ in self.requests]

    def cookies_sent(self) -> list[str]:
        return [headers.get("Cookie", "") for _, _, _, headers in self.requests]

    def header_names_sent(self) -> set[str]:
        return {name.lower() for _, _, _, headers in self.requests for name in headers}


def _site_handler(site: _Site, host: str) -> type[BaseHTTPRequestHandler]:
    class _Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args: object) -> None:
            pass

        def setup(self) -> None:
            super().setup()
            site.connections.append(host)

        def _send(
            self,
            status: int,
            body: bytes = b"",
            headers: tuple[tuple[str, str], ...] = (),
            content_type: str = "text/html",
        ) -> None:
            self.send_response(status)
            for name, value in headers:
                self.send_header(name, value)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _html(self, inner: str, headers: tuple[tuple[str, str], ...] = ()) -> None:
            page = f"<html><head><title>Guard</title></head><body><article>{inner}</article></body></html>"
            self._send(200, page.encode(), headers)

        def do_GET(self) -> None:
            site.requests.append(("GET", self.path, b"", self.headers))
            match self.path:
                case "/start":
                    self._send(
                        302, headers=(("Location", f"{site.other}/x"), ("Set-Cookie", "ahop=1; Path=/"))
                    )
                case "/x":
                    self._send(
                        302, headers=(("Location", "/final"), ("Set-Cookie", "bhop=2; Domain=b.test; Path=/"))
                    )
                case "/final":
                    self._html(
                        f"<p>{_CANARY}</p><p id='loc'></p>"
                        "<a id='rel' href='next'>next</a><img src='pic.png'>"
                        "<script>document.getElementById('loc').textContent ="
                        " 'located at ' + document.location.href;</script>",
                        headers=(("Set-Cookie", "final=3; Path=/"), ("X-Hop", "final")),
                    )
                case "/pic.png" | "/next":
                    self._send(200, _PNG, content_type="image/png")
                case "/form":
                    self._html(
                        "<form id='see-other' method='post' action='/submit'>"
                        "<input name='field' value='hello'></form>"
                        "<form id='temporary' method='post' action='/submit307'>"
                        "<input name='field' value='kept'></form>"
                    )
                case "/after":
                    self._html(f"<p>{_CANARY}</p><p>after</p>")
                case "/many":
                    images = "".join(f"<img src='/img/{n}.png'>" for n in range(_SUBRESOURCES))
                    self._html(f"<p>{_CANARY}</p>{images}")
                case path if path.startswith("/img/"):
                    self._send(200, _PNG, content_type="image/png")
                case _:
                    self._send(404)

        def do_POST(self) -> None:
            body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            site.requests.append(("POST", self.path, body, self.headers))
            match self.path:
                case "/submit":
                    self._send(303, headers=(("Location", f"{site.other}/after"),))
                case "/submit307":
                    self._send(307, headers=(("Location", f"{site.other}/echo"),))
                case "/echo":
                    self._html(f"<p>{_CANARY}</p><p>echo {body.decode()}</p>")
                case _:
                    self._send(404)

    return _Handler


@pytest.fixture
def sites(monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[_Site, _Site]]:
    """`a.test` and `www.b.test` on their own loopback addresses, answered by the guard's lookup only."""
    from ascend_python_common import uri_guard

    a_site, b_site = _Site(), _Site()
    servers = [
        ThreadingHTTPServer((_A_ADDRESS, 0), _site_handler(a_site, _A_HOST)),
        ThreadingHTTPServer((_B_ADDRESS, 0), _site_handler(b_site, _B_HOST)),
    ]
    a_site.port, b_site.port = (server.server_address[1] for server in servers)
    a_site.other = f"http://{_B_HOST}:{b_site.port}"
    b_site.other = f"http://{_A_HOST}:{a_site.port}"
    addresses = {_A_HOST: _A_ADDRESS, _B_HOST: _B_ADDRESS}
    real_lookup = uri_guard._lookup
    real_is_blocked = uri_guard._is_blocked

    async def _lookup(host: str, port: int) -> Any:
        if host in addresses:
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (addresses[host], port))]

        return await real_lookup(host, port)

    def _is_blocked(address: Any) -> bool:
        return str(address) not in addresses.values() and real_is_blocked(address)

    monkeypatch.setattr("src.config.config.settings.ALLOWED_PRIVATE_HOSTS", ())
    monkeypatch.setattr("src.reader.web_reader.settings.PLAYWRIGHT_HEADLESS", True)
    monkeypatch.setattr(uri_guard, "_lookup", _lookup)
    monkeypatch.setattr(uri_guard, "_is_blocked", _is_blocked)
    for server in servers:
        threading.Thread(target=server.serve_forever, daemon=True).start()
    yield a_site, b_site
    for server in servers:
        server.shutdown()
        server.server_close()


@asynccontextmanager
async def _guarded_page(engine: str, storage_state: dict[str, Any] | None = None) -> AsyncIterator[Any]:
    """A page of *engine* launched the way its tier launches it, with the guard installed."""
    async with _launched(engine) as (browser, family):
        context = await browser.new_context(service_workers="block", storage_state=storage_state)
        await install_browser_guard(context, url_validator, family=family)
        try:
            yield await context.new_page()
        finally:
            await context.close()


@asynccontextmanager
async def _launched(engine: str) -> AsyncIterator[tuple[Any, BrowserFamily]]:
    if engine == "playwright":
        from src.runtime.browser_pool import browser_pool

        yield await browser_pool.get_browser(), BrowserFamily.CHROMIUM
    elif engine == "patchright":
        from src.reader.strategies.patchright_strategy import PatchrightStrategy

        async with PatchrightStrategy(lambda: "ua", url_validator)._launched_browser() as browser:
            yield browser, BrowserFamily.CHROMIUM
    else:
        from camoufox.async_api import AsyncCamoufox

        from src.reader.strategies.camoufox_strategy import _launch_kwargs

        launcher: Any = AsyncCamoufox
        async with launcher(**_launch_kwargs()) as browser:
            yield browser, BrowserFamily.FIREFOX


def _url(site: _Site, host: str, path: str) -> str:
    return f"http://{host}:{site.port}{path}"


@pytest.mark.asyncio
@pytest.mark.parametrize("engine", _ENGINES)
async def test_cross_host_redirect_shows_the_final_address(engine: str, sites: tuple[_Site, _Site]) -> None:
    # given
    a_site, b_site = sites
    final = _url(b_site, _B_HOST, "/final")

    # when
    async with _guarded_page(engine) as page:
        response = await guarded_goto(page, _url(a_site, _A_HOST, "/start"), wait_until="load")
        location = await page.evaluate("document.location.href")
        page_url = page.url

    # then
    assert response is not None
    assert (page_url, location, response.url, response.status) == (final, final, final, 200)


@pytest.mark.asyncio
@pytest.mark.parametrize("engine", _CHROMIUM_ENGINES)
async def test_saved_cookie_reaches_its_own_site_and_not_the_redirect_target(
    engine: str, sites: tuple[_Site, _Site]
) -> None:
    # given
    a_site, b_site = sites

    # when
    async with _guarded_page(engine, _SAVED_STATE) as page:
        await guarded_goto(page, _url(a_site, _A_HOST, "/start"), wait_until="load")

    # then
    assert _SAVED_COOKIE_PAIR in a_site.cookies_sent()[0]
    assert not any("saved=" in cookie for cookie in b_site.cookies_sent())


@pytest.mark.asyncio
@pytest.mark.parametrize("engine", _CHROMIUM_ENGINES)
async def test_both_sites_receive_the_cache_headers_while_the_guard_route_is_installed(
    engine: str, sites: tuple[_Site, _Site]
) -> None:
    # given
    a_site, b_site = sites

    # when
    async with _guarded_page(engine, _SAVED_STATE) as page:
        await guarded_goto(page, _url(a_site, _A_HOST, "/start"), wait_until="load")

    # then
    assert {"pragma", "cache-control"} <= a_site.header_names_sent()
    assert {"pragma", "cache-control"} <= b_site.header_names_sent()


@pytest.mark.asyncio
@pytest.mark.parametrize("engine", _ENGINES)
async def test_relative_link_and_subresource_resolve_against_the_final_address(
    engine: str, sites: tuple[_Site, _Site]
) -> None:
    # given
    a_site, b_site = sites

    # when
    async with _guarded_page(engine) as page:
        await guarded_goto(page, _url(a_site, _A_HOST, "/start"), wait_until="load")
        link = await page.evaluate("document.getElementById('rel').href")

    # then
    assert link == _url(b_site, _B_HOST, "/next")
    assert "/pic.png" in b_site.paths
    assert "/pic.png" not in a_site.paths


@pytest.mark.asyncio
@pytest.mark.parametrize("engine", _ENGINES)
async def test_every_hop_sets_its_cookie_for_its_own_domain(engine: str, sites: tuple[_Site, _Site]) -> None:
    # given
    a_site, _ = sites

    # when
    async with _guarded_page(engine) as page:
        await guarded_goto(page, _url(a_site, _A_HOST, "/start"), wait_until="load")
        cookies = {cookie["name"]: cookie["domain"] for cookie in await page.context.cookies()}

    # then
    assert cookies == {"ahop": _A_HOST, "bhop": ".b.test", "final": _B_HOST}


@pytest.mark.asyncio
@pytest.mark.parametrize("engine", _ENGINES)
async def test_latest_main_frame_response_is_the_final_answer(
    engine: str, sites: tuple[_Site, _Site]
) -> None:
    # given
    a_site, _ = sites

    # when
    async with _guarded_page(engine) as page:
        responses = MainFrameResponses(page)
        responses.seed(await guarded_goto(page, _url(a_site, _A_HOST, "/start"), wait_until="load"))
        status, headers = await responses.status_and_headers()

    # then
    assert (status, headers.get("x-hop")) == (200, "final")


@pytest.mark.asyncio
@pytest.mark.parametrize("engine", _ENGINES)
async def test_form_post_answered_with_303_continues_as_a_get(
    engine: str, sites: tuple[_Site, _Site]
) -> None:
    # given
    a_site, b_site = sites
    after = _url(b_site, _B_HOST, "/after")

    # when
    async with _guarded_page(engine) as page:
        await guarded_goto(page, _url(a_site, _A_HOST, "/form"), wait_until="load")
        history_before = await page.evaluate("history.length")
        async with page.expect_event("framenavigated", predicate=lambda frame: frame.url == after):
            await page.evaluate("document.getElementById('see-other').submit()")
        await page.wait_for_load_state("load")
        history_length = await page.evaluate("history.length")
        await page.go_back(wait_until="load")
        back_url = page.url

    # then
    assert ("POST", "/submit", b"field=hello") in a_site.calls
    assert ("GET", "/after", b"") in b_site.calls
    assert (history_length - history_before, back_url) == (1, _url(a_site, _A_HOST, "/form"))


@pytest.mark.asyncio
@pytest.mark.parametrize("engine", _ENGINES)
async def test_form_post_answered_with_307_keeps_the_post(engine: str, sites: tuple[_Site, _Site]) -> None:
    # given
    a_site, b_site = sites
    echo = _url(b_site, _B_HOST, "/echo")

    # when
    async with _guarded_page(engine) as page:
        await guarded_goto(page, _url(a_site, _A_HOST, "/form"), wait_until="load")
        async with page.expect_event("framenavigated", predicate=lambda frame: frame.url == echo):
            await page.evaluate("document.getElementById('temporary').submit()")
        await page.wait_for_load_state("load")
        text = await page.inner_text("article")

    # then
    assert ("POST", "/echo", b"field=kept") in b_site.calls
    assert "echo field=kept" in text


@pytest.mark.asyncio
@pytest.mark.parametrize("tier", _BROWSER_TIERS)
async def test_tier_reads_a_cross_host_redirect_at_the_final_address(
    tier: str, sites: tuple[_Site, _Site]
) -> None:
    # given
    a_site, b_site = sites

    # when
    result = await WebReader().read(_url(a_site, _A_HOST, "/start"), tier=tier)  # type: ignore[arg-type]

    # then
    assert f"located at {_url(b_site, _B_HOST, '/final')}" in result["content"]


@pytest.mark.asyncio
@pytest.mark.parametrize("engine", _ENGINES)
async def test_fifty_images_on_one_host_all_load(engine: str, sites: tuple[_Site, _Site]) -> None:
    # given
    a_site, _ = sites

    # when
    async with _guarded_page(engine) as page:
        await guarded_goto(page, _url(a_site, _A_HOST, "/many"), wait_until="load")
        loaded = await page.evaluate("[...document.images].filter(image => image.naturalWidth === 1).length")

    # then
    assert loaded == _SUBRESOURCES

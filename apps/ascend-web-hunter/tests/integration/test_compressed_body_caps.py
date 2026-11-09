"""Live capped fetches against a local server that answers a compressed bomb.

Real curl_cffi over a real socket. Peak memory is read with tracemalloc, which
sees the bytes objects curl_cffi queues from its write callback. Not part of
the unit gate: run alone as `python -m pytest tests/integration -q --no-cov`.
"""

import asyncio
import gzip
import logging
import threading
import time
import tracemalloc
import zlib
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import asynccontextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Final
from unittest.mock import AsyncMock, patch

import brotli
import pytest
import zstandard
from ascend_python_common.uri_guard import FetchPolicy, FetchTarget
from curl_cffi import requests
from playwright.async_api import Page, async_playwright

from src.api.exceptions import ChallengeDetectedException
from src.config.config import settings
from src.crawl.fetcher import ConditionalProbe, conditional_probe, fetch_robots_txt
from src.fetch.byte_fetch import DocumentTooLargeError, stream_to_file
from src.fetch.pinned_fetch import make_send_hop
from src.reader.browser_guard import chromium_guard_args
from src.reader.strategies.browser_read import PageTooLargeError, bounded_page_content
from src.reader.strategies.curl_cffi_fetcher import fetch_with_curl_cffi

_MIB: Final[int] = 1024 * 1024
_INFLATED_SIZE: Final[int] = 256 * _MIB
_CAP: Final[int] = 64 * 1024
_PEAK_LIMIT: Final[int] = _MIB
_BOMB: Final[bytes] = gzip.compress(b"\0" * _INFLATED_SIZE, compresslevel=9)
_ENCODERS: Final[dict[str, Callable[[bytes], bytes]]] = {
    "gzip": gzip.compress,
    "deflate": zlib.compress,
    "br": lambda data: brotli.compress(data, quality=5),
    "zstd": zstandard.ZstdCompressor().compress,
}
_PAST_CAP_PAGE: Final[str] = "<html><body>" + "x" * (_CAP * 4) + "</body></html>"
_NORMAL_PAGE: Final[str] = "<html><body>" + "zażółć gęślą jaźń " * 4000 + "</body></html>"
_LOCAL_POLICY: Final[FetchPolicy] = FetchPolicy(
    allowed_hosts=("127.0.0.1",), file_root=None, max_redirect_hops=2
)
_COOKIE_VALUE: Final[str] = "stored-login"
_SMALL_SITEMAP: Final[bytes] = b"<urlset><url><loc>https://example.com/a</loc></url></urlset>"
_GZIPPED_SITEMAP: Final[bytes] = gzip.compress(_SMALL_SITEMAP)
_DRIP_INTERVAL_SECONDS: Final[float] = 0.05
_DRIP_LIFETIME_SECONDS: Final[float] = 4.0
_SHORT_EXTRACT_TIMEOUT_SECONDS: Final[float] = 0.3
_DRIP_DEADLINE_SECONDS: Final[float] = 2.0
_CHALLENGE_PAGE: Final[bytes] = b"<html><body>Attention required</body></html>"
_ETAG: Final[str] = '"v1"'
_LAST_MODIFIED: Final[str] = "Sun, 01 Nov 2026 10:00:00 GMT"


class _BombHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"
    received: list[dict[str, str | None]] = []  # noqa: RUF012
    other_host: str = ""
    bombs: dict[str, bytes] = {}  # noqa: RUF012

    def log_message(self, *args: object) -> None:
        pass

    def do_GET(self) -> None:
        type(self).received.append(
            {
                "path": self.path,
                "cookie": self.headers.get("Cookie"),
                "accept-encoding": self.headers.get("Accept-Encoding"),
            }
        )
        if self.path == "/redirect-away":
            self.send_response(302)
            self.send_header("Location", f"{type(self).other_host}/landing")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if self.path == "/landing":
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", "13")
            self.end_headers()
            self.wfile.write(b"<html></html>")
            return
        if self.path == "/drip":
            self._drip()
            return
        if self.path == "/challenge":
            self.send_response(403)
            self.send_header("Content-Type", "text/html")
            self.send_header("cf-mitigated", "challenge")
            self.send_header("Set-Cookie", "__cf_bm=abc; Path=/")
            self.send_header("Content-Length", str(len(_CHALLENGE_PAGE)))
            self.end_headers()
            self.wfile.write(_CHALLENGE_PAGE)
            return
        if self.path == "/not-modified":
            self.send_response(304)
            self.send_header("ETag", _ETAG)
            self.send_header("Last-Modified", _LAST_MODIFIED)
            self.end_headers()
            return
        if self.path == "/inflates-past-cap":
            self._send_coded(gzip.compress(_PAST_CAP_PAGE.encode()), "gzip")
            return
        if self.path.startswith("/bomb/"):
            coding = self.path.removeprefix("/bomb/")
            self._send_coded(type(self).bombs[coding], coding)
            return
        if self.path.startswith("/page/"):
            coding = self.path.removeprefix("/page/")
            self._send_coded(_ENCODERS[coding](_NORMAL_PAGE.encode()), coding)
            return
        body = _GZIPPED_SITEMAP if self.path == "/gzipped-sitemap.xml" else _BOMB
        self.send_response(200)
        self.send_header("Content-Type", "application/xml")
        self.send_header("Content-Encoding", "gzip")
        self.end_headers()
        self.wfile.write(body)

    def _drip(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        ends_at = time.monotonic() + _DRIP_LIFETIME_SECONDS
        try:
            while time.monotonic() < ends_at:
                self.wfile.write(b"xx")
                self.wfile.flush()
                time.sleep(_DRIP_INTERVAL_SECONDS)
        except OSError:
            return

    def _send_coded(self, body: bytes, coding: str) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Encoding", coding)
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture(scope="module", autouse=True)
def coded_bombs() -> None:
    inflated = b"\0" * _INFLATED_SIZE
    _BombHandler.bombs.update({coding: encode(inflated) for coding, encode in _ENCODERS.items()})


@pytest.fixture(scope="module")
def bomb_server() -> Iterator[int]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _BombHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server.server_address[1]
    server.shutdown()
    server.server_close()


@pytest.fixture(scope="module")
def second_host_server() -> Iterator[int]:
    server = ThreadingHTTPServer(("127.0.0.2", 0), _BombHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server.server_address[1]
    server.shutdown()
    server.server_close()


@pytest.fixture(autouse=True)
def allow_the_local_server(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(settings, "ALLOWED_PRIVATE_HOSTS", ("127.0.0.1", "127.0.0.2"))
    _BombHandler.received.clear()
    with (
        patch(
            "src.reader.cloudflare.cookie_manager.cookie_manager.get_user_agent",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "src.reader.cloudflare.cookie_manager.cookie_manager.get_flat_cookies",
            new=AsyncMock(return_value={"sid": _COOKIE_VALUE}),
        ),
    ):
        yield


async def test_a_capped_read_of_a_gzip_bomb_keeps_peak_memory_near_the_cap(
    bomb_server: int, caplog: pytest.LogCaptureFixture
) -> None:
    # given every lazy import of the fetch path already loaded
    await fetch_with_curl_cffi(
        f"http://127.0.0.1:{bomb_server}/landing", lambda: "UA", "bomb-test", max_bytes=_CAP
    )
    tracemalloc.start()

    # when
    body = await fetch_with_curl_cffi(
        f"http://127.0.0.1:{bomb_server}/sitemap.xml", lambda: "UA", "bomb-test", max_bytes=_CAP
    )
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    # then the wire bytes pass the cap, the read stops, and the inflated bytes stay near the cap
    assert len(_BOMB) > _CAP
    assert body == ""
    assert "above the cap of" in caplog.text
    print(f"capped sitemap read peak: {peak} bytes")
    assert peak < _PEAK_LIMIT, f"peak {peak} bytes"


async def test_a_sitemap_the_server_gzips_reaches_the_unpack_step_inflated(bomb_server: int) -> None:
    # given a server that answers Content-Encoding gzip although the fetch asked for identity
    path = "/gzipped-sitemap.xml"

    # when
    body = await fetch_with_curl_cffi(
        f"http://127.0.0.1:{bomb_server}{path}",
        lambda: "UA",
        "sitemap-test",
        max_bytes=_CAP,
        unpack=lambda raw, _content_type: raw,
    )

    # then the Content-Encoding layer is undone and identity was asked for
    assert body == _SMALL_SITEMAP.decode()
    assert _BombHandler.received[-1]["accept-encoding"] == "identity"


async def test_a_robots_fetch_of_a_gzip_bomb_inflates_within_the_cap_and_the_memory_limit(
    bomb_server: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    # given every lazy import of the fetch path already loaded
    monkeypatch.setattr(settings, "CRAWL_ROBOTS_MAX_BYTES", _CAP)
    await fetch_robots_txt(f"http://127.0.0.1:{bomb_server}/landing", None)
    tracemalloc.start()

    # when
    answer = await fetch_robots_txt(f"http://127.0.0.1:{bomb_server}/robots.txt", None)
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    # then the file is cut at the cap, and a file with no line end keeps no line
    assert (answer.status, answer.body) == (200, "")
    assert _BombHandler.received[-1]["accept-encoding"] == "identity"
    print(f"robots.txt read peak: {peak} bytes")
    assert peak < _PEAK_LIMIT, f"peak {peak} bytes"


@pytest.mark.parametrize("coding", sorted(_ENCODERS))
async def test_a_normal_compressed_page_reads_with_the_impersonated_headers_unchanged(
    bomb_server: int, coding: str
) -> None:
    # when
    body = await fetch_with_curl_cffi(f"http://127.0.0.1:{bomb_server}/page/{coding}", lambda: "UA", "page")

    # then
    assert body == _NORMAL_PAGE
    assert _BombHandler.received[-1]["accept-encoding"] == "gzip, deflate, br"


@pytest.mark.parametrize("coding", sorted(_ENCODERS))
async def test_a_page_read_of_a_bomb_is_a_tier_failure_within_the_memory_limit(
    bomb_server: int, coding: str, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    # given every lazy import of the fetch path already loaded
    monkeypatch.setattr(settings, "READ_RESPONSE_MAX_BYTES", _CAP)
    await fetch_with_curl_cffi(f"http://127.0.0.1:{bomb_server}/page/{coding}", lambda: "UA", "page")
    tracemalloc.start()

    # when
    body = await fetch_with_curl_cffi(f"http://127.0.0.1:{bomb_server}/bomb/{coding}", lambda: "UA", "page")
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    # then
    assert body == ""
    assert "above the cap of" in caplog.text
    print(f"page read peak [{coding}]: {peak} bytes")
    assert peak < _PEAK_LIMIT, f"peak {peak} bytes"


@pytest.mark.parametrize("coding", sorted(_ENCODERS))
async def test_a_document_bomb_raises_too_large_within_the_memory_limit(
    bomb_server: int, coding: str
) -> None:
    # given every lazy import of the fetch path already loaded
    loaded = await stream_to_file(f"http://127.0.0.1:{bomb_server}/landing", _CAP, policy=_LOCAL_POLICY)
    assert loaded is not None
    loaded.unlink()
    tracemalloc.start()

    # when
    with pytest.raises(DocumentTooLargeError):
        await stream_to_file(f"http://127.0.0.1:{bomb_server}/bomb/{coding}", _CAP, policy=_LOCAL_POLICY)
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    # then
    print(f"document read peak [{coding}]: {peak} bytes")
    assert peak < _PEAK_LIMIT, f"peak {peak} bytes"


@asynccontextmanager
async def _page_through_the_tunnel() -> AsyncIterator[Page]:
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True, args=list(chromium_guard_args()))
        try:
            yield await (await browser.new_context(service_workers="block")).new_page()
        finally:
            await browser.close()


@pytest.mark.parametrize("coding", sorted(_ENCODERS))
async def test_a_browser_reads_a_normal_compressed_page_through_the_tunnel(
    bomb_server: int, coding: str
) -> None:
    # when
    async with _page_through_the_tunnel() as page:
        await page.goto(f"http://127.0.0.1:{bomb_server}/page/{coding}")
        text = await page.inner_text("body")

    # then
    assert text.split() == _NORMAL_PAGE.removeprefix("<html><body>").removesuffix("</body></html>").split()


async def test_a_page_that_inflates_above_the_cap_is_not_copied_out_of_the_browser(
    bomb_server: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    # given a compressed body far under the cap on the wire, whose markup is far above it
    monkeypatch.setattr(settings, "BROWSER_RESPONSE_MAX_BYTES", _CAP)

    async with _page_through_the_tunnel() as page:
        await page.goto(f"http://127.0.0.1:{bomb_server}/inflates-past-cap")

        # when / then
        with pytest.raises(PageTooLargeError):
            await bounded_page_content(page)


async def test_the_tunnel_ends_a_compressed_body_above_the_byte_cap_on_the_wire(
    bomb_server: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    # given
    monkeypatch.setattr(settings, "BROWSER_RESPONSE_MAX_BYTES", _CAP)

    # when
    async with _page_through_the_tunnel() as page:
        navigation = await asyncio.gather(
            page.goto(f"http://127.0.0.1:{bomb_server}/bomb/gzip", wait_until="load"), return_exceptions=True
        )
        rendered = len(await page.content())

    # then the browser saw a truncated body, far below what the whole body inflates to
    print(f"tunnel cut navigation: {navigation[0]!r}, rendered {rendered} characters")
    assert rendered < _INFLATED_SIZE / 2


async def test_the_second_host_of_a_redirect_receives_no_cookie_header_on_the_wire(
    bomb_server: int, second_host_server: int
) -> None:
    # given a first host with stored cookies that redirects to a second host
    _BombHandler.other_host = f"http://127.0.0.2:{second_host_server}"

    # when
    await fetch_with_curl_cffi(f"http://127.0.0.1:{bomb_server}/redirect-away", lambda: "UA", "cookie-test")

    # then
    assert [hop["path"] for hop in _BombHandler.received] == ["/redirect-away", "/landing"]
    assert _BombHandler.received[0]["cookie"] == f"sid={_COOKIE_VALUE}"
    assert _BombHandler.received[1]["cookie"] is None


async def test_a_refused_hop_on_the_same_host_sends_no_cookie_kept_in_the_session_jar(
    bomb_server: int,
) -> None:
    # given a first hop that puts the stored cookie in the jar, and a check that refuses the second
    verdicts = iter([True, False])
    url = f"http://127.0.0.1:{bomb_server}/landing"
    target = FetchTarget(url=url, host="127.0.0.1", port=bomb_server, addresses=("127.0.0.1",))

    # when
    async with requests.AsyncSession(impersonate="chrome120") as session:
        send_hop = make_send_hop(session, {}, {"sid": _COOKIE_VALUE}, 5.0, {}, lambda _url: next(verdicts))
        await send_hop(target)
        await send_hop(target)

    # then
    assert [hop["cookie"] for hop in _BombHandler.received] == [f"sid={_COOKIE_VALUE}", None]


async def test_a_body_that_drips_forever_is_a_failed_tier_at_the_extract_timeout(
    bomb_server: int, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    # given a server that sends two bytes at a time for far longer than the read may take
    monkeypatch.setattr(settings, "EXTRACT_TIMEOUT", _SHORT_EXTRACT_TIMEOUT_SECONDS)
    started = time.monotonic()

    # when
    with caplog.at_level(logging.WARNING):
        async with asyncio.timeout(_DRIP_LIFETIME_SECONDS + 2):
            body = await fetch_with_curl_cffi(f"http://127.0.0.1:{bomb_server}/drip", lambda: "UA", "drip")

    # then the tier failed long before the server stopped dripping
    assert body == ""
    assert time.monotonic() - started < _DRIP_DEADLINE_SECONDS
    assert "drip failed to fetch URL" in caplog.text


async def test_a_403_with_cf_mitigated_and_a_cookie_is_a_challenge_on_the_wire(bomb_server: int) -> None:
    # when
    with pytest.raises(ChallengeDetectedException) as caught:
        await fetch_with_curl_cffi(f"http://127.0.0.1:{bomb_server}/challenge", lambda: "UA", "challenge")

    # then the header and the status reached the verdict through the streamed answer
    signals = {signal.id for signal in caught.value.verdict.signals}
    assert "definitive_header" in signals
    assert caught.value.verdict.wall is True
    assert _BombHandler.received[-1]["path"] == "/challenge"


async def test_a_304_answers_its_validators_on_the_wire(bomb_server: int) -> None:
    # when
    probe = await conditional_probe(f"http://127.0.0.1:{bomb_server}/not-modified", etag=_ETAG)

    # then
    assert probe == ConditionalProbe(304, _ETAG, _LAST_MODIFIED)

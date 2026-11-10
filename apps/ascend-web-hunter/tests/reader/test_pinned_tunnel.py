"""The local forward proxy the browser tiers connect through.

Every test runs a real tunnel and real sockets on loopback. `127.0.0.2` stands
for a public address where a test needs one, with the guard's own address
check patched to accept it.
"""

import asyncio
import base64
import logging
import socket
import ssl
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import suppress
from typing import Any, Final
from unittest.mock import AsyncMock, patch

import pytest
from ascend_python_common import uri_guard
from ascend_python_common.uri_guard import FetchPolicy, FetchTarget, UnsafeUriError

from src.config.config import settings
from src.reader.pinned_tunnel import PinnedTunnel, TunnelNotStartedError

_POLICY: Final = FetchPolicy(allowed_hosts=("127.0.0.1",), file_root=None, max_redirect_hops=3)
_PUBLIC_STAND_IN: Final = "127.0.0.2"
_READ_TIMEOUT: Final = 5.0

_SiteHandler = Callable[[asyncio.StreamReader, asyncio.StreamWriter], Awaitable[None]]


async def _close(writer: asyncio.StreamWriter) -> None:
    if not writer.is_closing():
        writer.close()
    with suppress(OSError):
        await writer.wait_closed()


class _Site:
    """A loopback server that records what it received and runs a handler for each connection."""

    def __init__(self, handler: _SiteHandler) -> None:
        self._handler = handler
        self.connections = 0
        self.received = bytearray()
        self.port = 0
        self._server: asyncio.Server | None = None
        self._tasks: set[asyncio.Task[None]] = set()

    async def start(self, host: str = "127.0.0.1") -> "_Site":
        self._server = await asyncio.start_server(self._accept, host, self.port)
        self.port = self._server.sockets[0].getsockname()[1]

        return self

    async def _accept(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self.connections += 1
        task = asyncio.current_task()
        assert task is not None
        self._tasks.add(task)
        try:
            await self._handler(reader, writer)
        finally:
            self._tasks.discard(task)
            await _close(writer)

    async def stop(self) -> None:
        assert self._server is not None
        self._server.close()
        for task in list(self._tasks):
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        await self._server.wait_closed()


@pytest.fixture(autouse=True)
def short_timeouts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "BROWSER_TUNNEL_CONNECT_TIMEOUT_SECONDS", 1.0)
    monkeypatch.setattr(settings, "BROWSER_TUNNEL_IDLE_TIMEOUT_SECONDS", 1.0)


@pytest.fixture
async def tunnel() -> AsyncIterator[PinnedTunnel]:
    instance = PinnedTunnel(lambda: _POLICY)
    await instance.start()
    yield instance
    await instance.stop()


@pytest.fixture
async def site_factory() -> AsyncIterator[Callable[[_SiteHandler], Awaitable[_Site]]]:
    started: list[_Site] = []

    async def _start(handler: _SiteHandler) -> _Site:
        site = await _Site(handler).start()
        started.append(site)

        return site

    yield _start
    for site in started:
        await site.stop()


async def _echo(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    while chunk := await reader.read(1024):
        writer.write(b"echo:" + chunk)
        await writer.drain()


async def _open(tunnel: PinnedTunnel) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
    return await asyncio.open_connection("127.0.0.1", tunnel.port)


async def _read_status_line(reader: asyncio.StreamReader) -> bytes:
    return await asyncio.wait_for(reader.readline(), _READ_TIMEOUT)


async def _read_head(reader: asyncio.StreamReader) -> bytes:
    return await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), _READ_TIMEOUT)


async def _read_until_close(reader: asyncio.StreamReader) -> bytes:
    try:
        return await asyncio.wait_for(reader.read(), _READ_TIMEOUT)
    except ConnectionResetError:
        return b""


async def _send_connect(writer: asyncio.StreamWriter, authority: str) -> None:
    writer.write(f"CONNECT {authority} HTTP/1.1\r\nHost: {authority}\r\n\r\n".encode())
    await writer.drain()


async def test_connect_to_a_checked_address_copies_bytes_both_ways(
    tunnel: PinnedTunnel, site_factory: Callable[[_SiteHandler], Awaitable[_Site]]
) -> None:
    # given
    site = await site_factory(_echo)
    reader, writer = await _open(tunnel)

    # when
    await _send_connect(writer, f"127.0.0.1:{site.port}")
    status = await _read_status_line(reader)
    await _read_head_rest(reader)
    writer.write(b"ping")
    await writer.drain()
    answer = await asyncio.wait_for(reader.readexactly(9), _READ_TIMEOUT)
    await _close(writer)

    # then
    assert status.startswith(b"HTTP/1.1 200")
    assert answer == b"echo:ping"
    assert site.connections == 1


async def _read_head_rest(reader: asyncio.StreamReader) -> None:
    while (await asyncio.wait_for(reader.readline(), _READ_TIMEOUT)) not in (b"\r\n", b""):
        pass


@pytest.mark.parametrize("authority", ["127.0.0.2:80", "169.254.169.254:80", "10.0.0.5:443", "[::1]:8443"])
async def test_connect_to_a_refused_address_answers_403_and_connects_nowhere(
    authority: str, tunnel: PinnedTunnel
) -> None:
    # given
    reader, writer = await _open(tunnel)

    # when
    with patch("src.reader.pinned_tunnel.asyncio.open_connection") as connect:
        await _send_connect(writer, authority)
        status = await _read_status_line(reader)
    await _close(writer)

    # then
    assert status.startswith(b"HTTP/1.1 403")
    connect.assert_not_called()


async def test_a_refused_connect_is_visible_through_was_refused(tunnel: PinnedTunnel) -> None:
    # given
    reader, writer = await _open(tunnel)

    # when
    await _send_connect(writer, "169.254.169.254:443")
    await _read_status_line(reader)
    await _close(writer)

    # then
    assert tunnel.was_refused("https://169.254.169.254/latest")
    assert not tunnel.was_refused("https://169.254.169.254:8443/latest")
    assert not tunnel.was_refused("https://example.com/")


async def test_a_refused_plain_http_request_is_visible_through_was_refused(tunnel: PinnedTunnel) -> None:
    # given
    reader, writer = await _open(tunnel)

    # when
    writer.write(b"GET http://10.0.0.5/a HTTP/1.1\r\nHost: 10.0.0.5\r\n\r\n")
    await writer.drain()
    await _read_status_line(reader)
    await _close(writer)

    # then
    assert tunnel.was_refused("http://10.0.0.5/other?x=1")


@pytest.mark.parametrize("url", ["ftp://10.0.0.5/", "http://[broken/", "http:///nohost"])
def test_was_refused_is_false_for_an_address_with_no_host_and_port_to_compare(url: str) -> None:
    # when / then
    assert PinnedTunnel(lambda: _POLICY).was_refused(url) is False


async def test_a_refusal_older_than_the_memory_window_no_longer_counts(
    tunnel: PinnedTunnel, monkeypatch: pytest.MonkeyPatch
) -> None:
    # given
    monkeypatch.setattr("src.reader.pinned_tunnel._REFUSAL_MEMORY_SECONDS", 0.0)
    reader, writer = await _open(tunnel)
    await _send_connect(writer, "10.0.0.5:443")
    await _read_status_line(reader)
    await _close(writer)

    # when
    await asyncio.sleep(0.01)

    # then
    assert not tunnel.was_refused("https://10.0.0.5/")


async def test_remembered_refusals_stay_bounded(
    tunnel: PinnedTunnel, monkeypatch: pytest.MonkeyPatch
) -> None:
    # given
    monkeypatch.setattr("src.reader.pinned_tunnel._MAX_REMEMBERED_REFUSALS", 2)

    # when
    for host in ("10.0.0.1", "10.0.0.2", "10.0.0.3"):
        reader, writer = await _open(tunnel)
        await _send_connect(writer, f"{host}:443")
        await _read_status_line(reader)
        await _close(writer)

    # then
    assert not tunnel.was_refused("https://10.0.0.1/")
    assert tunnel.was_refused("https://10.0.0.2/")
    assert tunnel.was_refused("https://10.0.0.3/")


@pytest.fixture
def public_stand_in_lookup(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """The guard's lookup answers the stand-in public address on the first call and loopback after it."""
    answers = [_PUBLIC_STAND_IN]
    asked: list[str] = []
    real_is_blocked = uri_guard._is_blocked

    async def _lookup(host: str, port: int) -> list[tuple[Any, ...]]:
        asked.append(host)
        answer = answers.pop(0) if answers else "127.0.0.1"

        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (answer, port))]

    def _is_blocked(address: Any) -> bool:
        return str(address) != _PUBLIC_STAND_IN and real_is_blocked(address)

    monkeypatch.setattr(uri_guard, "_lookup", _lookup)
    monkeypatch.setattr(uri_guard, "_is_blocked", _is_blocked)

    return asked


async def _two_sites_on_one_port(handler: _SiteHandler) -> tuple[_Site, _Site]:
    for _ in range(20):
        checked = await _Site(handler).start(_PUBLIC_STAND_IN)
        rebound = _Site(handler)
        rebound.port = checked.port
        try:
            await rebound.start("127.0.0.1")
        except OSError:
            await checked.stop()
            continue

        return checked, rebound
    raise AssertionError("no port is free on both loopback addresses")


async def test_a_name_that_rebinds_is_connected_only_at_the_checked_address(
    tunnel: PinnedTunnel, public_stand_in_lookup: list[str]
) -> None:
    # given
    checked, rebound = await _two_sites_on_one_port(_echo)
    reader, writer = await _open(tunnel)

    # when
    await _send_connect(writer, f"public.example:{checked.port}")
    status = await _read_status_line(reader)
    await _close(writer)
    await asyncio.sleep(0.05)

    # then
    assert status.startswith(b"HTTP/1.1 200")
    assert checked.connections == 1
    assert rebound.connections == 0
    assert public_stand_in_lookup == ["public.example"]
    await checked.stop()
    await rebound.stop()


async def test_a_name_answering_a_private_address_is_refused_after_one_lookup(
    tunnel: PinnedTunnel, public_stand_in_lookup: list[str]
) -> None:
    # given a first connection takes the public answer, so the next lookup answers private
    reader, writer = await _open(tunnel)
    await _send_connect(writer, "public.example:1")
    await _read_status_line(reader)
    await _close(writer)
    public_stand_in_lookup.clear()
    reader2, writer2 = await _open(tunnel)

    # when
    with patch("src.reader.pinned_tunnel.asyncio.open_connection") as connect:
        await _send_connect(writer2, "public.example:443")
        status = await _read_status_line(reader2)
    await _close(writer2)

    # then
    assert status.startswith(b"HTTP/1.1 403")
    assert public_stand_in_lookup == ["public.example"]
    connect.assert_not_called()


async def test_the_policy_is_read_for_every_connection(
    site_factory: Callable[[_SiteHandler], Awaitable[_Site]],
) -> None:
    # given
    policies = [_POLICY, FetchPolicy(allowed_hosts=(), file_root=None, max_redirect_hops=3)]
    tunnel = PinnedTunnel(lambda: policies.pop(0))
    await tunnel.start()
    site = await site_factory(_echo)

    # when
    first_reader, first_writer = await _open(tunnel)
    await _send_connect(first_writer, f"127.0.0.1:{site.port}")
    first = await _read_status_line(first_reader)
    second_reader, second_writer = await _open(tunnel)
    await _send_connect(second_writer, f"127.0.0.1:{site.port}")
    second = await _read_status_line(second_reader)
    await _close(first_writer)
    await _close(second_writer)
    await tunnel.stop()

    # then
    assert first.startswith(b"HTTP/1.1 200")
    assert second.startswith(b"HTTP/1.1 403")


async def test_connect_tries_the_next_checked_address_when_one_does_not_answer(
    tunnel: PinnedTunnel,
    site_factory: Callable[[_SiteHandler], Awaitable[_Site]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # given
    site = await site_factory(_echo)

    async def _lookup(host: str, port: int) -> list[tuple[Any, ...]]:
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.3", port)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", port)),
        ]

    monkeypatch.setattr(uri_guard, "_lookup", _lookup)
    monkeypatch.setattr(uri_guard, "_is_blocked", lambda _address: False)
    reader, writer = await _open(tunnel)

    # when
    await _send_connect(writer, f"multi.example:{site.port}")
    status = await _read_status_line(reader)
    await _close(writer)

    # then
    assert status.startswith(b"HTTP/1.1 200")
    assert site.connections == 1


async def test_connect_answers_502_when_no_checked_address_answers(tunnel: PinnedTunnel) -> None:
    # given
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        free_port = probe.getsockname()[1]
    reader, writer = await _open(tunnel)

    # when
    await _send_connect(writer, f"127.0.0.1:{free_port}")
    status = await _read_status_line(reader)
    await _close(writer)

    # then
    assert status.startswith(b"HTTP/1.1 502")


async def test_connect_answers_502_when_the_checked_address_does_not_answer_in_time(
    tunnel: PinnedTunnel, monkeypatch: pytest.MonkeyPatch
) -> None:
    # given
    monkeypatch.setattr(settings, "BROWSER_TUNNEL_CONNECT_TIMEOUT_SECONDS", 0.05)

    async def _never(*_args: object, **_kwargs: object) -> None:
        await asyncio.Event().wait()

    reader, writer = await _open(tunnel)

    # when
    with patch("src.reader.pinned_tunnel.asyncio.open_connection", new=_never):
        await _send_connect(writer, "127.0.0.1:443")
        status = await _read_status_line(reader)
    await _close(writer)

    # then
    assert status.startswith(b"HTTP/1.1 502")


async def test_a_client_that_sends_no_request_head_is_closed_after_the_connect_timeout(
    tunnel: PinnedTunnel, monkeypatch: pytest.MonkeyPatch
) -> None:
    # given
    monkeypatch.setattr(settings, "BROWSER_TUNNEL_CONNECT_TIMEOUT_SECONDS", 0.05)
    reader, writer = await _open(tunnel)

    # when
    answer = await _read_until_close(reader)
    await _close(writer)

    # then
    assert answer == b""


@pytest.mark.parametrize(
    "head",
    [
        b"GET /relative HTTP/1.1\r\nHost: example.com\r\n\r\n",
        b"CONNECT example.com HTTP/1.1\r\nHost: example.com\r\n\r\n",
        b"CONNECT example.com:notaport HTTP/1.1\r\nHost: example.com\r\n\r\n",
        b"CONNECT :443 HTTP/1.1\r\nHost: x\r\n\r\n",
        b"GET https://example.com/ HTTP/1.1\r\nHost: example.com\r\n\r\n",
        b"GET http:// HTTP/1.1\r\nHost: x\r\n\r\n",
        b"GET http://example.com:notaport/ HTTP/1.1\r\nHost: x\r\n\r\n",
        b"NONSENSE\r\n\r\n",
        b"GET http://example.com/ HTTP/2\r\nHost: example.com\r\n\r\n",
    ],
)
async def test_a_malformed_request_head_answers_400(head: bytes, tunnel: PinnedTunnel) -> None:
    # given
    reader, writer = await _open(tunnel)

    # when
    writer.write(head)
    await writer.drain()
    status = await _read_status_line(reader)
    await _close(writer)

    # then
    assert status.startswith(b"HTTP/1.1 400")


async def test_an_oversized_request_head_ends_the_connection(
    tunnel: PinnedTunnel, monkeypatch: pytest.MonkeyPatch
) -> None:
    # given
    reader, writer = await _open(tunnel)

    # when
    writer.write(b"GET http://example.com/ HTTP/1.1\r\nX-Junk: " + b"a" * 200_000)
    await writer.drain()
    answer = await _read_until_close(reader)
    await _close(writer)

    # then
    assert answer == b""


async def test_plain_http_is_sent_in_origin_form_without_proxy_headers(
    tunnel: PinnedTunnel, site_factory: Callable[[_SiteHandler], Awaitable[_Site]]
) -> None:
    # given
    seen: list[bytes] = []
    body = b"page"

    async def _handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        seen.append(await reader.readuntil(b"\r\n\r\n"))
        writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 4\r\nKeep-Alive: timeout=5\r\n\r\n" + body)
        await writer.drain()

    site = await site_factory(_handler)
    reader, writer = await _open(tunnel)

    # when
    writer.write(
        f"GET http://127.0.0.1:{site.port}/page?q=1 HTTP/1.1\r\n"
        f"Host: 127.0.0.1:{site.port}\r\n"
        "Proxy-Connection: keep-alive\r\n"
        "Proxy-Authorization: Basic abc\r\n"
        "Cookie: a=b\r\n\r\n".encode()
    )
    await writer.drain()
    answer_head = await _read_head(reader)
    answer_body = await _read_until_close(reader)
    await _close(writer)

    # then
    request = seen[0]
    assert request.startswith(b"GET /page?q=1 HTTP/1.1\r\n")
    assert b"Connection: close\r\n" in request
    assert b"proxy-connection" not in request.lower()
    assert b"proxy-authorization" not in request.lower()
    assert b"Cookie: a=b\r\n" in request
    assert answer_head.startswith(b"HTTP/1.1 200 OK\r\n")
    assert b"Connection: close\r\n" in answer_head
    assert b"keep-alive" not in answer_head.lower()
    assert answer_body == body


async def test_plain_http_without_a_path_is_sent_with_the_root_path(
    tunnel: PinnedTunnel, site_factory: Callable[[_SiteHandler], Awaitable[_Site]]
) -> None:
    # given
    seen: list[bytes] = []

    async def _handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        seen.append(await reader.readuntil(b"\r\n\r\n"))
        writer.write(b"HTTP/1.1 204 No Content\r\n\r\n")

    site = await site_factory(_handler)
    reader, writer = await _open(tunnel)

    # when
    writer.write(f"GET http://127.0.0.1:{site.port} HTTP/1.1\r\nHost: x\r\n\r\n".encode())
    await writer.drain()
    await _read_head(reader)
    await _close(writer)

    # then
    assert seen[0].startswith(b"GET / HTTP/1.1\r\n")


async def test_plain_http_uses_port_80_when_the_address_names_none(tunnel: PinnedTunnel) -> None:
    # given
    reader, writer = await _open(tunnel)

    # when
    with patch(
        "src.reader.pinned_tunnel.asyncio.open_connection", side_effect=OSError("no route")
    ) as connect:
        writer.write(b"GET http://127.0.0.1/ HTTP/1.1\r\nHost: x\r\n\r\n")
        await writer.drain()
        await _read_status_line(reader)
    await _close(writer)

    # then
    assert connect.call_args.args[:2] == ("127.0.0.1", 80)


async def test_plain_http_forwards_a_request_body_by_its_content_length_and_nothing_after_it(
    tunnel: PinnedTunnel, site_factory: Callable[[_SiteHandler], Awaitable[_Site]]
) -> None:
    # given
    received: list[bytes] = []

    async def _handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await reader.readuntil(b"\r\n\r\n")
        received.append(await reader.readexactly(5))
        await asyncio.sleep(0.05)
        writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\n\r\n")
        await writer.drain()

    site = await site_factory(_handler)
    reader, writer = await _open(tunnel)

    # when
    writer.write(
        f"POST http://127.0.0.1:{site.port}/form HTTP/1.1\r\nHost: x\r\nContent-Length: 5\r\n\r\n".encode()
        + b"hello"
        + b"GET http://other.example/ HTTP/1.1\r\n\r\n"
    )
    await writer.drain()
    await _read_head(reader)
    leftover = await _read_until_close(reader)
    await _close(writer)

    # then
    assert received == [b"hello"]
    assert leftover == b""
    assert site.connections == 1


async def test_plain_http_with_a_body_the_client_never_finishes_ends_at_the_idle_timeout(
    tunnel: PinnedTunnel,
    site_factory: Callable[[_SiteHandler], Awaitable[_Site]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # given
    monkeypatch.setattr(settings, "BROWSER_TUNNEL_IDLE_TIMEOUT_SECONDS", 0.05)
    site = await site_factory(_echo)
    reader, writer = await _open(tunnel)

    # when
    writer.write(
        f"POST http://127.0.0.1:{site.port}/ HTTP/1.1\r\nHost: x\r\nContent-Length: 50\r\n\r\n".encode()
        + b"partial"
    )
    await writer.drain()
    closed = await _read_until_close(reader)
    await _close(writer)

    # then
    assert closed == b""


async def test_plain_http_with_a_body_that_ends_before_its_length_ends_the_connection(
    tunnel: PinnedTunnel, site_factory: Callable[[_SiteHandler], Awaitable[_Site]]
) -> None:
    # given
    site = await site_factory(_echo)
    reader, writer = await _open(tunnel)

    # when
    writer.write(
        f"POST http://127.0.0.1:{site.port}/ HTTP/1.1\r\nHost: x\r\nContent-Length: 50\r\n\r\n".encode()
        + b"partial"
    )
    await writer.drain()
    writer.write_eof()
    closed = await _read_until_close(reader)
    await _close(writer)

    # then
    assert closed == b""


@pytest.mark.parametrize(
    ("header", "expected_status"),
    [
        (b"Transfer-Encoding: chunked\r\n", b"HTTP/1.1 501"),
        (b"Content-Length: nope\r\n", b"HTTP/1.1 400"),
    ],
)
async def test_plain_http_refuses_a_body_it_cannot_frame(
    header: bytes, expected_status: bytes, tunnel: PinnedTunnel
) -> None:
    # given
    reader, writer = await _open(tunnel)

    # when
    writer.write(b"POST http://127.0.0.1:9/ HTTP/1.1\r\nHost: x\r\n" + header + b"\r\n")
    await writer.drain()
    status = await _read_status_line(reader)
    await _close(writer)

    # then
    assert status.startswith(expected_status)


async def test_plain_http_passes_interim_answers_and_rewrites_only_the_final_head(
    tunnel: PinnedTunnel, site_factory: Callable[[_SiteHandler], Awaitable[_Site]]
) -> None:
    # given
    async def _handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await reader.readuntil(b"\r\n\r\n")
        writer.write(b"HTTP/1.1 103 Early Hints\r\nLink: </a.css>\r\n\r\n")
        writer.write(b"HTTP/1.1 200 OK\r\nConnection: keep-alive\r\nContent-Length: 2\r\n\r\nok")
        await writer.drain()

    site = await site_factory(_handler)
    reader, writer = await _open(tunnel)

    # when
    writer.write(f"GET http://127.0.0.1:{site.port}/ HTTP/1.1\r\nHost: x\r\n\r\n".encode())
    await writer.drain()
    interim = await _read_head(reader)
    final = await _read_head(reader)
    body = await _read_until_close(reader)
    await _close(writer)

    # then
    assert interim == b"HTTP/1.1 103 Early Hints\r\nLink: </a.css>\r\n\r\n"
    assert final.startswith(b"HTTP/1.1 200 OK\r\n")
    assert b"Connection: close\r\n" in final
    assert b"keep-alive" not in final.lower()
    assert body == b"ok"


async def test_plain_http_refused_answers_403_and_logs_no_query(
    tunnel: PinnedTunnel, caplog: pytest.LogCaptureFixture
) -> None:
    # given
    reader, writer = await _open(tunnel)

    # when
    with caplog.at_level(logging.WARNING, logger="src.reader.pinned_tunnel"):
        writer.write(b"GET http://10.0.0.5/admin?token=secret HTTP/1.1\r\nHost: 10.0.0.5\r\n\r\n")
        await writer.drain()
        status = await _read_status_line(reader)
    await _close(writer)

    # then
    assert status.startswith(b"HTTP/1.1 403")
    assert "http://10.0.0.5/admin" in caplog.text
    assert "secret" not in caplog.text


async def test_plain_http_answers_502_when_the_checked_address_does_not_answer(tunnel: PinnedTunnel) -> None:
    # given
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        free_port = probe.getsockname()[1]
    reader, writer = await _open(tunnel)

    # when
    writer.write(f"GET http://127.0.0.1:{free_port}/ HTTP/1.1\r\nHost: x\r\n\r\n".encode())
    await writer.drain()
    status = await _read_status_line(reader)
    await _close(writer)

    # then
    assert status.startswith(b"HTTP/1.1 502")


async def _stream_chunks(count: int, chunk: bytes) -> _SiteHandler:
    async def _handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await reader.read(1)
        for _ in range(count):
            writer.write(chunk)
            await writer.drain()
            await asyncio.sleep(0.01)

    return _handler


async def test_bytes_from_the_site_above_the_cap_end_the_connection(
    tunnel: PinnedTunnel,
    site_factory: Callable[[_SiteHandler], Awaitable[_Site]],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # given
    monkeypatch.setattr(settings, "BROWSER_RESPONSE_MAX_BYTES", 1000)
    site = await site_factory(await _stream_chunks(10, b"x" * 400))
    reader, writer = await _open(tunnel)

    # when
    with caplog.at_level(logging.WARNING, logger="src.reader.pinned_tunnel"):
        await _send_connect(writer, f"127.0.0.1:{site.port}")
        await _read_head(reader)
        writer.write(b"g")
        await writer.drain()
        received = await _read_until_close(reader)
    await _close(writer)

    # then
    assert 0 < len(received) <= 1000
    assert "above the cap" in caplog.text


async def test_plain_http_counts_the_answer_head_against_the_cap(
    tunnel: PinnedTunnel,
    site_factory: Callable[[_SiteHandler], Awaitable[_Site]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # given
    monkeypatch.setattr(settings, "BROWSER_RESPONSE_MAX_BYTES", 10)

    async def _handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await reader.readuntil(b"\r\n\r\n")
        writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 4\r\n\r\nabcd")
        await writer.drain()

    site = await site_factory(_handler)
    reader, writer = await _open(tunnel)

    # when
    writer.write(f"GET http://127.0.0.1:{site.port}/ HTTP/1.1\r\nHost: x\r\n\r\n".encode())
    await writer.drain()
    received = await _read_until_close(reader)
    await _close(writer)

    # then
    assert received == b""


async def test_bytes_from_the_browser_are_not_counted_against_the_cap(
    tunnel: PinnedTunnel,
    site_factory: Callable[[_SiteHandler], Awaitable[_Site]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # given
    monkeypatch.setattr(settings, "BROWSER_RESPONSE_MAX_BYTES", 10)

    async def _handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        got = await reader.readexactly(50)
        writer.write(str(len(got)).encode())
        await writer.drain()

    site = await site_factory(_handler)
    reader, writer = await _open(tunnel)

    # when
    await _send_connect(writer, f"127.0.0.1:{site.port}")
    await _read_head(reader)
    writer.write(b"u" * 50)
    await writer.drain()
    answer = await asyncio.wait_for(reader.readexactly(2), _READ_TIMEOUT)
    await _close(writer)

    # then
    assert answer == b"50"


async def test_an_idle_tunnel_is_closed_at_the_idle_timeout(
    tunnel: PinnedTunnel,
    site_factory: Callable[[_SiteHandler], Awaitable[_Site]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # given
    monkeypatch.setattr(settings, "BROWSER_TUNNEL_IDLE_TIMEOUT_SECONDS", 0.05)
    site = await site_factory(_echo)
    reader, writer = await _open(tunnel)
    await _send_connect(writer, f"127.0.0.1:{site.port}")
    await _read_head(reader)

    # when
    closed = await _read_until_close(reader)
    await _close(writer)

    # then
    assert closed == b""


async def test_a_tunnel_with_traffic_in_one_direction_stays_open_past_the_idle_timeout(
    tunnel: PinnedTunnel,
    site_factory: Callable[[_SiteHandler], Awaitable[_Site]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # given
    monkeypatch.setattr(settings, "BROWSER_TUNNEL_IDLE_TIMEOUT_SECONDS", 0.2)

    async def _slow_site(_reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        for chunk in (b"a", b"b", b"c", b"d"):
            writer.write(chunk)
            await writer.drain()
            await asyncio.sleep(0.1)

    site = await site_factory(_slow_site)
    reader, writer = await _open(tunnel)

    # when
    await _send_connect(writer, f"127.0.0.1:{site.port}")
    await _read_head(reader)
    received = await asyncio.wait_for(reader.read(), _READ_TIMEOUT)
    await _close(writer)

    # then
    assert received == b"abcd"


async def test_a_plain_http_answer_stalled_past_the_idle_timeout_ends_the_connection(
    tunnel: PinnedTunnel,
    site_factory: Callable[[_SiteHandler], Awaitable[_Site]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # given
    monkeypatch.setattr(settings, "BROWSER_TUNNEL_IDLE_TIMEOUT_SECONDS", 0.05)

    async def _silent(reader: asyncio.StreamReader, _writer: asyncio.StreamWriter) -> None:
        await reader.readuntil(b"\r\n\r\n")
        await asyncio.Event().wait()

    site = await site_factory(_silent)
    reader, writer = await _open(tunnel)

    # when
    writer.write(f"GET http://127.0.0.1:{site.port}/ HTTP/1.1\r\nHost: x\r\n\r\n".encode())
    await writer.drain()
    closed = await _read_until_close(reader)
    await _close(writer)

    # then
    assert closed == b""


async def test_shutdown_closes_every_socket_and_task(
    site_factory: Callable[[_SiteHandler], Awaitable[_Site]],
) -> None:
    # given
    tunnel = PinnedTunnel(lambda: _POLICY)
    await tunnel.start()
    site = await site_factory(_echo)
    reader, writer = await _open(tunnel)
    await _send_connect(writer, f"127.0.0.1:{site.port}")
    await _read_head(reader)
    idle_reader, idle_writer = await _open(tunnel)
    port = tunnel.port
    before = asyncio.all_tasks()

    # when
    await tunnel.stop()
    await asyncio.sleep(0)
    answer = await _read_until_close(reader)
    idle_answer = await _read_until_close(idle_reader)
    await _close(writer)
    await _close(idle_writer)

    # then
    assert answer == b""
    assert idle_answer == b""
    with pytest.raises(OSError, match="Connect"):
        await asyncio.open_connection("127.0.0.1", port)
    assert asyncio.all_tasks() - before == set()


async def test_port_raises_before_the_tunnel_started() -> None:
    # when / then
    with pytest.raises(TunnelNotStartedError):
        _ = PinnedTunnel(lambda: _POLICY).port


async def test_port_raises_after_the_tunnel_stopped() -> None:
    # given
    tunnel = PinnedTunnel(lambda: _POLICY)
    await tunnel.start()
    await tunnel.stop()

    # when / then
    with pytest.raises(TunnelNotStartedError):
        _ = tunnel.port


async def test_starting_a_started_tunnel_keeps_its_listener() -> None:
    # given
    tunnel = PinnedTunnel(lambda: _POLICY)
    await tunnel.start()
    port = tunnel.port

    # when
    await tunnel.start()

    # then
    assert tunnel.port == port
    await tunnel.stop()


async def test_stopping_a_tunnel_that_never_started_does_nothing() -> None:
    # given
    tunnel = PinnedTunnel(lambda: _POLICY)

    # when / then
    await tunnel.stop()


@pytest.fixture
def chain_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "PROXY_URL", "http://user:p%40ss@127.0.0.1:39999")
    monkeypatch.setattr(settings, "CRAWL_PROXY_URL", "socks5://crawl-proxy:1080")


async def test_a_context_proxy_is_chained_through_a_tunnel_listener_of_its_own(chain_settings: None) -> None:
    # given
    tunnel = PinnedTunnel(lambda: _POLICY)
    await tunnel.start()

    # when
    chained = tunnel.chained_proxy({"server": "socks5://crawl-proxy:1080"})

    # then
    assert chained["server"].startswith("http://127.0.0.1:")
    assert chained["server"] != f"http://127.0.0.1:{tunnel.port}"
    await tunnel.stop()


async def test_a_context_proxy_the_tunnel_has_no_listener_for_raises() -> None:
    # given
    tunnel = PinnedTunnel(lambda: _POLICY)
    await tunnel.start()

    # when / then
    with pytest.raises(TunnelNotStartedError):
        tunnel.chained_proxy({"server": "http://unknown:1"})
    await tunnel.stop()


async def _proxy_site(answer: bytes, seen: list[bytes]) -> _SiteHandler:
    async def _handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        seen.append(await reader.readuntil(b"\r\n\r\n"))
        writer.write(answer)
        await writer.drain()
        await _echo(reader, writer)

    return _handler


async def test_connect_through_a_chained_proxy_sends_the_name_and_the_credentials(
    site_factory: Callable[[_SiteHandler], Awaitable[_Site]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # given
    seen: list[bytes] = []
    proxy = await site_factory(await _proxy_site(b"HTTP/1.1 200 Connected\r\n\r\n", seen))
    server = f"http://user:p%40ss@127.0.0.1:{proxy.port}"
    monkeypatch.setattr(settings, "PROXY_URL", server)
    policy = FetchPolicy(allowed_hosts=("public.example",), file_root=None, max_redirect_hops=3)
    tunnel = PinnedTunnel(lambda: policy)
    await tunnel.start()
    chain_port = int(tunnel.chained_proxy({"server": server})["server"].rsplit(":", 1)[1])
    reader, writer = await asyncio.open_connection("127.0.0.1", chain_port)

    # when
    await _send_connect(writer, "public.example:443")
    status = await _read_status_line(reader)
    await _read_head_rest(reader)
    writer.write(b"ping")
    await writer.drain()
    answer = await asyncio.wait_for(reader.readexactly(9), _READ_TIMEOUT)
    await _close(writer)
    await tunnel.stop()

    # then
    assert status.startswith(b"HTTP/1.1 200")
    assert answer == b"echo:ping"
    expected = base64.b64encode(b"user:p@ss").decode()
    assert seen[0].startswith(b"CONNECT public.example:443 HTTP/1.1\r\n")
    assert f"Proxy-Authorization: Basic {expected}\r\n".encode() in seen[0]


async def test_a_chained_proxy_with_no_credentials_sends_no_authorization(
    site_factory: Callable[[_SiteHandler], Awaitable[_Site]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # given
    seen: list[bytes] = []
    proxy = await site_factory(await _proxy_site(b"HTTP/1.1 200 Connected\r\n\r\n", seen))
    server = f"http://127.0.0.1:{proxy.port}"
    monkeypatch.setattr(settings, "PROXY_URL", server)
    tunnel = PinnedTunnel(lambda: _POLICY)
    await tunnel.start()
    chain_port = int(tunnel.chained_proxy({"server": server})["server"].rsplit(":", 1)[1])
    reader, writer = await asyncio.open_connection("127.0.0.1", chain_port)

    # when
    await _send_connect(writer, "[2606:4700::1]:443")
    await _read_status_line(reader)
    await _close(writer)
    await tunnel.stop()

    # then
    assert seen[0].startswith(b"CONNECT [2606:4700::1]:443 HTTP/1.1\r\n")
    assert b"proxy-authorization" not in seen[0].lower()


async def test_a_refused_address_never_reaches_the_chained_proxy(
    site_factory: Callable[[_SiteHandler], Awaitable[_Site]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # given
    seen: list[bytes] = []
    proxy = await site_factory(await _proxy_site(b"HTTP/1.1 200 Connected\r\n\r\n", seen))
    server = f"http://127.0.0.1:{proxy.port}"
    monkeypatch.setattr(settings, "PROXY_URL", server)
    tunnel = PinnedTunnel(lambda: _POLICY)
    await tunnel.start()
    chain_port = int(tunnel.chained_proxy({"server": server})["server"].rsplit(":", 1)[1])
    reader, writer = await asyncio.open_connection("127.0.0.1", chain_port)

    # when
    await _send_connect(writer, "10.0.0.5:443")
    status = await _read_status_line(reader)
    await _close(writer)
    await tunnel.stop()

    # then
    assert status.startswith(b"HTTP/1.1 403")
    assert seen == []


async def test_a_chained_proxy_that_refuses_the_tunnel_answers_502(
    site_factory: Callable[[_SiteHandler], Awaitable[_Site]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # given
    proxy = await site_factory(await _proxy_site(b"HTTP/1.1 407 Auth\r\n\r\n", []))
    server = f"http://127.0.0.1:{proxy.port}"
    monkeypatch.setattr(settings, "PROXY_URL", server)
    tunnel = PinnedTunnel(lambda: _POLICY)
    await tunnel.start()
    chain_port = int(tunnel.chained_proxy({"server": server})["server"].rsplit(":", 1)[1])
    reader, writer = await asyncio.open_connection("127.0.0.1", chain_port)

    # when
    await _send_connect(writer, "127.0.0.1:443")
    status = await _read_status_line(reader)
    await _close(writer)
    await tunnel.stop()

    # then
    assert status.startswith(b"HTTP/1.1 502")


async def test_a_chained_proxy_that_closes_before_it_answers_answers_502(
    site_factory: Callable[[_SiteHandler], Awaitable[_Site]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # given
    async def _closing(_reader: asyncio.StreamReader, _writer: asyncio.StreamWriter) -> None:
        return

    proxy = await site_factory(_closing)
    server = f"http://127.0.0.1:{proxy.port}"
    monkeypatch.setattr(settings, "PROXY_URL", server)
    tunnel = PinnedTunnel(lambda: _POLICY)
    await tunnel.start()
    chain_port = int(tunnel.chained_proxy({"server": server})["server"].rsplit(":", 1)[1])
    reader, writer = await asyncio.open_connection("127.0.0.1", chain_port)

    # when
    await _send_connect(writer, "127.0.0.1:443")
    status = await _read_status_line(reader)
    await _close(writer)
    await tunnel.stop()

    # then
    assert status.startswith(b"HTTP/1.1 502")


async def test_a_socks_proxy_cannot_be_chained_and_answers_502(
    chain_settings: None, caplog: pytest.LogCaptureFixture
) -> None:
    # given
    tunnel = PinnedTunnel(lambda: _POLICY)
    await tunnel.start()
    chained = tunnel.chained_proxy({"server": "socks5://crawl-proxy:1080"})
    chain_port = int(chained["server"].rsplit(":", 1)[1])
    reader, writer = await asyncio.open_connection("127.0.0.1", chain_port)

    # when
    with caplog.at_level(logging.WARNING, logger="src.reader.pinned_tunnel"):
        await _send_connect(writer, "127.0.0.1:443")
        status = await _read_status_line(reader)
    await _close(writer)
    await tunnel.stop()

    # then
    assert status.startswith(b"HTTP/1.1 502")
    assert "cannot be chained" in caplog.text
    assert "crawl-proxy" in caplog.text


async def test_a_chained_https_proxy_is_reached_over_tls(monkeypatch: pytest.MonkeyPatch) -> None:
    # given
    server = "https://proxy.example:8443"
    monkeypatch.setattr(settings, "PROXY_URL", server)
    tunnel = PinnedTunnel(lambda: _POLICY)
    await tunnel.start()
    chain_port = int(tunnel.chained_proxy({"server": server})["server"].rsplit(":", 1)[1])
    reader, writer = await asyncio.open_connection("127.0.0.1", chain_port)

    # when
    with patch(
        "src.reader.pinned_tunnel.asyncio.open_connection", side_effect=ssl.SSLError("nope")
    ) as connect:
        await _send_connect(writer, "127.0.0.1:443")
        await _read_status_line(reader)
    await _close(writer)
    await tunnel.stop()

    # then
    assert connect.call_args.args[:2] == ("proxy.example", 8443)
    assert connect.call_args.kwargs["ssl"] is True


async def test_plain_http_goes_through_a_chained_proxy_with_connect(
    site_factory: Callable[[_SiteHandler], Awaitable[_Site]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # given
    seen: list[bytes] = []

    async def _handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        seen.append(await reader.readuntil(b"\r\n\r\n"))
        writer.write(b"HTTP/1.1 200 Connected\r\n\r\n")
        await writer.drain()
        seen.append(await reader.readuntil(b"\r\n\r\n"))
        writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\n\r\n")
        await writer.drain()

    proxy = await site_factory(_handler)
    server = f"http://127.0.0.1:{proxy.port}"
    monkeypatch.setattr(settings, "PROXY_URL", server)
    tunnel = PinnedTunnel(lambda: _POLICY)
    await tunnel.start()
    chain_port = int(tunnel.chained_proxy({"server": server})["server"].rsplit(":", 1)[1])
    reader, writer = await asyncio.open_connection("127.0.0.1", chain_port)

    # when
    writer.write(b"GET http://127.0.0.1:8080/a HTTP/1.1\r\nHost: x\r\n\r\n")
    await writer.drain()
    status = await _read_status_line(reader)
    await _close(writer)
    await tunnel.stop()

    # then
    assert status.startswith(b"HTTP/1.1 200")
    assert seen[0].startswith(b"CONNECT 127.0.0.1:8080 HTTP/1.1\r\n")
    assert seen[1].startswith(b"GET /a HTTP/1.1\r\n")


async def _wait_until_no_connection(tunnel: PinnedTunnel, seconds: float) -> None:
    if tunnel._connections:
        await asyncio.wait(tunnel._connections, timeout=seconds)


@pytest.mark.parametrize(
    "answer",
    [b"HTTP/1.1 200 OK\r\nContent-Length: 1\r\n\r\n", b""],
    ids=["site holds its socket after the head", "site never answers"],
)
async def test_a_browser_that_closes_ends_a_plain_connection_the_site_holds_open(
    tunnel: PinnedTunnel,
    site_factory: Callable[[_SiteHandler], Awaitable[_Site]],
    monkeypatch: pytest.MonkeyPatch,
    answer: bytes,
) -> None:
    # given
    monkeypatch.setattr(settings, "BROWSER_TUNNEL_IDLE_TIMEOUT_SECONDS", 30.0)
    answered = asyncio.Event()
    held = asyncio.Event()

    async def _hold(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await reader.readuntil(b"\r\n\r\n")
        writer.write(answer)
        await writer.drain()
        answered.set()
        await held.wait()

    site = await site_factory(_hold)
    reader, writer = await _open(tunnel)
    writer.write(f"GET http://127.0.0.1:{site.port}/ HTTP/1.1\r\nHost: x\r\n\r\n".encode())
    await writer.drain()
    await asyncio.wait_for(answered.wait(), _READ_TIMEOUT)
    if answer:
        await _read_head(reader)

    # when
    await _close(writer)
    await _wait_until_no_connection(tunnel, 2.0)

    # then
    assert tunnel._connections == set()


async def test_a_connection_above_the_cap_answers_503_and_opens_no_site_socket(
    tunnel: PinnedTunnel,
    site_factory: Callable[[_SiteHandler], Awaitable[_Site]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # given
    monkeypatch.setattr(settings, "BROWSER_TUNNEL_MAX_CONNECTIONS", 1)
    site = await site_factory(_echo)
    first_reader, first_writer = await _open(tunnel)
    await _send_connect(first_writer, f"127.0.0.1:{site.port}")
    await _read_head(first_reader)

    # when
    second_reader, second_writer = await _open(tunnel)
    await _send_connect(second_writer, f"127.0.0.1:{site.port}")
    status = await _read_status_line(second_reader)
    await _close(second_writer)
    await _close(first_writer)

    # then
    assert status.startswith(b"HTTP/1.1 503")
    assert site.connections == 1


async def test_a_later_good_check_clears_the_remembered_refusal(
    tunnel: PinnedTunnel, site_factory: Callable[[_SiteHandler], Awaitable[_Site]]
) -> None:
    # given a name whose first lookup failed for a moment
    site = await site_factory(_echo)
    authority = f"flaky.example:{site.port}"
    url = f"https://{authority}/"
    check = AsyncMock(
        side_effect=[
            UnsafeUriError("could not resolve"),
            FetchTarget(url=url, host="flaky.example", port=site.port, addresses=("127.0.0.1",)),
        ]
    )

    with patch("src.reader.pinned_tunnel.check_fetch_uri", new=check):
        reader, writer = await _open(tunnel)
        await _send_connect(writer, authority)
        await _read_status_line(reader)
        await _close(writer)
        refused_after_the_failure = tunnel.was_refused(url)

        # when
        reader, writer = await _open(tunnel)
        await _send_connect(writer, authority)
        await _read_head(reader)
        await _close(writer)

    # then
    assert refused_after_the_failure is True
    assert tunnel.was_refused(url) is False


def test_the_missing_listener_error_names_the_proxy_host_without_its_credentials() -> None:
    # given
    tunnel = PinnedTunnel(lambda: _POLICY)

    # when
    with pytest.raises(TunnelNotStartedError) as caught:
        tunnel.chained_proxy({"server": "http://user:hunter2@proxy.example:3128"})

    # then
    assert "proxy.example" in str(caught.value)
    assert "hunter2" not in str(caught.value)
    assert "user" not in str(caught.value)

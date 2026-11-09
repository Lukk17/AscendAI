"""Local forward proxy every browser tier connects through.

One lookup both checks and pins: a CONNECT or plain http request resolves its
host once through ``check_fetch_uri``, refuses an address the fetch policy
refuses, and opens only the checked addresses. The browser keeps its own TLS
handshake, because the tunnel carries bytes and never terminates anything.
Plain http is carried one request per connection, framed by Content-Length, so
a reused connection can never hand one site's request to another.

A browser context with a customer proxy gets a listener of its own that sends
the same checked connection on through that proxy, which resolves the name
itself, as the static tiers do.

A refusal has no effect a browser can report precisely, so the tunnel
remembers what it refused for a short time and ``was_refused`` answers it for
the guard.
"""

import asyncio
import base64
import logging
import time
from collections import OrderedDict
from collections.abc import Callable, Coroutine, Mapping
from dataclasses import dataclass
from functools import partial
from typing import Any, Final
from urllib.parse import unquote, urlsplit

from ascend_python_common.uri_guard import FetchPolicy, UnsafeUriError, check_fetch_uri

from src.config.config import settings
from src.observability.safe_address import address_without_query

logger = logging.getLogger(__name__)

TUNNEL_HOST: Final = "127.0.0.1"
TUNNEL_REFUSAL_STATUS: Final = 403
_HEAD_END: Final = b"\r\n\r\n"
_LINE_END: Final = b"\r\n"
_HEAD_LIMIT_BYTES: Final = 65536
_COPY_CHUNK_BYTES: Final = 65536
_HTTP_DEFAULT_PORT: Final = 80
_DEFAULT_PORTS: Final = {"http": 80, "https": 443}
_INTERIM_STATUSES: Final = range(100, 200)
_CONNECT: Final = "CONNECT"
_REFUSAL_MEMORY_SECONDS: float = 30.0
_MAX_REMEMBERED_REFUSALS: int = 4096
_CHAINABLE_PROXY_SCHEMES: Final = frozenset({"http", "https"})

_ESTABLISHED: Final = b"HTTP/1.1 200 Connection Established\r\n\r\n"
_BAD_REQUEST: Final = "400 Bad Request"
_FORBIDDEN: Final = f"{TUNNEL_REFUSAL_STATUS} Forbidden"
_NOT_IMPLEMENTED: Final = "501 Not Implemented"
_BAD_GATEWAY: Final = "502 Bad Gateway"
_SERVICE_UNAVAILABLE: Final = "503 Service Unavailable"

_STRIPPED_REQUEST_HEADERS: Final = frozenset(
    {
        b"connection",
        b"proxy-connection",
        b"proxy-authorization",
        b"keep-alive",
        b"te",
        b"upgrade",
        b"transfer-encoding",
    }
)
_STRIPPED_ANSWER_HEADERS: Final = frozenset({b"connection", b"proxy-connection", b"keep-alive"})
_CONNECTION_CLOSE: Final = b"Connection: close"
_CONTENT_LENGTH: Final = b"content-length"
_TRANSFER_ENCODING: Final = b"transfer-encoding"


class TunnelNotStartedError(RuntimeError):
    """The tunnel, or the listener of the asked context proxy, is not running."""


class _SiteUnreachableError(OSError):
    """No checked address, or no chained proxy, opened a connection to the site."""


class _ByteCapExceededError(OSError):
    """More bytes came from the site than ``BROWSER_RESPONSE_MAX_BYTES`` allows on one connection."""


@dataclass(frozen=True, slots=True)
class _Request:
    method: str
    check_url: str
    host: str
    port: int
    origin_form: str
    version: str
    headers: tuple[bytes, ...]

    @property
    def is_tunnel(self) -> bool:
        return self.method == _CONNECT

    @property
    def authority(self) -> str:
        return f"[{self.host}]:{self.port}" if ":" in self.host else f"{self.host}:{self.port}"


def _authority_url(host: str, port: int) -> str:
    bracketed = f"[{host}]" if ":" in host else host

    return f"https://{bracketed}:{port}/"


def _split_host_port(authority: str) -> tuple[str, int] | None:
    try:
        parts = urlsplit(f"//{authority}")
        port = parts.port
    except ValueError:
        return None

    return (parts.hostname, port) if parts.hostname and port is not None else None


def _parse_connect(target: str, version: str, headers: tuple[bytes, ...]) -> _Request | None:
    host_port = _split_host_port(target)
    if host_port is None:
        return None
    host, port = host_port

    return _Request(_CONNECT, _authority_url(host, port), host, port, "", version, headers)


def _parse_absolute(method: str, target: str, version: str, headers: tuple[bytes, ...]) -> _Request | None:
    try:
        parts = urlsplit(target)
        port = parts.port if parts.port is not None else _HTTP_DEFAULT_PORT
    except ValueError:
        return None
    if parts.scheme.lower() != "http" or not parts.hostname:
        return None
    origin_form = parts.path or "/"
    if parts.query:
        origin_form = f"{origin_form}?{parts.query}"

    return _Request(method, target, parts.hostname, port, origin_form, version, headers)


def _parse_head(head: bytes) -> _Request | None:
    request_line, *header_lines = head[: -len(_HEAD_END)].split(_LINE_END)
    fields = request_line.decode("latin-1").split()
    if len(fields) != 3 or not fields[2].startswith("HTTP/1."):
        return None
    method, target, version = fields
    headers = tuple(header_lines)
    if method.upper() == _CONNECT:
        return _parse_connect(target, version, headers)

    return _parse_absolute(method, target, version, headers)


def _header_name(line: bytes) -> bytes:
    return line.split(b":", 1)[0].strip().lower()


def _content_length(request: _Request) -> int | None:
    for line in request.headers:
        if _header_name(line) == _CONTENT_LENGTH:
            value = line.split(b":", 1)[1].strip()
            if not value.isdigit():
                return None

            return int(value)

    return 0


def _has_transfer_encoding(request: _Request) -> bool:
    return any(_header_name(line) == _TRANSFER_ENCODING for line in request.headers)


def _origin_form_head(request: _Request) -> bytes:
    kept = [line for line in request.headers if _header_name(line) not in _STRIPPED_REQUEST_HEADERS]
    request_line = f"{request.method} {request.origin_form} {request.version}".encode("latin-1")

    return _LINE_END.join([request_line, *kept, _CONNECTION_CLOSE, b"", b""])


def _answer_status(head: bytes) -> int:
    fields = head.split(_LINE_END, 1)[0].split()

    return int(fields[1]) if len(fields) > 1 and fields[1].isdigit() else 0


def _with_connection_close(head: bytes) -> bytes:
    status_line, *lines = head[: -len(_HEAD_END)].split(_LINE_END)
    kept = [line for line in lines if _header_name(line) not in _STRIPPED_ANSWER_HEADERS]

    return _LINE_END.join([status_line, *kept, _CONNECTION_CLOSE, b"", b""])


def _refusal_key(url: str) -> tuple[str, int] | None:
    try:
        parts = urlsplit(url)
        port = parts.port or _DEFAULT_PORTS.get(parts.scheme.lower())
    except ValueError:
        return None

    return (parts.hostname.lower(), port) if parts.hostname and port else None


def _host_and_port(request: _Request) -> tuple[str, int]:
    return request.host.lower(), request.port


class _Relay:
    """The byte count and the last activity of one relayed connection."""

    def __init__(self, shown: str) -> None:
        self._shown = shown
        self._site_bytes = 0
        self._last_activity = time.monotonic()

    def touch(self) -> None:
        self._last_activity = time.monotonic()

    def seconds_idle(self) -> float:
        return time.monotonic() - self._last_activity

    def count_site_bytes(self, count: int) -> None:
        self._site_bytes += count
        if self._site_bytes > settings.BROWSER_RESPONSE_MAX_BYTES:
            logger.warning(
                "pinned_tunnel: connection to %s is above the cap of %d bytes, closed",
                self._shown,
                settings.BROWSER_RESPONSE_MAX_BYTES,
            )

            raise _ByteCapExceededError(self._shown)


async def _read_some(source: asyncio.StreamReader, relay: _Relay) -> bytes:
    idle = settings.BROWSER_TUNNEL_IDLE_TIMEOUT_SECONDS
    while True:
        try:
            async with asyncio.timeout(idle):
                return await source.read(_COPY_CHUNK_BYTES)
        except TimeoutError:
            if relay.seconds_idle() >= idle:
                raise


async def _drain(target: asyncio.StreamWriter) -> None:
    async with asyncio.timeout(settings.BROWSER_TUNNEL_IDLE_TIMEOUT_SECONDS):
        await target.drain()


async def _pump(
    source: asyncio.StreamReader, target: asyncio.StreamWriter, relay: _Relay, *, from_site: bool
) -> None:
    while chunk := await _read_some(source, relay):
        if from_site:
            relay.count_site_bytes(len(chunk))
        relay.touch()
        target.write(chunk)
        await _drain(target)


async def _read_head_idle(reader: asyncio.StreamReader) -> bytes:
    async with asyncio.timeout(settings.BROWSER_TUNNEL_IDLE_TIMEOUT_SECONDS):
        return await reader.readuntil(_HEAD_END)


async def _forward_request_body(
    client: asyncio.StreamReader, site: asyncio.StreamWriter, length: int, relay: _Relay
) -> None:
    remaining = length
    while remaining > 0:
        async with asyncio.timeout(settings.BROWSER_TUNNEL_IDLE_TIMEOUT_SECONDS):
            chunk = await client.read(min(remaining, _COPY_CHUNK_BYTES))
        if not chunk:
            raise asyncio.IncompleteReadError(b"", remaining)
        remaining -= len(chunk)
        relay.touch()
        site.write(chunk)
        await _drain(site)


async def _forward_answer_head(
    site: asyncio.StreamReader, client: asyncio.StreamWriter, relay: _Relay
) -> None:
    while True:
        head = await _read_head_idle(site)
        relay.count_site_bytes(len(head))
        relay.touch()
        if _answer_status(head) not in _INTERIM_STATUSES:
            client.write(_with_connection_close(head))
            await _drain(client)

            return
        client.write(head)
        await _drain(client)


async def _until_the_first_ends(*steps: Coroutine[Any, Any, None]) -> None:
    tasks = {asyncio.create_task(step) for step in steps}
    try:
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


async def _relay_tunnel(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    site_reader: asyncio.StreamReader,
    site_writer: asyncio.StreamWriter,
    relay: _Relay,
) -> None:
    writer.write(_ESTABLISHED)
    await writer.drain()
    await _until_the_first_ends(
        _pump(reader, site_writer, relay, from_site=False),
        _pump(site_reader, writer, relay, from_site=True),
    )


async def _until_the_client_closes(reader: asyncio.StreamReader) -> None:
    while await reader.read(_COPY_CHUNK_BYTES):
        continue


async def _carry_answer(
    site_reader: asyncio.StreamReader, writer: asyncio.StreamWriter, relay: _Relay
) -> None:
    await _forward_answer_head(site_reader, writer, relay)
    await _pump(site_reader, writer, relay, from_site=True)


async def _relay_plain(
    request: _Request,
    length: int,
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    site_reader: asyncio.StreamReader,
    site_writer: asyncio.StreamWriter,
    relay: _Relay,
) -> None:
    site_writer.write(_origin_form_head(request))
    await _drain(site_writer)
    await _forward_request_body(reader, site_writer, length, relay)
    await _until_the_first_ends(_carry_answer(site_reader, writer, relay), _until_the_client_closes(reader))


def _basic_authorization(username: str | None, password: str | None) -> bytes | None:
    if username is None:
        return None
    credentials = f"{unquote(username)}:{unquote(password or '')}".encode()

    return b"Proxy-Authorization: Basic " + base64.b64encode(credentials)


class PinnedTunnel:
    """A forward proxy on loopback that connects a browser only to addresses the fetch policy allows."""

    def __init__(self, policy: Callable[[], FetchPolicy]) -> None:
        self._policy = policy
        self._servers: list[asyncio.Server] = []
        self._port: int | None = None
        self._chained_ports: dict[str, int] = {}
        self._connections: set[asyncio.Task[None]] = set()
        self._refusals: OrderedDict[tuple[str, int], float] = OrderedDict()

    @property
    def port(self) -> int:
        """The loopback port every browser uses, for a context without a customer proxy.

        Raises:
            TunnelNotStartedError: when the tunnel is not running.
        """
        if self._port is None:
            raise TunnelNotStartedError("the browser tunnel is not running")

        return self._port

    def chained_proxy(self, proxy: Mapping[str, str]) -> dict[str, str]:
        """The tunnel listener that carries a context's connections on through *proxy*.

        Raises:
            TunnelNotStartedError: when no listener exists for that proxy.
        """
        port = self._chained_ports.get(proxy["server"])
        if port is None:
            raise TunnelNotStartedError(
                f"the browser tunnel has no listener for {urlsplit(proxy['server']).hostname}"
            )

        return {"server": f"http://{TUNNEL_HOST}:{port}"}

    async def start(self) -> None:
        """Open the listener and the chained listeners of the configured customer proxies."""
        if self._port is not None:
            return

        self._port = await self._listen(None)
        for proxy_url in {settings.PROXY_URL, settings.CRAWL_PROXY_URL} - {""}:
            self._chained_ports[proxy_url] = await self._listen(proxy_url)

    async def stop(self) -> None:
        """Close every listener, relay and socket, then forget the ports."""
        for server in self._servers:
            server.close()
        await asyncio.sleep(0)
        while self._connections:
            connections = list(self._connections)
            for connection in connections:
                connection.cancel()
            await asyncio.gather(*connections, return_exceptions=True)
        for server in self._servers:
            await server.wait_closed()
        self._servers.clear()
        self._port = None
        self._chained_ports.clear()

    def was_refused(self, url: str) -> bool:
        """True when the tunnel refused the host and port of *url* within the memory window."""
        key = _refusal_key(url)
        if key is None:
            return False
        refused_at = self._refusals.get(key)

        return refused_at is not None and time.monotonic() - refused_at <= _REFUSAL_MEMORY_SECONDS

    async def _listen(self, proxy_url: str | None) -> int:
        server = await asyncio.start_server(
            partial(self._handle, proxy_url), TUNNEL_HOST, 0, limit=_HEAD_LIMIT_BYTES
        )
        self._servers.append(server)
        port: int = server.sockets[0].getsockname()[1]

        return port

    def _remember_refusal(self, request: _Request) -> None:
        key = _host_and_port(request)
        self._refusals[key] = time.monotonic()
        self._refusals.move_to_end(key)
        while len(self._refusals) > _MAX_REMEMBERED_REFUSALS:
            self._refusals.popitem(last=False)

    async def _handle(
        self, proxy_url: str | None, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        task = asyncio.current_task()
        assert task is not None
        self._connections.add(task)
        try:
            await self._serve(proxy_url, reader, writer)
        except (OSError, TimeoutError, asyncio.IncompleteReadError, asyncio.LimitOverrunError) as exc:
            logger.debug("pinned_tunnel: connection ended early: %s", type(exc).__name__)
        finally:
            self._connections.discard(task)
            writer.close()

    async def _serve(
        self, proxy_url: str | None, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        async with asyncio.timeout(settings.BROWSER_TUNNEL_CONNECT_TIMEOUT_SECONDS):
            head = await reader.readuntil(_HEAD_END)
        if len(self._connections) > settings.BROWSER_TUNNEL_MAX_CONNECTIONS:
            logger.warning(
                "pinned_tunnel: above the cap of %d connections, answering 503",
                settings.BROWSER_TUNNEL_MAX_CONNECTIONS,
            )
            await self._answer(writer, _SERVICE_UNAVAILABLE)

            return
        request = _parse_head(head)
        if request is None:
            await self._answer(writer, _BAD_REQUEST)

            return
        length = 0
        if not request.is_tunnel:
            if _has_transfer_encoding(request):
                await self._answer(writer, _NOT_IMPLEMENTED)

                return
            framed_length = _content_length(request)
            if framed_length is None:
                await self._answer(writer, _BAD_REQUEST)

                return
            length = framed_length
        shown = address_without_query(request.check_url)
        try:
            target = await check_fetch_uri(request.check_url, self._policy())
        except UnsafeUriError as exc:
            self._remember_refusal(request)
            logger.warning("pinned_tunnel: refusing %s: %s", shown, exc)
            await self._answer(writer, _FORBIDDEN)

            return
        self._refusals.pop(_host_and_port(request), None)
        try:
            site_reader, site_writer = await self._open_site(request, target.addresses, proxy_url)
        except _SiteUnreachableError as exc:
            logger.warning("pinned_tunnel: %s: %s", shown, exc)
            await self._answer(writer, _BAD_GATEWAY)

            return
        relay = _Relay(shown)
        try:
            if request.is_tunnel:
                await _relay_tunnel(reader, writer, site_reader, site_writer, relay)
            else:
                await _relay_plain(request, length, reader, writer, site_reader, site_writer, relay)
        finally:
            site_writer.close()

    @staticmethod
    async def _answer(writer: asyncio.StreamWriter, status: str) -> None:
        writer.write(f"HTTP/1.1 {status}\r\nContent-Length: 0\r\nConnection: close\r\n\r\n".encode())
        await writer.drain()

    async def _open_site(
        self, request: _Request, addresses: tuple[str, ...], proxy_url: str | None
    ) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        if proxy_url is not None:
            return await self._open_through_proxy(request, proxy_url)
        failures: list[str] = []
        for address in addresses or (request.host,):
            try:
                async with asyncio.timeout(settings.BROWSER_TUNNEL_CONNECT_TIMEOUT_SECONDS):
                    return await asyncio.open_connection(address, request.port, limit=_HEAD_LIMIT_BYTES)
            except (OSError, TimeoutError) as exc:
                failures.append(f"{address}: {type(exc).__name__}")

        raise _SiteUnreachableError(f"no checked address answered ({', '.join(failures)})")

    async def _open_through_proxy(
        self, request: _Request, proxy_url: str
    ) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        proxy = urlsplit(proxy_url)
        if proxy.scheme not in _CHAINABLE_PROXY_SCHEMES:
            raise _SiteUnreachableError(f"proxy {proxy.hostname} cannot be chained, it is {proxy.scheme}")
        site_reader, site_writer = await self._connect_proxy(proxy.hostname or "", proxy.port, proxy.scheme)
        try:
            async with asyncio.timeout(settings.BROWSER_TUNNEL_CONNECT_TIMEOUT_SECONDS):
                site_writer.write(self._proxy_connect_head(request, proxy.username, proxy.password))
                await site_writer.drain()
                answer = await site_reader.readuntil(_HEAD_END)
        except (OSError, TimeoutError, asyncio.IncompleteReadError, asyncio.LimitOverrunError) as exc:
            site_writer.close()
            raise _SiteUnreachableError(
                f"proxy {proxy.hostname} did not answer: {type(exc).__name__}"
            ) from exc
        if _answer_status(answer) != 200:
            site_writer.close()
            raise _SiteUnreachableError(f"proxy {proxy.hostname} refused the tunnel")

        return site_reader, site_writer

    @staticmethod
    async def _connect_proxy(
        hostname: str, port: int | None, scheme: str
    ) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        target_port = port or _DEFAULT_PORTS[scheme]
        try:
            async with asyncio.timeout(settings.BROWSER_TUNNEL_CONNECT_TIMEOUT_SECONDS):
                return await asyncio.open_connection(
                    hostname, target_port, ssl=scheme == "https" or None, limit=_HEAD_LIMIT_BYTES
                )
        except (OSError, TimeoutError) as exc:
            raise _SiteUnreachableError(f"proxy {hostname} did not answer: {type(exc).__name__}") from exc

    @staticmethod
    def _proxy_connect_head(request: _Request, username: str | None, password: str | None) -> bytes:
        authority = request.authority
        lines = [f"CONNECT {authority} HTTP/1.1".encode(), f"Host: {authority}".encode()]
        authorization = _basic_authorization(username, password)
        if authorization is not None:
            lines.append(authorization)

        return _LINE_END.join([*lines, b"", b""])

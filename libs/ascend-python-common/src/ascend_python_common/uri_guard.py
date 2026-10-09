import asyncio
import ipaddress
import socket
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Generic, TypeVar
from urllib.parse import ParseResult, unquote, urljoin, urlparse

MAX_REDIRECT_HOPS = 10

_DEFAULT_PORTS = {"http": 80, "https": 443}
_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})

_T = TypeVar("_T")

AddrInfo = tuple[
    socket.AddressFamily,
    socket.SocketKind,
    int,
    str,
    tuple[str, int] | tuple[str, int, int, int],
]


class UnsafeUriError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class FetchPolicy:
    allowed_hosts: tuple[str, ...] = ()
    file_root: Path | None = None
    max_redirect_hops: int = MAX_REDIRECT_HOPS


@dataclass(frozen=True, slots=True)
class FetchTarget:
    url: str
    host: str | None
    port: int | None
    addresses: tuple[str, ...] = ()
    file_path: Path | None = None


@dataclass(frozen=True, slots=True)
class HopAnswer(Generic[_T]):
    status: int
    location: str | None
    answer: _T


def _is_blocked(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
    )


def _is_allowed(host: str, allowed: tuple[str, ...]) -> bool:
    lowered = host.lower()
    return any(entry.lower() == lowered for entry in allowed)


async def _lookup(host: str, port: int) -> list[AddrInfo]:
    try:
        return await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise UnsafeUriError("host does not resolve") from exc


def _check_file_uri(uri: str, url_path: str, policy: FetchPolicy) -> FetchTarget:
    root = policy.file_root
    if root is None:
        raise UnsafeUriError("file URI fetching is disabled")
    resolved_root = root.resolve()
    candidate = (resolved_root / unquote(url_path).lstrip("/\\")).resolve()
    if not candidate.is_relative_to(resolved_root):
        raise UnsafeUriError("file URI escapes its root")
    return FetchTarget(url=uri, host=None, port=None, file_path=candidate)


async def check_fetch_uri(uri: str, policy: FetchPolicy) -> FetchTarget:
    try:
        parsed = urlparse(uri)
    except ValueError as exc:
        raise UnsafeUriError("URI does not parse") from exc
    scheme = parsed.scheme.lower()
    if scheme == "file":
        return _check_file_uri(uri, parsed.path, policy)
    if scheme not in _DEFAULT_PORTS:
        raise UnsafeUriError(f"unsupported URI scheme: {scheme or 'none'}")
    return await _check_http_uri(uri, parsed, scheme, policy)


async def _check_http_uri(uri: str, parsed: ParseResult, scheme: str, policy: FetchPolicy) -> FetchTarget:
    if parsed.username is not None or parsed.password is not None:
        raise UnsafeUriError("user info in URI is not permitted")
    host = parsed.hostname
    if not host:
        raise UnsafeUriError("URI has no host")
    try:
        port = parsed.port
    except ValueError as exc:
        raise UnsafeUriError("invalid port in URI") from exc
    effective_port = port if port is not None else _DEFAULT_PORTS[scheme]
    if effective_port < 1 or effective_port > 65535:
        raise UnsafeUriError("invalid port in URI")
    if _is_allowed(host, policy.allowed_hosts):
        return FetchTarget(url=uri, host=host, port=effective_port)
    addresses = await _resolve_http_addresses(host, effective_port)
    return FetchTarget(url=uri, host=host, port=effective_port, addresses=addresses)


async def _resolve_http_addresses(host: str, port: int) -> tuple[str, ...]:
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None:
        if _is_blocked(literal):
            raise UnsafeUriError("URI resolves to a non-public address")
        return ()
    infos = await _lookup(host, port)
    if not infos:
        raise UnsafeUriError("host answers no address")
    addresses: list[str] = []
    for info in infos:
        raw = str(info[4][0])
        try:
            found = ipaddress.ip_address(raw)
        except ValueError as exc:
            raise UnsafeUriError("host answers a non-IP value") from exc
        if _is_blocked(found):
            raise UnsafeUriError("URI resolves to a non-public address")
        if raw not in addresses:
            addresses.append(raw)
    return tuple(addresses)


async def follow_guarded_redirects(
    first: FetchTarget,
    policy: FetchPolicy,
    send_hop: Callable[[FetchTarget], Awaitable[HopAnswer[_T]]],
) -> HopAnswer[_T]:
    current = first
    answer = await send_hop(current)
    hops = 0
    while answer.status in _REDIRECT_STATUSES and hops < policy.max_redirect_hops and answer.location:
        hop_policy = policy if policy.file_root is None else replace(policy, file_root=None)
        current = await check_fetch_uri(urljoin(current.url, answer.location), hop_policy)
        answer = await send_hop(current)
        hops += 1
    return answer

import contextlib
import ipaddress
import socket
from collections.abc import AsyncIterator, Iterator
from contextvars import ContextVar
from dataclasses import replace
from typing import Any
from urllib.parse import urljoin

import aiohttp
from aiohttp.abc import AbstractResolver, ResolveResult

from ascend_python_common.uri_guard import (
    FetchPolicy,
    FetchTarget,
    UnsafeUriError,
    check_fetch_uri,
)

_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})

current_pin: ContextVar[FetchTarget | None] = ContextVar("ascend_fetch_pin", default=None)


@contextlib.contextmanager
def pinned_scope(target: FetchTarget) -> Iterator[None]:
    token = current_pin.set(target)
    try:
        yield
    finally:
        current_pin.reset(token)


def _pinned_entry(host: str, address: str, port: int) -> ResolveResult:
    family = socket.AF_INET6 if ipaddress.ip_address(address).version == 6 else socket.AF_INET
    return {"hostname": host, "host": address, "port": port, "family": int(family), "proto": 0, "flags": 0}


class PinnedResolver(AbstractResolver):
    def __init__(self, resolver: AbstractResolver | None = None) -> None:
        self._wrapped = resolver or aiohttp.DefaultResolver()

    async def resolve(
        self,
        host: str,
        port: int = 0,
        family: socket.AddressFamily = socket.AF_INET,
    ) -> list[ResolveResult]:
        pin = current_pin.get()
        if pin is not None and pin.host is not None and pin.addresses and host.lower() == pin.host.lower():
            return [_pinned_entry(host, address, port) for address in pin.addresses]
        return await self._wrapped.resolve(host, port, family=family)

    async def close(self) -> None:
        await self._wrapped.close()


@contextlib.asynccontextmanager
async def guarded_get(
    session: aiohttp.ClientSession,
    uri: str,
    policy: FetchPolicy,
    **kwargs: Any,
) -> AsyncIterator[aiohttp.ClientResponse]:
    current = await check_fetch_uri(uri, policy)
    hops = 0
    while True:
        token = current_pin.set(current)
        try:
            response = await session.get(current.url, allow_redirects=False, **kwargs)
        finally:
            current_pin.reset(token)
        redirect = response.status in _REDIRECT_STATUSES and hops < policy.max_redirect_hops
        location = response.headers.get("Location")
        if not redirect or not location:
            try:
                yield response
            finally:
                response.release()
            return
        hop_policy = policy if policy.file_root is None else replace(policy, file_root=None)
        try:
            current = await check_fetch_uri(urljoin(current.url, location), hop_policy)
        except UnsafeUriError:
            response.release()
            raise
        response.release()
        hops += 1

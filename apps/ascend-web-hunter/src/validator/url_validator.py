import ipaddress
import logging
import socket
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from adblockparser import AdblockRules

from src.config.blocklist_loader import blocklist_loader

logger = logging.getLogger(__name__)

_SAFE_SCHEMES = {"http", "https"}
_DEFAULT_PORTS = {"http": 80, "https": 443}


class URLValidator:
    def __init__(self, rules: AdblockRules) -> None:
        self.rules = rules

    def should_block(self, url: str) -> bool:
        result: bool = self.rules.should_block(url)
        return result

    async def route_handler(self, route: Any) -> None:
        url = route.request.url
        if self.should_block(url):
            await route.abort()
        else:
            await route.continue_()


# Process-wide singleton: every WebReader (REST and MCP) shares this one instance,
# so a successful POST /api/v1/blocklist/refresh -- which reassigns `.rules` below --
# is picked up by every consumer immediately, without needing to reach into each
# WebReader individually.
url_validator = URLValidator(blocklist_loader.load_rules())


def is_safe_external_url(url: str) -> bool:
    """
    SSRF guard for endpoints that take user-supplied URLs.

    Returns False for non-http(s), loopback, private (RFC1918), link-local, multicast,
    and reserved address space. Callers should reject the request when this returns False.
    Pydantic's HttpUrl validates the scheme/structure but does not resolve the hostname,
    so an attacker can still pass http://127.0.0.1:6379 or http://169.254.169.254 (AWS IMDS).
    """
    try:
        parsed = urlparse(url)
    except Exception:
        return False

    if parsed.scheme.lower() not in _SAFE_SCHEMES:
        return False

    host = parsed.hostname
    if not host:
        return False

    return _is_safe_host(host)


def _is_safe_host(host: str) -> bool:
    """Resolve host and verify all returned IPs are public/routable."""
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return False

    return all(_is_public_address(str(info[4][0])) for info in infos)


def _is_public_address(address: str) -> bool:
    """True when *address* is a routable public IP, False for anything internal."""
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False

    return not (
        ip.is_loopback
        or ip.is_private
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def _is_ip_literal(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False

    return True


def _resolve_public_addresses(host: str, port: int) -> tuple[str, ...] | None:
    """Resolve *host* once and return its addresses, or None if any is not public."""
    try:
        infos = socket.getaddrinfo(host, port)
    except socket.gaierror:
        return None

    addresses: list[str] = []
    for info in infos:
        address = str(info[4][0])
        if not _is_public_address(address):
            return None
        if address not in addresses:
            addresses.append(address)

    if not addresses:
        return None

    return tuple(addresses)


@dataclass(frozen=True, slots=True)
class PinnedHost:
    """A host whose addresses were validated by the lookup that produced them."""

    host: str
    port: int
    addresses: tuple[str, ...]

    def curl_resolve_entries(self) -> list[str]:
        """Render the pin as libcurl CURLOPT_RESOLVE entries (`HOST:PORT:ADDR,ADDR`).

        Empty for a host that is already an IP literal: there is no name for a
        second lookup to answer differently, so there is nothing to pin.
        """
        if _is_ip_literal(self.host):
            return []

        rendered = ",".join(f"[{a}]" if ":" in a else a for a in self.addresses)

        return [f"{self.host}:{self.port}:{rendered}"]


def pin_safe_host(url: str) -> PinnedHost | None:
    """Validate *url*'s host and pin the addresses the same lookup returned.

    This is `is_safe_external_url` plus the answer it throws away: one
    `getaddrinfo` both authorises the host and supplies the addresses the
    transport must connect to, so no second resolution can stand between the
    check and the connection. Returns None when the URL is not http(s), carries
    no usable host or port, does not resolve, or resolves to any address that is
    not public. A None is a refusal to fetch, not a fall-through.
    """
    try:
        parsed = urlparse(url)
        host = parsed.hostname
        port = parsed.port
    except ValueError:
        return None

    scheme = parsed.scheme.lower()
    if scheme not in _SAFE_SCHEMES or not host:
        return None

    effective_port = port or _DEFAULT_PORTS[scheme]
    addresses = _resolve_public_addresses(host, effective_port)
    if addresses is None:
        logger.warning("SSRF guard: %s did not resolve to a public address", url)

        return None

    return PinnedHost(host=host, port=effective_port, addresses=addresses)

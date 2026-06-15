import ipaddress
import logging
import socket
from typing import Any
from urllib.parse import urlparse

from adblockparser import AdblockRules

logger = logging.getLogger(__name__)

_SAFE_SCHEMES = {"http", "https"}
_MAX_REDIRECTS = 10


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

    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0])
        except ValueError:
            return False
        if (
            ip.is_loopback
            or ip.is_private
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        ):
            return False
    return True


def validate_redirect_chain(history: list[Any]) -> bool:
    """
    Validate every redirect hop in a response history against the SSRF guard.

    Each item in *history* must expose a `url` attribute (curl_cffi Response objects
    do). Returns False as soon as any hop fails the guard; True if all are safe.

    FlareSolverr and Crawlee fetch out-of-process, so redirect chains for those tiers
    cannot be validated hop-by-hop here. Pre-dispatch validation (is_safe_external_url
    on the initial URL) is the defence for those tiers; residual risk is noted in
    docs/architecture/decisions/.
    """
    for resp in history:
        hop_url: str = getattr(resp, "url", "") or ""
        if hop_url and not is_safe_external_url(str(hop_url)):
            logger.warning("SSRF guard: redirect hop %s failed safety check", hop_url)
            return False
    return True

import ipaddress
import logging
import socket
from urllib.parse import urlparse

from adblockparser import AdblockRules

logger = logging.getLogger(__name__)

_SAFE_SCHEMES = {"http", "https"}


class URLValidator:
    def __init__(self, rules: AdblockRules):
        self.rules = rules

    def should_block(self, url: str) -> bool:
        return self.rules.should_block(url)

    async def route_handler(self, route) -> None:
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

    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return False

    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0])
        except ValueError:
            return False
        if (ip.is_loopback or ip.is_private or ip.is_link_local
                or ip.is_multicast or ip.is_reserved or ip.is_unspecified):
            return False
    return True

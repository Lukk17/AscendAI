"""The curl_cffi tier connects to the address the SSRF guard validated.

Change close-web-search-scraping-follow-ups, tasks 1.3 to 1.5. The attack these
tests describe is DNS rebinding: a name that answers with a public address while
it is being validated and with an internal address by the time the socket opens.

Change follow-relative-redirects, tasks 1.1 to 1.3, adds the relative-`Location`
cases: a hop is resolved against the URL that returned it before it is validated,
and the resolved absolute URL faces exactly the same guard an absolute one does.
"""

import socket
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from urllib.parse import urlparse

import pytest
from curl_cffi import CurlOpt

from src.reader.strategies.curl_cffi_fetcher import fetch_with_curl_cffi

_PUBLIC = "93.184.216.34"
_METADATA = "169.254.169.254"
_URL = "https://rebind.example/page"
_HOP_URL = "https://hop.example/page"
_HTML = "<html><body>the page</body></html>"


class _RebindingResolver:
    """A getaddrinfo stand-in: public on the first answer, internal on every later one."""

    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, host: str, port: object = None, *_args: object, **_kwargs: object) -> list[tuple]:
        self.calls += 1
        address = _PUBLIC if self.calls == 1 else _METADATA

        return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", (address, 0))]


class _FixedResolver:
    """A getaddrinfo stand-in that always answers with one address."""

    def __init__(self, address: str) -> None:
        self.address = address
        self.calls = 0

    def __call__(self, host: str, port: object = None, *_args: object, **_kwargs: object) -> list[tuple]:
        self.calls += 1

        return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", (self.address, 0))]


class _HostResolver:
    """A getaddrinfo stand-in that answers per host, and refuses an unknown one."""

    def __init__(self, addresses: dict[str, str]) -> None:
        self.addresses = addresses
        self.calls = 0

    def __call__(self, host: str, port: object = None, *_args: object, **_kwargs: object) -> list[tuple]:
        self.calls += 1
        address = self.addresses.get(host)
        if address is None:
            raise socket.gaierror(f"unknown host {host}")

        return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", (address, 0))]


class _PinAwareSession:
    """An AsyncSession stand-in that picks its connect address the way libcurl does.

    libcurl consults its CURLOPT_RESOLVE list before the system resolver, so a
    request whose host and port carry a pin connects to the pinned address and
    never asks the resolver again. With no matching entry it resolves the name
    itself, which is where a rebound answer wins.
    """

    def __init__(self, resolver: Any, responses: list[Any]) -> None:
        self.curl_options: dict[Any, Any] = {}
        self.connected_to: list[str] = []
        self.requested: list[str] = []
        self._resolver = resolver
        self._responses = list(responses)

    async def __aenter__(self) -> "_PinAwareSession":
        return self

    async def __aexit__(self, *_exc: object) -> bool:
        return False

    async def get(self, url: str, **_kwargs: object) -> Any:
        parsed = urlparse(url)
        host = parsed.hostname or ""
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        self.requested.append(url)
        self.connected_to.append(self._connect_address(host, port))

        return self._responses.pop(0)

    def _connect_address(self, host: str, port: int) -> str:
        prefix = f"{host}:{port}:"
        for entry in self.curl_options.get(CurlOpt.RESOLVE, []):
            if entry.startswith(prefix):
                return entry[len(prefix) :].split(",")[0]

        return str(self._resolver(host, port)[0][4][0])


def _ok_response() -> MagicMock:
    response = MagicMock()
    response.status_code = 200
    response.headers = {}
    response.text = _HTML
    response.raise_for_status = MagicMock()

    return response


def _redirect_response(location: str) -> MagicMock:
    response = MagicMock()
    response.status_code = 302
    response.headers = {"location": location}
    response.text = ""
    response.raise_for_status = MagicMock()

    return response


def _patched(session: _PinAwareSession, resolver: Any) -> list[Any]:
    return [
        patch("src.reader.strategies.curl_cffi_fetcher.requests.AsyncSession", return_value=session),
        patch("src.validator.url_validator.socket.getaddrinfo", new=resolver),
        patch(
            "src.reader.strategies.curl_cffi_fetcher.cookie_manager.get_flat_cookies",
            new=AsyncMock(return_value={}),
        ),
        patch(
            "src.reader.strategies.curl_cffi_fetcher.cookie_manager.get_user_agent",
            new=AsyncMock(return_value=None),
        ),
    ]


async def _fetch(session: _PinAwareSession, resolver: Any, url: str = _URL) -> str:
    patches = _patched(session, resolver)
    for entered in patches:
        entered.start()
    try:
        return await fetch_with_curl_cffi(url, lambda: "UA", "test")
    finally:
        for entered in patches:
            entered.stop()


@pytest.mark.asyncio
async def test_a_name_rebound_after_validation_is_never_connected_to():
    # given
    resolver = _RebindingResolver()
    session = _PinAwareSession(resolver, [_ok_response()])

    # when
    html = await _fetch(session, resolver)

    # then
    assert html == _HTML
    assert session.curl_options[CurlOpt.RESOLVE] == [f"rebind.example:443:{_PUBLIC}"]
    assert session.connected_to == [_PUBLIC]
    assert _METADATA not in session.connected_to
    assert resolver.calls == 1, "the connect re-resolved the name instead of using the validated address"


@pytest.mark.asyncio
async def test_without_a_pin_the_rebound_address_is_the_one_that_connects():
    """The harness itself must be able to demonstrate the attack, or the test above proves nothing."""
    # given
    resolver = _RebindingResolver()
    session = _PinAwareSession(resolver, [_ok_response()])
    resolver("rebind.example", 443)

    # when
    await session.get(_URL)

    # then
    assert session.connected_to == [_METADATA]


@pytest.mark.asyncio
async def test_a_host_that_resolves_to_an_internal_address_is_never_requested():
    # given
    resolver = _FixedResolver(_METADATA)
    session = _PinAwareSession(resolver, [_ok_response()])

    # when
    html = await _fetch(session, resolver)

    # then
    assert html == ""
    assert session.connected_to == []


@pytest.mark.asyncio
async def test_every_redirect_hop_connects_to_its_own_validated_address():
    # given
    resolver = _FixedResolver(_PUBLIC)
    session = _PinAwareSession(resolver, [_redirect_response(_HOP_URL), _ok_response()])

    # when
    html = await _fetch(session, resolver)

    # then
    assert html == _HTML
    assert session.connected_to == [_PUBLIC, _PUBLIC]
    assert resolver.calls == 2, "one resolution per hop, and none of them at connect time"


@pytest.mark.asyncio
async def test_the_pin_is_replaced_per_hop_rather_than_accumulated():
    # given
    resolver = _FixedResolver(_PUBLIC)
    session = _PinAwareSession(resolver, [_redirect_response(_HOP_URL), _ok_response()])

    # when
    await _fetch(session, resolver)

    # then
    assert session.curl_options[CurlOpt.RESOLVE] == [f"hop.example:443:{_PUBLIC}"]


@pytest.mark.asyncio
async def test_a_root_relative_location_is_resolved_against_the_hop_that_returned_it():
    # given
    resolver = _FixedResolver(_PUBLIC)
    session = _PinAwareSession(resolver, [_redirect_response("/article"), _ok_response()])

    # when
    html = await _fetch(session, resolver)

    # then
    assert html == _HTML
    assert session.requested == [_URL, "https://rebind.example/article"]
    assert session.connected_to == [_PUBLIC, _PUBLIC]


@pytest.mark.asyncio
async def test_a_path_relative_location_is_resolved_against_the_previous_hop_not_the_first_url():
    # given
    resolver = _FixedResolver(_PUBLIC)
    responses = [
        _redirect_response("/docs/intro"),
        _redirect_response("../index.html"),
        _ok_response(),
    ]
    session = _PinAwareSession(resolver, responses)

    # when
    html = await _fetch(session, resolver)

    # then
    assert html == _HTML
    assert session.requested == [
        _URL,
        "https://rebind.example/docs/intro",
        "https://rebind.example/index.html",
    ]


@pytest.mark.asyncio
async def test_a_protocol_relative_location_takes_the_scheme_of_the_hop_that_returned_it():
    # given
    resolver = _HostResolver({"rebind.example": _PUBLIC, "hop.example": _PUBLIC})
    session = _PinAwareSession(resolver, [_redirect_response("//hop.example/page"), _ok_response()])

    # when
    html = await _fetch(session, resolver)

    # then
    assert html == _HTML
    assert session.requested == [_URL, _HOP_URL]
    assert session.curl_options[CurlOpt.RESOLVE] == [f"hop.example:443:{_PUBLIC}"]


@pytest.mark.asyncio
async def test_a_protocol_relative_location_to_an_internal_host_is_refused():
    # given
    resolver = _HostResolver({"rebind.example": _PUBLIC, "evil.example": _METADATA})
    session = _PinAwareSession(resolver, [_redirect_response("//evil.example/page"), _ok_response()])

    # when
    html = await _fetch(session, resolver)

    # then
    assert html == ""
    assert session.requested == [_URL]
    assert session.connected_to == [_PUBLIC]


@pytest.mark.asyncio
async def test_a_relative_location_whose_host_has_rebound_is_still_refused():
    # given
    resolver = _RebindingResolver()
    session = _PinAwareSession(resolver, [_redirect_response("/article"), _ok_response()])

    # when
    html = await _fetch(session, resolver)

    # then
    assert html == ""
    assert session.requested == [_URL]
    assert _METADATA not in session.connected_to

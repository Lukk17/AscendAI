"""Tests for connect-time address pinning (change close-web-search-scraping-follow-ups, task 1.1/1.2)."""

import socket
from unittest.mock import patch

from src.validator.url_validator import PinnedHost, pin_safe_host

_PUBLIC_V4 = "93.184.216.34"
_PUBLIC_V4_ALT = "93.184.216.35"
_PUBLIC_V6 = "2606:2800:220:1:248:1893:25c8:1946"


def _addr(ip: str, family: int = socket.AF_INET) -> tuple:
    return (family, 0, 0, "", (ip, 0))


# ---------------------------------------------------------------------------
# pin_safe_host
# ---------------------------------------------------------------------------


def test_pins_the_addresses_the_same_lookup_validated():
    with patch("src.validator.url_validator.socket.getaddrinfo", return_value=[_addr(_PUBLIC_V4)]):
        pinned = pin_safe_host("https://example.com/article")

    assert pinned == PinnedHost(host="example.com", port=443, addresses=(_PUBLIC_V4,))


def test_defaults_to_port_80_for_http():
    with patch("src.validator.url_validator.socket.getaddrinfo", return_value=[_addr(_PUBLIC_V4)]):
        pinned = pin_safe_host("http://example.com/")

    assert pinned is not None
    assert pinned.port == 80


def test_uses_the_explicit_port_when_the_url_carries_one():
    with patch("src.validator.url_validator.socket.getaddrinfo", return_value=[_addr(_PUBLIC_V4)]):
        pinned = pin_safe_host("https://example.com:8443/")

    assert pinned is not None
    assert pinned.port == 8443


def test_resolves_against_the_port_it_pins():
    with patch("src.validator.url_validator.socket.getaddrinfo", return_value=[_addr(_PUBLIC_V4)]) as resolve:
        pin_safe_host("https://example.com/")

    resolve.assert_called_once_with("example.com", 443)


def test_keeps_every_public_address_the_lookup_returned():
    answers = [_addr(_PUBLIC_V4), _addr(_PUBLIC_V4_ALT)]
    with patch("src.validator.url_validator.socket.getaddrinfo", return_value=answers):
        pinned = pin_safe_host("https://example.com/")

    assert pinned is not None
    assert pinned.addresses == (_PUBLIC_V4, _PUBLIC_V4_ALT)


def test_deduplicates_the_same_address_returned_twice():
    answers = [_addr(_PUBLIC_V4), _addr(_PUBLIC_V4)]
    with patch("src.validator.url_validator.socket.getaddrinfo", return_value=answers):
        pinned = pin_safe_host("https://example.com/")

    assert pinned is not None
    assert pinned.addresses == (_PUBLIC_V4,)


def test_refuses_a_loopback_answer():
    with patch("src.validator.url_validator.socket.getaddrinfo", return_value=[_addr("127.0.0.1")]):
        assert pin_safe_host("http://localhost/") is None


def test_refuses_a_private_answer():
    with patch("src.validator.url_validator.socket.getaddrinfo", return_value=[_addr("192.168.1.1")]):
        assert pin_safe_host("http://router/") is None


def test_refuses_the_metadata_address():
    with patch("src.validator.url_validator.socket.getaddrinfo", return_value=[_addr("169.254.169.254")]):
        assert pin_safe_host("http://imds/") is None


def test_refuses_when_one_of_several_answers_is_private():
    answers = [_addr(_PUBLIC_V4), _addr("10.0.0.5")]
    with patch("src.validator.url_validator.socket.getaddrinfo", return_value=answers):
        assert pin_safe_host("https://example.com/") is None


def test_refuses_an_answer_that_is_not_an_address():
    with patch("src.validator.url_validator.socket.getaddrinfo", return_value=[_addr("not-an-address")]):
        assert pin_safe_host("https://example.com/") is None


def test_refuses_a_host_that_does_not_resolve():
    with patch("src.validator.url_validator.socket.getaddrinfo", side_effect=socket.gaierror):
        assert pin_safe_host("https://nowhere.invalid/") is None


def test_refuses_a_resolution_with_no_answers_at_all():
    with patch("src.validator.url_validator.socket.getaddrinfo", return_value=[]):
        assert pin_safe_host("https://example.com/") is None


def test_refuses_a_non_http_scheme():
    assert pin_safe_host("ftp://example.com/") is None


def test_refuses_a_url_with_no_host():
    assert pin_safe_host("http:///article") is None


def test_refuses_a_url_whose_port_cannot_be_parsed():
    assert pin_safe_host("http://example.com:not-a-port/") is None


# ---------------------------------------------------------------------------
# PinnedHost.curl_resolve_entries
# ---------------------------------------------------------------------------


def test_resolve_entry_names_the_host_the_port_and_the_address():
    pinned = PinnedHost(host="example.com", port=443, addresses=(_PUBLIC_V4,))

    assert pinned.curl_resolve_entries() == [f"example.com:443:{_PUBLIC_V4}"]


def test_resolve_entry_lists_every_pinned_address():
    pinned = PinnedHost(host="example.com", port=80, addresses=(_PUBLIC_V4, _PUBLIC_V4_ALT))

    assert pinned.curl_resolve_entries() == [f"example.com:80:{_PUBLIC_V4},{_PUBLIC_V4_ALT}"]


def test_resolve_entry_brackets_an_ipv6_address():
    pinned = PinnedHost(host="example.com", port=443, addresses=(_PUBLIC_V6,))

    assert pinned.curl_resolve_entries() == [f"example.com:443:[{_PUBLIC_V6}]"]


def test_no_resolve_entry_for_a_host_that_is_already_an_address():
    pinned = PinnedHost(host=_PUBLIC_V4, port=443, addresses=(_PUBLIC_V4,))

    assert pinned.curl_resolve_entries() == []


def test_no_resolve_entry_for_a_host_that_is_already_an_ipv6_address():
    pinned = PinnedHost(host=_PUBLIC_V6, port=443, addresses=(_PUBLIC_V6,))

    assert pinned.curl_resolve_entries() == []

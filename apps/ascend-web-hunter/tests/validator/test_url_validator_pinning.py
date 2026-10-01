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
    # when
    with patch("src.validator.url_validator.socket.getaddrinfo", return_value=[_addr(_PUBLIC_V4)]):
        pinned = pin_safe_host("https://example.com/article")

    # then
    assert pinned == PinnedHost(host="example.com", port=443, addresses=(_PUBLIC_V4,))


def test_defaults_to_port_80_for_http():
    # when
    with patch("src.validator.url_validator.socket.getaddrinfo", return_value=[_addr(_PUBLIC_V4)]):
        pinned = pin_safe_host("http://example.com/")

    # then
    assert pinned is not None
    assert pinned.port == 80


def test_uses_the_explicit_port_when_the_url_carries_one():
    # when
    with patch("src.validator.url_validator.socket.getaddrinfo", return_value=[_addr(_PUBLIC_V4)]):
        pinned = pin_safe_host("https://example.com:8443/")

    # then
    assert pinned is not None
    assert pinned.port == 8443


def test_resolves_against_the_port_it_pins():
    # when
    with patch("src.validator.url_validator.socket.getaddrinfo", return_value=[_addr(_PUBLIC_V4)]) as resolve:
        pin_safe_host("https://example.com/")

    # then
    resolve.assert_called_once_with("example.com", 443)


def test_keeps_every_public_address_the_lookup_returned():
    # given
    answers = [_addr(_PUBLIC_V4), _addr(_PUBLIC_V4_ALT)]

    # when
    with patch("src.validator.url_validator.socket.getaddrinfo", return_value=answers):
        pinned = pin_safe_host("https://example.com/")

    # then
    assert pinned is not None
    assert pinned.addresses == (_PUBLIC_V4, _PUBLIC_V4_ALT)


def test_deduplicates_the_same_address_returned_twice():
    # given
    answers = [_addr(_PUBLIC_V4), _addr(_PUBLIC_V4)]

    # when
    with patch("src.validator.url_validator.socket.getaddrinfo", return_value=answers):
        pinned = pin_safe_host("https://example.com/")

    # then
    assert pinned is not None
    assert pinned.addresses == (_PUBLIC_V4,)


def test_refuses_a_loopback_answer():
    # given
    with patch("src.validator.url_validator.socket.getaddrinfo", return_value=[_addr("127.0.0.1")]):
        # when / then
        assert pin_safe_host("http://localhost/") is None


def test_refuses_a_private_answer():
    # given
    with patch("src.validator.url_validator.socket.getaddrinfo", return_value=[_addr("192.168.1.1")]):
        # when / then
        assert pin_safe_host("http://router/") is None


def test_refuses_the_metadata_address():
    # given
    with patch("src.validator.url_validator.socket.getaddrinfo", return_value=[_addr("169.254.169.254")]):
        # when / then
        assert pin_safe_host("http://imds/") is None


def test_refuses_when_one_of_several_answers_is_private():
    # given
    answers = [_addr(_PUBLIC_V4), _addr("10.0.0.5")]
    with patch("src.validator.url_validator.socket.getaddrinfo", return_value=answers):
        # when / then
        assert pin_safe_host("https://example.com/") is None


def test_refuses_an_answer_that_is_not_an_address():
    # given
    with patch("src.validator.url_validator.socket.getaddrinfo", return_value=[_addr("not-an-address")]):
        # when / then
        assert pin_safe_host("https://example.com/") is None


def test_refuses_a_host_that_does_not_resolve():
    # given
    with patch("src.validator.url_validator.socket.getaddrinfo", side_effect=socket.gaierror):
        # when / then
        assert pin_safe_host("https://nowhere.invalid/") is None


def test_refuses_a_resolution_with_no_answers_at_all():
    # given
    with patch("src.validator.url_validator.socket.getaddrinfo", return_value=[]):
        # when / then
        assert pin_safe_host("https://example.com/") is None


def test_refuses_a_non_http_scheme():
    # when / then
    assert pin_safe_host("ftp://example.com/") is None


def test_refuses_a_url_with_no_host():
    # when / then
    assert pin_safe_host("http:///article") is None


def test_refuses_a_url_whose_port_cannot_be_parsed():
    # when / then
    assert pin_safe_host("http://example.com:not-a-port/") is None


# ---------------------------------------------------------------------------
# PinnedHost.curl_resolve_entries
# ---------------------------------------------------------------------------


def test_resolve_entry_names_the_host_the_port_and_the_address():
    # when
    pinned = PinnedHost(host="example.com", port=443, addresses=(_PUBLIC_V4,))

    # then
    assert pinned.curl_resolve_entries() == [f"example.com:443:{_PUBLIC_V4}"]


def test_resolve_entry_lists_every_pinned_address():
    # when
    pinned = PinnedHost(host="example.com", port=80, addresses=(_PUBLIC_V4, _PUBLIC_V4_ALT))

    # then
    assert pinned.curl_resolve_entries() == [f"example.com:80:{_PUBLIC_V4},{_PUBLIC_V4_ALT}"]


def test_resolve_entry_brackets_an_ipv6_address():
    # when
    pinned = PinnedHost(host="example.com", port=443, addresses=(_PUBLIC_V6,))

    # then
    assert pinned.curl_resolve_entries() == [f"example.com:443:[{_PUBLIC_V6}]"]


def test_no_resolve_entry_for_a_host_that_is_already_an_address():
    # when
    pinned = PinnedHost(host=_PUBLIC_V4, port=443, addresses=(_PUBLIC_V4,))

    # then
    assert pinned.curl_resolve_entries() == []


def test_no_resolve_entry_for_a_host_that_is_already_an_ipv6_address():
    # when
    pinned = PinnedHost(host=_PUBLIC_V6, port=443, addresses=(_PUBLIC_V6,))

    # then
    assert pinned.curl_resolve_entries() == []

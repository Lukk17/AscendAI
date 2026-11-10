import time

import pytest

from src.observability.safe_address import (
    MAX_EXCEPTION_TEXT_LENGTH,
    address_without_query,
    exception_text_without_queries,
)

_ONE_MEGABYTE = 1_000_000

_SCAN_BUDGET_SECONDS = 1.0


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (
            "https://Example.COM/r/programming/?code=SECRET#access_token=SECRET",
            "https://example.com/r/programming/",
        ),
        ("HTTPS://user:pass@example.com:8443/login?next=%2F", "https://example.com:8443/login"),
        ("https://x.com:443@y.com/", "https://y.com/"),
        ("http://[::1]:7031/wall", "http://[::1]:7031/wall"),
        ("https://nowsecure.nl", "https://nowsecure.nl"),
        ("https://example.com/app;jsessionid=abc?x=1", "https://example.com/app"),
        ("redis://host/0?password=x", "redis://host/0"),
    ],
)
def test_address_without_query_keeps_scheme_host_port_and_path_only(url: str, expected: str) -> None:
    # when
    address = address_without_query(url)

    # then
    assert address == expected


@pytest.mark.parametrize(
    "url", ["https://example.com:99999/x?sig=1", "https://[bad/x?sig=1"], ids=["port", "ipv6"]
)
def test_address_without_query_answers_a_marker_for_an_address_it_cannot_read(url: str) -> None:
    # when
    address = address_without_query(url)

    # then
    assert address == "<unreadable address>"


def test_exception_text_keeps_the_reason_and_drops_every_query_and_user_info() -> None:
    # given
    exc = RuntimeError(
        "net::ERR_CONNECTION_REFUSED at https://user:pw@example.com/doc?X-Amz-Signature=secret\n"
        'navigating to "HTTP://Example.com/a;jsessionid=abc?token=secret", waiting until "load"'
    )

    # when
    text = exception_text_without_queries(exc)

    # then
    assert text == (
        "net::ERR_CONNECTION_REFUSED at https://example.com/doc\n"
        'navigating to "http://example.com/a", waiting until "load"'
    )


def test_exception_text_strips_user_info_of_any_other_scheme() -> None:
    # when
    text = exception_text_without_queries(OSError("proxy socks5://user:pw@proxy:1080 refused"))

    # then
    assert text == "proxy socks5://proxy:1080 refused"


def test_exception_text_of_an_exception_without_a_message_is_its_type() -> None:
    # when
    text = exception_text_without_queries(TimeoutError())

    # then
    assert text == "TimeoutError"


@pytest.mark.parametrize(
    "message",
    [
        "x" * _ONE_MEGABYTE,
        "https://" + "a" * _ONE_MEGABYTE,
        "http://a " * (_ONE_MEGABYTE // 9),
        "h" * _ONE_MEGABYTE,
        "a://" * (_ONE_MEGABYTE // 4),
    ],
    ids=["plain-text", "one-address", "many-addresses", "scheme-letters", "repeated-schemes"],
)
def test_exception_text_of_one_megabyte_is_capped_inside_the_time_limit(message: str) -> None:
    # given
    started = time.perf_counter()

    # when
    text = exception_text_without_queries(RuntimeError(message))

    # then
    assert time.perf_counter() - started < _SCAN_BUDGET_SECONDS
    assert len(text) <= MAX_EXCEPTION_TEXT_LENGTH


def test_exception_text_cut_inside_a_query_keeps_no_query() -> None:
    # given
    url = "https://example.com/doc?X-Amz-Signature="
    message = "x" * (MAX_EXCEPTION_TEXT_LENGTH - len(url)) + url + "secret"

    # when
    text = exception_text_without_queries(RuntimeError(message))

    # then
    assert "X-Amz-Signature" not in text
    assert text.endswith("https://example.com/doc")

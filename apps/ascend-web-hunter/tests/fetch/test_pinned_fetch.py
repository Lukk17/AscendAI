import asyncio
from typing import Any
from unittest.mock import MagicMock

import pytest
from ascend_python_common.uri_guard import FetchTarget, HopAnswer
from curl_cffi import CurlOpt

from src.fetch import pinned_fetch
from src.fetch.pinned_fetch import (
    cookies_stay_on_site,
    leave_bodies_undecoded,
    make_send_hop,
    stopping_hops,
)
from src.reader.cloudflare.cookie_manager import CookieManager


class _Answer:
    def __init__(self, name: str, events: list[str]) -> None:
        self.quit_now = MagicMock()
        self._name = name
        self._events = events

    async def aclose(self) -> None:
        self._events.append(f"closed {self._name}")


def _target(url: str) -> FetchTarget:
    return FetchTarget(url=url, host="example.com", port=443, addresses=("93.184.216.34",))


@pytest.mark.asyncio
async def test_a_redirect_answer_is_stopped_before_the_next_hop_is_sent() -> None:
    # given
    events: list[str] = []
    answers = {"first": _Answer("first", events), "second": _Answer("second", events)}

    async def send_hop(target: FetchTarget) -> HopAnswer[Any]:
        events.append(f"sent {target.url}")
        return HopAnswer(status=302, location=None, answer=answers[target.url])

    # when
    async with stopping_hops(send_hop) as tracked_hop:
        await tracked_hop(_target("first"))
        await tracked_hop(_target("second"))
        during = list(events)

    # then
    assert during == ["sent first", "closed first", "sent second"]
    assert events == [*during, "closed second"]
    answers["first"].quit_now.set.assert_called_once_with()
    answers["second"].quit_now.set.assert_called_once_with()


@pytest.mark.asyncio
async def test_a_hop_that_fails_leaves_nothing_more_to_stop_on_exit() -> None:
    # given a first answer and a second hop that fails
    events: list[str] = []
    answer = _Answer("first", events)

    async def send_hop(target: FetchTarget) -> HopAnswer[Any]:
        if target.url == "second":
            raise RuntimeError("down")
        return HopAnswer(status=302, location=None, answer=answer)

    async def two_hops() -> None:
        async with stopping_hops(send_hop) as tracked_hop:
            await tracked_hop(_target("first"))
            await tracked_hop(_target("second"))

    # when
    with pytest.raises(RuntimeError, match="down"):
        await two_hops()

    # then the first answer was stopped once, before the failing hop
    assert events == ["closed first"]
    answer.quit_now.set.assert_called_once_with()


@pytest.mark.asyncio
async def test_leaving_without_a_hop_stops_nothing() -> None:
    # given
    async def send_hop(target: FetchTarget) -> HopAnswer[Any]:
        raise AssertionError(f"no hop expected, got {target.url}")

    # when / then
    async with stopping_hops(send_hop):
        pass


def test_leave_bodies_undecoded_turns_off_libcurl_content_decoding() -> None:
    # given
    session = MagicMock(curl_options={})

    # when
    leave_bodies_undecoded(session)

    # then
    assert session.curl_options == {CurlOpt.HTTP_CONTENT_DECODING: 0}


@pytest.mark.parametrize(
    ("first_url", "hop_url", "allowed"),
    [
        ("https://shop.example.com/a", "https://shop.example.com/b", True),
        ("https://shop.example.com/a", "https://www.example.com/b", True),
        ("https://shop.example.com/a", "https://SHOP.EXAMPLE.COM/b", True),
        ("https://example.com/a", "https://other.example.org/b", False),
        ("https://example.com/a", "https://example.com.evil.org/b", False),
        ("https://example.com/a", "https://user@evil.org/@example.com", False),
        ("https://example.com/a", "http://example.com/b", False),
        ("http://fake-site:8080/a", "http://fake-site:8080/b", True),
        ("http://fake-site:8080/a", "https://fake-site:8080/b", True),
        ("http://fake-site:8080/a", "http://other-site:8080/b", False),
        ("https://93.184.216.34/a", "https://93.184.216.34/b", True),
        ("https://93.184.216.34/a", "https://93.184.216.35/b", False),
    ],
)
def test_cookies_stay_on_the_site_and_scheme_of_the_first_url(
    first_url: str, hop_url: str, allowed: bool
) -> None:
    # when
    check = cookies_stay_on_site(first_url)

    # then
    assert check(hop_url) is allowed


@pytest.mark.parametrize(
    ("first_url", "hop_url", "allowed"),
    [
        ("https://foo.github.io/a", "https://bar.github.io/b", False),
        ("https://foo.github.io/a", "https://foo.github.io/b", True),
        ("https://foo.github.io/a", "https://www.foo.github.io/b", True),
        ("https://github.io/a", "https://foo.github.io/b", False),
        ("https://login.example.com/a", "https://www.example.com/b", True),
        ("https://www.example.co.uk/a", "https://shop.example.co.uk/b", True),
        ("http://127.0.0.1:8080/a", "http://127.0.0.1:9090/b", True),
        ("http://127.0.0.1/a", "http://127.0.0.2/b", False),
    ],
)
def test_cookies_stay_on_one_owner_of_a_private_suffix(first_url: str, hop_url: str, allowed: bool) -> None:
    # when
    check = cookies_stay_on_site(first_url)

    # then
    assert check(hop_url) is allowed


def test_the_session_key_domain_still_ignores_the_private_suffix_list() -> None:
    # when
    domain = CookieManager.registrable_domain("https://foo.github.io/a")

    # then
    assert domain == "github.io"


class _HopSession:
    def __init__(self) -> None:
        self.curl_options: dict[Any, Any] = {}
        self.cookies = MagicMock()
        self.sent: list[dict[str, str]] = []

    async def get(self, _url: str, **kwargs: Any) -> Any:
        self.sent.append(kwargs["cookies"])
        return MagicMock(status_code=200, headers={})


@pytest.mark.asyncio
async def test_a_hop_the_check_allows_carries_the_cookies_and_keeps_the_session_jar() -> None:
    # given
    session = _HopSession()
    send_hop = make_send_hop(session, {}, {"sid": "s1"}, 5.0, {}, lambda _url: True)

    # when
    await send_hop(_target("https://example.com/a"))

    # then
    assert session.sent == [{"sid": "s1"}]
    session.cookies.clear.assert_not_called()


@pytest.mark.asyncio
async def test_a_hop_the_check_refuses_gets_no_cookies_and_the_session_jar_is_cleared() -> None:
    # given
    session = _HopSession()
    send_hop = make_send_hop(session, {}, {"sid": "s1"}, 5.0, {}, lambda _url: False)

    # when
    await send_hop(_target("https://other.example.org/b"))

    # then
    assert session.sent == [{}]
    session.cookies.clear.assert_called_once_with()


@pytest.mark.asyncio
async def test_a_hop_without_stored_cookies_leaves_the_session_jar_alone() -> None:
    # given
    session = _HopSession()
    send_hop = make_send_hop(session, {}, {}, 5.0, {}, lambda _url: False)

    # when
    await send_hop(_target("https://other.example.org/b"))

    # then
    assert session.sent == [{}]
    session.cookies.clear.assert_not_called()


async def test_stopping_a_stream_waits_only_the_grace_period_for_a_silent_server(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # given a stream whose close never returns
    monkeypatch.setattr(pinned_fetch, "_STREAM_STOP_GRACE_SECONDS", 0.01)

    async def silent() -> None:
        await asyncio.Event().wait()

    response = MagicMock()
    response.quit_now = asyncio.Event()
    response.aclose = silent

    # when
    async with asyncio.timeout(5):
        await pinned_fetch.stop_stream(response)

    # then
    assert response.quit_now.is_set()


def test_the_stream_stop_grace_period_is_one_second() -> None:
    # then
    assert pinned_fetch._STREAM_STOP_GRACE_SECONDS == 1.0

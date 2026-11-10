import asyncio
import gzip
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from ascend_python_common.uri_guard import FetchTarget
from curl_cffi import CurlOpt

from src.config.config import settings
from src.crawl.fetcher import ConditionalProbe, RobotsFetch, conditional_probe, fetch_robots_txt


def _target(url: str = "https://example.com/page") -> FetchTarget:
    return FetchTarget(url=url, host="example.com", port=443, addresses=("93.184.216.34",))


@pytest.fixture(autouse=True)
def stored_session() -> Any:
    sessions = MagicMock()
    sessions.get_flat_cookies = AsyncMock(return_value={})
    sessions.get_user_agent = AsyncMock(return_value=None)
    with patch("src.crawl.fetcher.cookie_manager", sessions):
        yield sessions


class _FakeSession:
    def __init__(self, response: Any, *more: Any) -> None:
        self._responses = [response, *more]
        self.sent_headers: dict[str, str] | None = None
        self.sent_kwargs: dict[str, Any] = {}
        self.sent_urls: list[str] = []
        self.curl_options: dict[Any, Any] = {}
        self.cookies = MagicMock()

    async def __aenter__(self) -> "_FakeSession":
        return self

    async def __aexit__(self, *args: Any) -> bool:
        return False

    async def get(self, url: str, **kwargs: Any) -> Any:
        self.sent_headers = kwargs.get("headers", {})
        self.sent_kwargs = kwargs
        self.sent_urls.append(url)
        return self._responses[min(len(self.sent_urls), len(self._responses)) - 1]


def _response(status: int, headers: dict[str, str] | None = None) -> MagicMock:
    response = MagicMock()
    response.status_code = status
    response.headers = headers or {}
    response.aclose = AsyncMock()
    return response


def _assert_stopped_unread(response: MagicMock) -> None:
    response.quit_now.set.assert_called_once_with()
    response.aclose.assert_awaited_once_with()
    response.aiter_content.assert_not_called()


async def test_probe_that_never_gets_an_answer_gives_up_at_the_extract_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # given
    monkeypatch.setattr(settings, "EXTRACT_TIMEOUT", 0.01)
    session = _FakeSession(_response(200))

    async def silent(_url: str, **_kwargs: Any) -> Any:
        await asyncio.Event().wait()

    monkeypatch.setattr(session, "get", silent)

    # when
    with (
        patch("src.crawl.fetcher.check_fetch_uri", new=AsyncMock(return_value=_target())),
        patch("src.crawl.fetcher.requests.AsyncSession", return_value=session),
    ):
        async with asyncio.timeout(5):
            probe = await conditional_probe("https://example.com/page")

    # then
    assert probe == ConditionalProbe(None, None, None)


async def test_probe_sends_conditional_headers_and_reads_304() -> None:
    # given
    session = _FakeSession(_response(304, {"etag": '"v1"'}))

    # when
    with (
        patch("src.crawl.fetcher.check_fetch_uri", new=AsyncMock(return_value=_target())),
        patch("src.crawl.fetcher.requests.AsyncSession", return_value=session),
    ):
        probe = await conditional_probe("https://example.com/page", etag='"old"', last_modified="Mon")

    # then
    assert probe.status == 304
    assert probe.etag == '"v1"'
    assert probe.last_modified is None
    assert session.sent_headers == {"If-None-Match": '"old"', "If-Modified-Since": "Mon"}


async def test_probe_200_returns_fresh_validators() -> None:
    # given
    session = _FakeSession(_response(200, {"etag": '"v2"', "last-modified": "Tue"}))

    # when
    with (
        patch("src.crawl.fetcher.check_fetch_uri", new=AsyncMock(return_value=_target())),
        patch("src.crawl.fetcher.requests.AsyncSession", return_value=session),
    ):
        probe = await conditional_probe("https://example.com/page")

    # then no conditional headers are sent and fresh validators are read
    assert probe.status == 200
    assert probe.etag == '"v2"'
    assert probe.last_modified == "Tue"
    assert session.sent_headers == {}


async def test_probe_uses_crawl_proxy_in_crawl_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # given a configured crawl proxy
    from src.config.config import settings
    from src.proxy.proxy_provider import crawl_proxy

    monkeypatch.setattr(settings, "CRAWL_PROXY_URL", "http://crawl-proxy:8080")
    session = _FakeSession(_response(200, {}))

    # when the probe runs inside the crawl context
    with (
        patch("src.crawl.fetcher.check_fetch_uri", new=AsyncMock(return_value=_target())),
        patch("src.crawl.fetcher.requests.AsyncSession", return_value=session),
        crawl_proxy(),
    ):
        probe = await conditional_probe("https://example.com/page")

    # then the hop carries the crawl proxy
    assert probe.status == 200
    assert session.sent_kwargs.get("proxies") == {
        "http": "http://crawl-proxy:8080",
        "https": "http://crawl-proxy:8080",
    }


async def test_probe_refused_url_answers_none() -> None:
    # given a guard refusal
    from ascend_python_common.uri_guard import UnsafeUriError

    # when
    with patch("src.crawl.fetcher.check_fetch_uri", new=AsyncMock(side_effect=UnsafeUriError("no"))):
        probe = await conditional_probe("http://127.0.0.1/")

    # then
    assert probe.status is None


async def test_probe_refused_redirect_answers_none() -> None:
    # given a guard refusal on a redirect hop
    from ascend_python_common.uri_guard import UnsafeUriError

    session = _FakeSession(_response(302, {"location": "http://127.0.0.1/x"}))

    async def fail_hop(*args: Any) -> Any:
        raise UnsafeUriError("no")

    # when
    with (
        patch("src.crawl.fetcher.check_fetch_uri", new=AsyncMock(return_value=_target())),
        patch("src.crawl.fetcher.requests.AsyncSession", return_value=session),
        patch("src.crawl.fetcher.follow_pinned_redirects", new=fail_hop),
    ):
        probe = await conditional_probe("https://example.com/page")

    # then
    assert probe.status is None


async def test_probe_transport_error_answers_none() -> None:
    # given a failing session
    broken = MagicMock()
    broken.__aenter__ = AsyncMock(side_effect=RuntimeError("down"))

    # when
    with (
        patch("src.crawl.fetcher.check_fetch_uri", new=AsyncMock(return_value=_target())),
        patch("src.crawl.fetcher.requests.AsyncSession", return_value=broken),
    ):
        probe = await conditional_probe("https://example.com/page")

    # then
    assert probe.status is None


async def test_probe_uses_the_shared_fetch_policy(monkeypatch: pytest.MonkeyPatch) -> None:
    # given a shared policy and a guard that records the policy it receives
    sentinel = object()
    policies: list[object] = []

    async def recording_guard(url: str, policy: Any) -> FetchTarget:
        policies.append(policy)
        return _target()

    monkeypatch.setattr("src.crawl.fetcher.web_hunter_fetch_policy", lambda: sentinel)
    monkeypatch.setattr("src.crawl.fetcher.check_fetch_uri", recording_guard)
    session = _FakeSession(_response(200))

    # when
    with (
        patch("src.crawl.fetcher.requests.AsyncSession", return_value=session),
        patch(
            "src.crawl.fetcher.follow_pinned_redirects",
            new=AsyncMock(return_value=MagicMock(answer=_response(200))),
        ),
    ):
        await conditional_probe("https://example.com/page")

    # then the guard ran with the shared policy
    assert policies == [sentinel]


async def test_probe_sends_the_stored_cookies_and_user_agent_of_the_profile(stored_session: Any) -> None:
    # given a stored session of the profile with cookies and a user agent
    stored_session.get_flat_cookies.return_value = {"sid": "s1"}
    stored_session.get_user_agent.return_value = "StoredAgent/1"
    session = _FakeSession(_response(304, {"etag": '"v1"'}))

    # when
    with (
        patch("src.crawl.fetcher.check_fetch_uri", new=AsyncMock(return_value=_target())),
        patch("src.crawl.fetcher.requests.AsyncSession", return_value=session),
    ):
        probe = await conditional_probe("https://example.com/page", etag='"old"', profile="alice")

    # then the probe carries the same session the read tiers send for that profile
    assert probe.status == 304
    stored_session.get_flat_cookies.assert_awaited_once_with("https://example.com/page", "alice")
    stored_session.get_user_agent.assert_awaited_once_with("https://example.com/page", "alice")
    assert session.sent_kwargs["cookies"] == {"sid": "s1"}
    assert session.sent_headers == {"User-Agent": "StoredAgent/1", "If-None-Match": '"old"'}


async def test_probe_without_a_stored_session_sends_no_cookies_and_no_user_agent(stored_session: Any) -> None:
    # given no stored session
    session = _FakeSession(_response(200))

    # when
    with (
        patch("src.crawl.fetcher.check_fetch_uri", new=AsyncMock(return_value=_target())),
        patch("src.crawl.fetcher.requests.AsyncSession", return_value=session),
    ):
        await conditional_probe("https://example.com/page")

    # then the default profile was looked up and nothing extra is sent
    stored_session.get_flat_cookies.assert_awaited_once_with("https://example.com/page", None)
    assert session.sent_kwargs["cookies"] == {}
    assert session.sent_headers == {}


async def test_probe_session_lookup_failure_answers_none(stored_session: Any) -> None:
    # given a session store that fails
    stored_session.get_flat_cookies.side_effect = RuntimeError("store down")

    # when
    with patch("src.crawl.fetcher.check_fetch_uri", new=AsyncMock(return_value=_target())):
        probe = await conditional_probe("https://example.com/page", profile="alice")

    # then the caller reads the page unconditionally
    assert probe.status is None


async def test_probe_streams_and_stops_every_hop_without_reading_a_body() -> None:
    # given a redirect to a public address and a 304 at its end
    redirect = _response(302, {"location": "https://93.184.216.34/next"})
    final = _response(304, {"etag": '"v2"', "last-modified": "Tue"})
    session = _FakeSession(redirect, final)

    # when
    with (
        patch("src.crawl.fetcher.check_fetch_uri", new=AsyncMock(return_value=_target())),
        patch("src.crawl.fetcher.requests.AsyncSession", return_value=session),
    ):
        probe = await conditional_probe("https://example.com/page", etag='"v1"')

    # then both hops were streamed, aborted and closed with no body read, and the final answer is read
    assert session.sent_urls == ["https://example.com/page", "https://93.184.216.34/next"]
    assert session.sent_kwargs["stream"] is True
    _assert_stopped_unread(redirect)
    _assert_stopped_unread(final)
    assert probe == ConditionalProbe(304, '"v2"', "Tue")


async def test_probe_stops_the_opened_hop_when_the_redirect_is_refused() -> None:
    # given a redirect the guard refuses
    redirect = _response(302, {"location": "http://127.0.0.1/x"})
    session = _FakeSession(redirect)

    # when
    with (
        patch("src.crawl.fetcher.check_fetch_uri", new=AsyncMock(return_value=_target())),
        patch("src.crawl.fetcher.requests.AsyncSession", return_value=session),
    ):
        probe = await conditional_probe("https://example.com/page")

    # then no request went to the refused hop and the opened one was stopped
    assert probe.status is None
    assert session.sent_urls == ["https://example.com/page"]
    _assert_stopped_unread(redirect)


async def test_probe_failure_log_carries_no_userinfo(caplog: pytest.LogCaptureFixture) -> None:
    # given a url with userinfo and a transport that fails naming it
    url = "https://crawler:hunter2@example.com/page?X-Amz-Signature=secret"
    broken = MagicMock()
    broken.__aenter__ = AsyncMock(side_effect=RuntimeError(f"cannot reach {url}"))

    # when
    with (
        patch("src.crawl.fetcher.check_fetch_uri", new=AsyncMock(return_value=_target())),
        patch("src.crawl.fetcher.requests.AsyncSession", return_value=broken),
        caplog.at_level("WARNING", logger="src.crawl.fetcher"),
    ):
        probe = await conditional_probe(url)

    # then the warning names the page without its password
    assert probe.status is None
    assert (
        "conditional probe of https://example.com/page failed: cannot reach https://example.com/page"
        in caplog.text
    )
    assert "hunter2" not in caplog.text
    assert "X-Amz-Signature" not in caplog.text


class _Chunks:
    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = chunks
        self.read = 0

    def __call__(self) -> "_Chunks":
        return self

    def __aiter__(self) -> "_Chunks":
        return self

    async def __anext__(self) -> bytes:
        if self.read == len(self._chunks):
            raise StopAsyncIteration
        self.read += 1
        return self._chunks[self.read - 1]

    async def aclose(self) -> None:
        return


def _robots_response(
    status: int, body: str = "", headers: dict[str, str] | None = None, *, chunks: list[bytes] | None = None
) -> MagicMock:
    response = _response(status, headers)
    response.aiter_content = _Chunks(chunks if chunks is not None else [body.encode("utf-8")])
    return response


async def test_robots_fetch_answers_status_and_body_with_the_crawl_user_agent(stored_session: Any) -> None:
    # given a stored session with cookies and no stored user agent
    stored_session.get_flat_cookies.return_value = {"sid": "s1"}
    session = _FakeSession(_robots_response(200, "User-agent: *\nDisallow: /x\n"))

    # when
    with (
        patch("src.crawl.fetcher.check_fetch_uri", new=AsyncMock(return_value=_target())),
        patch("src.crawl.fetcher.requests.AsyncSession", return_value=session),
    ):
        answer = await fetch_robots_txt("https://example.com/robots.txt", None)

    # then the whole body comes back unstreamed with the status, cookies and the crawl user agent
    assert answer == RobotsFetch(200, "User-agent: *\nDisallow: /x\n")
    stored_session.get_flat_cookies.assert_awaited_once_with("https://example.com/robots.txt", None)
    assert session.sent_kwargs["cookies"] == {"sid": "s1"}
    assert session.sent_kwargs["stream"] is True
    assert session.sent_headers == {"User-Agent": "ascend-web-hunter-crawl", "Accept-Encoding": "identity"}


async def test_robots_fetch_sends_the_stored_user_agent(stored_session: Any) -> None:
    # given a stored user agent for the origin
    stored_session.get_user_agent.return_value = "StoredAgent/1"
    session = _FakeSession(_robots_response(404))

    # when
    with (
        patch("src.crawl.fetcher.check_fetch_uri", new=AsyncMock(return_value=_target())),
        patch("src.crawl.fetcher.requests.AsyncSession", return_value=session),
    ):
        answer = await fetch_robots_txt("https://example.com/robots.txt", None)

    # then
    assert answer.status == 404
    assert session.sent_headers == {"User-Agent": "StoredAgent/1", "Accept-Encoding": "identity"}


async def test_robots_fetch_follows_a_redirect_and_answers_the_final_status() -> None:
    # given a robots.txt that redirects to a file answering 503
    session = _FakeSession(
        _robots_response(301, headers={"location": "https://example.com/real-robots.txt"}),
        _robots_response(503, "busy"),
    )

    # when
    with (
        patch("src.crawl.fetcher.check_fetch_uri", new=AsyncMock(return_value=_target())),
        patch("src.crawl.fetcher.requests.AsyncSession", return_value=session),
    ):
        answer = await fetch_robots_txt("https://example.com/robots.txt", None)

    # then
    assert answer == RobotsFetch(503, "busy")
    assert len(session.sent_urls) == 2


async def test_robots_fetch_uses_crawl_proxy_in_crawl_context(monkeypatch: pytest.MonkeyPatch) -> None:
    # given a configured crawl proxy
    from src.config.config import settings
    from src.proxy.proxy_provider import crawl_proxy

    monkeypatch.setattr(settings, "CRAWL_PROXY_URL", "http://crawl-proxy:8080")
    session = _FakeSession(_robots_response(200))

    # when
    with (
        patch("src.crawl.fetcher.check_fetch_uri", new=AsyncMock(return_value=_target())),
        patch("src.crawl.fetcher.requests.AsyncSession", return_value=session),
        crawl_proxy(),
    ):
        await fetch_robots_txt("https://example.com/robots.txt", None)

    # then
    assert session.sent_kwargs.get("proxies") == {
        "http": "http://crawl-proxy:8080",
        "https": "http://crawl-proxy:8080",
    }


async def test_robots_fetch_raises_a_refused_address() -> None:
    # given
    from ascend_python_common.uri_guard import UnsafeUriError

    # when / then
    with (
        patch("src.crawl.fetcher.check_fetch_uri", new=AsyncMock(side_effect=UnsafeUriError("no"))),
        pytest.raises(UnsafeUriError),
    ):
        await fetch_robots_txt("http://127.0.0.1/robots.txt", None)


async def test_robots_fetch_raises_a_refused_redirect() -> None:
    # given
    from ascend_python_common.uri_guard import UnsafeUriError

    session = _FakeSession(_robots_response(302, headers={"location": "http://127.0.0.1/x"}))

    async def fail_hop(*args: Any) -> Any:
        raise UnsafeUriError("no")

    # when / then
    with (
        patch("src.crawl.fetcher.check_fetch_uri", new=AsyncMock(return_value=_target())),
        patch("src.crawl.fetcher.requests.AsyncSession", return_value=session),
        patch("src.crawl.fetcher.follow_pinned_redirects", new=fail_hop),
        pytest.raises(UnsafeUriError),
    ):
        await fetch_robots_txt("https://example.com/robots.txt", None)


async def test_robots_fetch_transport_error_answers_no_status(caplog: pytest.LogCaptureFixture) -> None:
    # given a connection that fails
    from curl_cffi.requests.exceptions import ConnectionError as CurlConnectionError

    broken = MagicMock()
    broken.__aenter__ = AsyncMock(side_effect=CurlConnectionError("refused http://user:pw@example.com/"))

    # when
    with (
        patch("src.crawl.fetcher.check_fetch_uri", new=AsyncMock(return_value=_target())),
        patch("src.crawl.fetcher.requests.AsyncSession", return_value=broken),
    ):
        answer = await fetch_robots_txt("https://user:pw@example.com/robots.txt", None)

    # then
    assert answer == RobotsFetch(None)
    assert "example.com/robots.txt" in caplog.text
    assert "pw" not in caplog.text


async def test_robots_fetch_stops_reading_at_the_cap_and_keeps_the_whole_lines_before_it(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    # given a cap of 64 bytes and a body sent in chunks far past it
    from src.config.config import settings

    monkeypatch.setattr(settings, "CRAWL_ROBOTS_MAX_BYTES", 64)
    head = b"User-agent: *\nDisallow: /private/\n"
    chunks = [head, b"# " + b"x" * 40 + b"\nDisallow: /late/\n", b"Disallow: /later/\n" * 1000, b"never read"]
    response = _robots_response(200, chunks=chunks)
    session = _FakeSession(response)

    # when
    with (
        patch("src.crawl.fetcher.check_fetch_uri", new=AsyncMock(return_value=_target())),
        patch("src.crawl.fetcher.requests.AsyncSession", return_value=session),
    ):
        answer = await fetch_robots_txt("https://example.com/robots.txt", None)

    # then the body keeps the whole lines inside the first 64 bytes, drops the line the cap cuts, and the
    # stream stopped at the chunk that crossed the cap
    assert len(head) < 64 < len(head) + len(chunks[1])
    assert answer == RobotsFetch(200, head.decode())
    assert response.aiter_content.read == 2
    response.quit_now.set.assert_called_once_with()
    response.aclose.assert_awaited_once_with()
    assert "64 bytes" in caplog.text


async def test_robots_fetch_keeps_a_body_of_exactly_the_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    # given a body exactly as long as the cap
    from src.config.config import settings

    body = b"User-agent: *\nDisallow: /a\n"
    monkeypatch.setattr(settings, "CRAWL_ROBOTS_MAX_BYTES", len(body))
    session = _FakeSession(_robots_response(200, chunks=[body[:10], body[10:]]))

    # when
    with (
        patch("src.crawl.fetcher.check_fetch_uri", new=AsyncMock(return_value=_target())),
        patch("src.crawl.fetcher.requests.AsyncSession", return_value=session),
    ):
        answer = await fetch_robots_txt("https://example.com/robots.txt", None)

    # then nothing is cut
    assert answer == RobotsFetch(200, body.decode())


async def test_robots_fetch_sends_the_cookies_and_user_agent_of_the_job_profile(stored_session: Any) -> None:
    # given two profiles with their own stored sessions
    stored_session.get_flat_cookies.side_effect = lambda url, profile: {"sid": f"s-{profile}"}
    stored_session.get_user_agent.side_effect = lambda url, profile: f"Agent-{profile}"
    sessions = [_FakeSession(_robots_response(200)), _FakeSession(_robots_response(200))]

    # when
    with (
        patch("src.crawl.fetcher.check_fetch_uri", new=AsyncMock(return_value=_target())),
        patch("src.crawl.fetcher.requests.AsyncSession", side_effect=sessions),
    ):
        await fetch_robots_txt("https://example.com/robots.txt", "alice")
        await fetch_robots_txt("https://example.com/robots.txt", "bob")

    # then each fetch carried its own profile's session
    assert [session.sent_kwargs["cookies"] for session in sessions] == [{"sid": "s-alice"}, {"sid": "s-bob"}]
    assert [session.sent_headers for session in sessions] == [
        {"User-Agent": "Agent-alice", "Accept-Encoding": "identity"},
        {"User-Agent": "Agent-bob", "Accept-Encoding": "identity"},
    ]


async def _fetch_robots(session: _FakeSession, url: str = "https://example.com/robots.txt") -> RobotsFetch:
    with (
        patch("src.crawl.fetcher.check_fetch_uri", new=AsyncMock(return_value=_target())),
        patch("src.crawl.fetcher.requests.AsyncSession", return_value=session),
    ):
        return await fetch_robots_txt(url, None)


async def test_robots_fetch_turns_off_libcurl_content_decoding() -> None:
    # given
    session = _FakeSession(_robots_response(200))

    # when
    await _fetch_robots(session)

    # then
    assert session.curl_options[CurlOpt.HTTP_CONTENT_DECODING] == 0


async def test_probe_turns_off_decoding_and_keeps_the_default_accept_encoding() -> None:
    # given
    session = _FakeSession(_response(304))

    # when
    with (
        patch("src.crawl.fetcher.check_fetch_uri", new=AsyncMock(return_value=_target())),
        patch("src.crawl.fetcher.requests.AsyncSession", return_value=session),
    ):
        await conditional_probe("https://example.com/page", etag='"old"')

    # then
    assert session.curl_options[CurlOpt.HTTP_CONTENT_DECODING] == 0
    assert session.sent_headers == {"If-None-Match": '"old"'}


@pytest.mark.parametrize("coding", ["gzip", "GZIP"])
async def test_robots_fetch_inflates_a_compressed_success_it_did_not_ask_for(coding: str) -> None:
    # given a server that gzips although the fetch asked for identity
    body = "User-agent: *\nDisallow: /x\n"
    response = _robots_response(
        200, chunks=[gzip.compress(body.encode())], headers={"content-encoding": coding}
    )

    # when
    answer = await _fetch_robots(_FakeSession(response))

    # then
    assert answer == RobotsFetch(200, body)


async def test_robots_fetch_of_a_compressed_file_keeps_the_whole_lines_within_the_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # given a compressed file whose inflated length passes the cap
    monkeypatch.setattr(settings, "CRAWL_ROBOTS_MAX_BYTES", 80)
    wire = gzip.compress(b"User-agent: *\n" + b"Disallow: /x\n" * 200)
    response = _robots_response(200, chunks=[wire], headers={"content-encoding": "gzip"})

    # when
    answer = await _fetch_robots(_FakeSession(response))

    # then
    assert len(wire) < 80
    assert answer == RobotsFetch(200, "User-agent: *\n" + "Disallow: /x\n" * 5)


@pytest.mark.parametrize(
    ("coding", "wire"), [("compress", b"x"), ("gzip", b"\x1f\x8b\x00not a deflate stream")]
)
async def test_robots_fetch_answers_no_status_for_a_success_it_cannot_decode(
    coding: str, wire: bytes, caplog: pytest.LogCaptureFixture
) -> None:
    # given
    response = _robots_response(200, chunks=[wire], headers={"content-encoding": coding})

    # when
    answer = await _fetch_robots(_FakeSession(response))

    # then the file reads as unreachable, so no rule is silently lost
    assert answer == RobotsFetch(None)
    assert "cannot be decoded" in caplog.text


async def test_robots_fetch_keeps_the_status_of_an_error_answer_it_cannot_decode() -> None:
    # given
    response = _robots_response(404, chunks=[b"not gzip"], headers={"content-encoding": "gzip"})

    # when
    answer = await _fetch_robots(_FakeSession(response))

    # then
    assert answer == RobotsFetch(404)


async def test_robots_fetch_keeps_the_status_of_a_compressed_error_answer() -> None:
    # given
    session = _FakeSession(_robots_response(404, headers={"content-encoding": "gzip"}))

    # when
    answer = await _fetch_robots(session)

    # then
    assert answer.status == 404


async def test_robots_fetch_reads_a_body_marked_identity() -> None:
    # given
    session = _FakeSession(_robots_response(200, "User-agent: *\n", {"content-encoding": "identity"}))

    # when
    answer = await _fetch_robots(session)

    # then
    assert answer == RobotsFetch(200, "User-agent: *\n")


async def test_robots_fetch_drops_a_byte_order_mark_before_the_first_group() -> None:
    # given
    session = _FakeSession(_robots_response(200, chunks=[b"\xef\xbb\xbfUser-agent: *\nDisallow: /x\n"]))

    # when
    answer = await _fetch_robots(session)

    # then
    assert answer == RobotsFetch(200, "User-agent: *\nDisallow: /x\n")


async def test_robots_fetch_replaces_invalid_bytes_after_a_byte_order_mark() -> None:
    # given
    session = _FakeSession(_robots_response(200, chunks=[b"\xef\xbb\xbf# caf\xe9\n"]))

    # when
    answer = await _fetch_robots(session)

    # then
    assert answer == RobotsFetch(200, "# caf\ufffd\n")


@pytest.mark.parametrize(
    ("body", "kept"),
    [
        (b"User-agent: *\rDisallow: /x\rDisallow: /cut-in-the-mid", b"User-agent: *\rDisallow: /x\r"),
        (b"User-agent: *\nDisallow: /x\r\nDisallow: /cut-in-the-mid", b"User-agent: *\nDisallow: /x\r\n"),
        (b"User-agent: *\rDisallow: /a\nDisallow: /cut-in-the-mid", b"User-agent: *\rDisallow: /a\n"),
    ],
)
async def test_robots_fetch_cuts_at_the_last_line_end_of_any_kind(
    body: bytes, kept: bytes, monkeypatch: pytest.MonkeyPatch
) -> None:
    # given a cap that falls inside the last line
    from src.config.config import settings

    monkeypatch.setattr(settings, "CRAWL_ROBOTS_MAX_BYTES", len(body) - 3)
    session = _FakeSession(_robots_response(200, chunks=[body]))

    # when
    answer = await _fetch_robots(session)

    # then
    assert answer == RobotsFetch(200, kept.decode())


async def test_robots_fetch_failure_log_carries_no_query_string(caplog: pytest.LogCaptureFixture) -> None:
    # given a transport error that names a signed address
    from curl_cffi.requests.exceptions import ConnectionError as CurlConnectionError

    url = "https://example.com/robots.txt?X-Amz-Signature=secret"
    broken = MagicMock()
    broken.__aenter__ = AsyncMock(side_effect=CurlConnectionError(f"refused {url}"))

    # when
    with (
        patch("src.crawl.fetcher.check_fetch_uri", new=AsyncMock(return_value=_target())),
        patch("src.crawl.fetcher.requests.AsyncSession", return_value=broken),
    ):
        answer = await fetch_robots_txt(url, None)

    # then
    assert answer == RobotsFetch(None)
    assert "refused https://example.com/robots.txt" in caplog.text
    assert "X-Amz-Signature" not in caplog.text


async def test_robots_cut_warning_carries_no_query_string(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    # given
    from src.config.config import settings

    monkeypatch.setattr(settings, "CRAWL_ROBOTS_MAX_BYTES", 4)
    session = _FakeSession(_robots_response(200, chunks=[b"a\nbcdefgh"]))

    # when
    await _fetch_robots(session, "https://example.com/robots.txt?X-Amz-Signature=secret")

    # then
    assert "X-Amz-Signature" not in caplog.text


@pytest.mark.parametrize("fetcher_name", ["robots", "probe"])
async def test_a_redirect_to_a_second_host_receives_no_stored_cookies(
    fetcher_name: str, stored_session: Any
) -> None:
    # given stored login cookies and a redirect to another registrable domain
    stored_session.get_flat_cookies.return_value = {"sid": "s1"}
    session = _FakeSession(
        _robots_response(302, headers={"location": "https://93.184.216.34/next"}), _robots_response(200)
    )

    # when
    with (
        patch("src.crawl.fetcher.check_fetch_uri", new=AsyncMock(return_value=_target())),
        patch("src.crawl.fetcher.requests.AsyncSession", return_value=session),
    ):
        if fetcher_name == "robots":
            await fetch_robots_txt("https://example.com/robots.txt", None)
        else:
            await conditional_probe("https://example.com/page")

    # then the last hop, on the second host, carried no cookie
    assert session.sent_urls[-1] == "https://93.184.216.34/next"
    assert session.sent_kwargs["cookies"] == {}

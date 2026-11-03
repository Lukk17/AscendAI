from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from ascend_python_common.uri_guard import FetchTarget

from src.crawl.fetcher import conditional_probe, head_validators


def _target(url: str = "https://example.com/page") -> FetchTarget:
    return FetchTarget(url=url, host="example.com", port=443, addresses=("93.184.216.34",))


class _FakeSession:
    def __init__(self, response: Any) -> None:
        self._response = response
        self.sent_headers: dict[str, str] | None = None
        self.sent_kwargs: dict[str, Any] = {}
        self.curl_options: dict[str, list[str]] = {}

    async def __aenter__(self) -> "_FakeSession":
        return self

    async def __aexit__(self, *args: Any) -> bool:
        return False

    async def get(self, url: str, **kwargs: Any) -> Any:
        self.sent_headers = kwargs.get("headers", {})
        self.sent_kwargs = kwargs
        return self._response

    async def head(self, url: str, **kwargs: Any) -> Any:
        self.sent_kwargs = kwargs
        return self._response


def _response(status: int, headers: dict[str, str] | None = None) -> MagicMock:
    response = MagicMock()
    response.status_code = status
    response.headers = headers or {}
    return response


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


async def test_head_reads_validators() -> None:
    # given
    session = _FakeSession(_response(200, {"etag": '"v9"', "last-modified": "Wed"}))

    # when
    with (
        patch("src.crawl.fetcher.check_fetch_uri", new=AsyncMock(return_value=_target())),
        patch("src.crawl.fetcher.requests.AsyncSession", return_value=session),
    ):
        validators = await head_validators("https://example.com/page")

    # then
    assert validators == ('"v9"', "Wed")


async def test_head_non_200_answers_nones() -> None:
    # given
    session = _FakeSession(_response(404, {}))

    # when
    with (
        patch("src.crawl.fetcher.check_fetch_uri", new=AsyncMock(return_value=_target())),
        patch("src.crawl.fetcher.requests.AsyncSession", return_value=session),
    ):
        validators = await head_validators("https://example.com/page")

    # then
    assert validators == (None, None)


async def test_head_refused_url_answers_nones() -> None:
    # given a guard refusal
    from ascend_python_common.uri_guard import UnsafeUriError

    # when
    with patch("src.crawl.fetcher.check_fetch_uri", new=AsyncMock(side_effect=UnsafeUriError("no"))):
        validators = await head_validators("http://127.0.0.1/")

    # then
    assert validators == (None, None)


async def test_head_error_answers_nones() -> None:
    # given a failing session
    broken = MagicMock()
    broken.__aenter__ = AsyncMock(side_effect=RuntimeError("down"))

    # when
    with (
        patch("src.crawl.fetcher.check_fetch_uri", new=AsyncMock(return_value=_target())),
        patch("src.crawl.fetcher.requests.AsyncSession", return_value=broken),
    ):
        validators = await head_validators("https://example.com/page")

    # then
    assert validators == (None, None)


async def test_head_uses_crawl_proxy_in_crawl_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # given a configured crawl proxy
    from src.config.config import settings
    from src.proxy.proxy_provider import crawl_proxy

    monkeypatch.setattr(settings, "CRAWL_PROXY_URL", "http://crawl-proxy:8080")
    session = _FakeSession(_response(200, {}))

    # when the HEAD runs inside the crawl context
    with (
        patch("src.crawl.fetcher.check_fetch_uri", new=AsyncMock(return_value=_target())),
        patch("src.crawl.fetcher.requests.AsyncSession", return_value=session),
        crawl_proxy(),
    ):
        validators = await head_validators("https://example.com/page")

    # then the hop carries the crawl proxy
    assert validators == (None, None)
    assert session.sent_kwargs.get("proxies") == {
        "http": "http://crawl-proxy:8080",
        "https": "http://crawl-proxy:8080",
    }

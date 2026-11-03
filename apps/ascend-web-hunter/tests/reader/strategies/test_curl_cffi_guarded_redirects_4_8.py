"""Task 4.8: the curl_cffi tier pins the first request and every hop (design D21)."""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from ascend_python_common.uri_guard import FetchPolicy, FetchTarget
from ascend_python_common.uri_guard import check_fetch_uri as _real_check
from curl_cffi import CurlOpt

from src.reader.strategies import curl_cffi_fetcher as fetcher

_PUBLIC = "93.184.216.34"
_START_URL = "https://start.example/page"
_HOP_URL = "https://hop.example/page"
_HTML = "<html><body>the page</body></html>"

_CHECK = "src.reader.strategies.curl_cffi_fetcher.check_fetch_uri"
_LIBRARY_CHECK = "ascend_python_common.uri_guard.check_fetch_uri"
_SESSION = "src.reader.strategies.curl_cffi_fetcher.requests.AsyncSession"
_COOKIES = "src.reader.strategies.curl_cffi_fetcher.cookie_manager.get_flat_cookies"
_USER_AGENT = "src.reader.strategies.curl_cffi_fetcher.cookie_manager.get_user_agent"


class _FakeSession:
    def __init__(self, responses: list[MagicMock]) -> None:
        self.curl_options: dict[Any, Any] = {}
        self.requested: list[str] = []
        self._responses = list(responses)

    async def __aenter__(self) -> "_FakeSession":
        return self

    async def __aexit__(self, *_exc: object) -> bool:
        return False

    async def get(self, url: str, **_kwargs: object) -> Any:
        self.requested.append(url)
        return self._responses.pop(0)


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


async def _start_and_hop_check(uri: str, policy: FetchPolicy) -> FetchTarget:
    # when
    if uri == _START_URL:
        return FetchTarget(url=uri, host="start.example", port=443, addresses=(_PUBLIC,))
    # when
    if uri == _HOP_URL:
        return FetchTarget(url=uri, host="hop.example", port=443, addresses=(_PUBLIC,))
    # when
    return await _real_check(uri, policy)


async def _start_only_check(uri: str, policy: FetchPolicy) -> FetchTarget:
    # when
    if uri == _START_URL:
        return FetchTarget(url=uri, host="start.example", port=443, addresses=(_PUBLIC,))
    # when
    return await _real_check(uri, policy)


@pytest.mark.asyncio
async def test_first_request_and_every_hop_pinned_through_curlopt_resolve() -> None:
    # given
    session = _FakeSession([_redirect_response(_HOP_URL), _ok_response()])

    # when
    with (
        patch(_CHECK, side_effect=_start_and_hop_check),
        patch(_LIBRARY_CHECK, side_effect=_start_and_hop_check),
        patch(_SESSION, return_value=session),
        patch(_COOKIES, new=AsyncMock(return_value={})),
        patch(_USER_AGENT, new=AsyncMock(return_value=None)),
    ):
        html = await fetcher.fetch_with_curl_cffi(_START_URL, lambda: "UA", "test")

    # then
    assert html == _HTML
    assert session.requested == [_START_URL, _HOP_URL]
    assert session.curl_options[CurlOpt.RESOLVE] == [f"hop.example:443:{_PUBLIC}"]


@pytest.mark.asyncio
async def test_private_redirect_hop_returns_no_content_without_request() -> None:
    # given
    session = _FakeSession([_redirect_response("http://192.168.1.1/secret"), _ok_response()])

    # when
    with (
        patch(_CHECK, side_effect=_start_only_check),
        patch(_LIBRARY_CHECK, side_effect=_start_only_check),
        patch(_SESSION, return_value=session),
        patch(_COOKIES, new=AsyncMock(return_value={})),
        patch(_USER_AGENT, new=AsyncMock(return_value=None)),
    ):
        html = await fetcher.fetch_with_curl_cffi(_START_URL, lambda: "UA", "test")

    # then
    assert html == ""
    assert session.requested == [_START_URL]


@pytest.mark.asyncio
async def test_private_first_request_returns_no_content_without_session() -> None:
    # given
    sentinel = MagicMock()
    sentinel.__aenter__.side_effect = AssertionError("no session must open for a refused URL")

    # when
    with patch(_SESSION, return_value=sentinel):
        html = await fetcher.fetch_with_curl_cffi("http://192.168.1.1/secret", lambda: "UA", "test")

    # then
    assert html == ""
    sentinel.__aenter__.assert_not_called()


@pytest.mark.parametrize(
    ("target", "expected"),
    [
        (
            FetchTarget(url="https://n.example/", host="n.example", port=443, addresses=("93.184.216.34",)),
            ["n.example:443:93.184.216.34"],
        ),
        (
            FetchTarget(
                url="https://n.example/",
                host="n.example",
                port=443,
                addresses=("93.184.216.34", "93.184.216.35", "2001:db8::1"),
            ),
            ["n.example:443:93.184.216.34,93.184.216.35,[2001:db8::1]"],
        ),
        (
            FetchTarget(url="http://93.184.216.34/", host="93.184.216.34", port=80, addresses=()),
            [],
        ),
        (
            FetchTarget(url="http://allowed:7021/", host="allowed", port=7021, addresses=()),
            [],
        ),
        (
            FetchTarget(url="file:///root/a", host=None, port=None),
            [],
        ),
    ],
)
def test_resolve_entries_built_from_the_checked_target(target: FetchTarget, expected: list[str]) -> None:
    # given
    entries: list[str] = []

    # when
    entries = fetcher._resolve_entries(target)

    # then
    assert entries == expected

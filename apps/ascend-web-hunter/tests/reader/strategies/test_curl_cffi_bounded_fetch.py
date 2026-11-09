"""The byte-capped curl_cffi path streams the body and stops at the cap."""

import asyncio
import gzip
import logging
import zlib
from collections.abc import AsyncIterator, Callable
from typing import Any, cast
from unittest.mock import AsyncMock, patch

import brotli
import pytest
import zstandard
from ascend_python_common.uri_guard import FetchPolicy, FetchTarget, UnsafeUriError
from ascend_python_common.uri_guard import check_fetch_uri as _real_check
from curl_cffi import CurlOpt

from src.config.config import settings
from src.crawl.robots import _unpack_sitemap
from src.reader.strategies import curl_cffi_fetcher as fetcher
from src.reader.strategies.base_strategy import FetchedHtml
from tests.reader.strategies.conftest import HostileCodec

_PUBLIC = "93.184.216.34"
_START_URL = "https://start.example/sitemap.xml"
_HOP_URL = "https://hop.example/sitemap.xml"

_CHECK = "src.reader.strategies.curl_cffi_fetcher.check_fetch_uri"
_LIBRARY_CHECK = "ascend_python_common.uri_guard.check_fetch_uri"
_SESSION = "src.reader.strategies.curl_cffi_fetcher.requests.AsyncSession"
_COOKIES = "src.reader.strategies.curl_cffi_fetcher.cookie_manager.get_flat_cookies"
_USER_AGENT = "src.reader.strategies.curl_cffi_fetcher.cookie_manager.get_user_agent"


class _StreamedResponse:
    def __init__(
        self,
        chunks: list[bytes],
        *,
        status_code: int = 200,
        headers: dict[str, str] | None = None,
        encoding: str = "utf-8",
    ) -> None:
        self.status_code = status_code
        self.headers = headers or {}
        self.encoding = encoding
        self.text = ""
        self.url = ""
        self.quit_now = asyncio.Event()
        self.chunks_read = 0
        self.closed = False
        self._chunks = chunks

    async def aiter_content(self) -> AsyncIterator[bytes]:
        for chunk in self._chunks:
            self.chunks_read += 1
            yield chunk

    async def aclose(self) -> None:
        self.closed = True

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class _FakeSession:
    def __init__(self, responses: list[_StreamedResponse]) -> None:
        self.curl_options: dict[Any, Any] = {}
        self.requested: list[str] = []
        self.kwargs: list[dict[str, object]] = []
        self.resolved: list[object] = []
        self._responses = list(responses)

    async def __aenter__(self) -> "_FakeSession":
        return self

    async def __aexit__(self, *_exc: object) -> bool:
        return False

    async def get(self, url: str, **kwargs: object) -> Any:
        self.requested.append(url)
        self.kwargs.append(kwargs)
        self.resolved.append(self.curl_options.get(CurlOpt.RESOLVE))
        response = self._responses.pop(0)
        response.url = url
        return response


async def _pinned_check(uri: str, policy: FetchPolicy) -> FetchTarget:
    if uri == _START_URL:
        return FetchTarget(url=uri, host="start.example", port=443, addresses=(_PUBLIC,))
    if uri == _HOP_URL:
        return FetchTarget(url=uri, host="hop.example", port=443, addresses=(_PUBLIC,))
    return await _real_check(uri, policy)


async def _fetch(session: _FakeSession, max_bytes: int) -> str:
    with (
        patch(_CHECK, side_effect=_pinned_check),
        patch(_LIBRARY_CHECK, side_effect=_pinned_check),
        patch(_SESSION, return_value=session),
        patch(_COOKIES, new=AsyncMock(return_value={})),
        patch(_USER_AGENT, new=AsyncMock(return_value=None)),
    ):
        return await fetcher.fetch_with_curl_cffi(
            _START_URL, lambda: "UA", "crawl-sitemap", max_bytes=max_bytes
        )


def _redirect(location: str) -> _StreamedResponse:
    return _StreamedResponse([], status_code=302, headers={"location": location})


@pytest.mark.asyncio
async def test_body_within_the_cap_is_read_streamed_and_pinned() -> None:
    # given
    response = _StreamedResponse([b"<urlset>", b"</urlset>"])
    session = _FakeSession([response])

    # when
    body = await _fetch(session, max_bytes=17)

    # then the body is whole, the request streamed, and the connection pinned to the checked address
    assert body == "<urlset></urlset>"
    assert session.kwargs[0]["stream"] is True
    assert session.resolved == [[f"start.example:443:{_PUBLIC}"]]
    assert response.closed is True


@pytest.mark.asyncio
async def test_body_passing_the_cap_stops_reading_and_is_skipped(caplog: pytest.LogCaptureFixture) -> None:
    # given ten chunks of ten bytes and a cap of 25 bytes
    response = _StreamedResponse([b"x" * 10 for _ in range(10)])
    session = _FakeSession([response])

    # when
    with caplog.at_level("WARNING", logger="src.reader.strategies.curl_cffi_fetcher"):
        body = await _fetch(session, max_bytes=25)

    # then reading stopped at the third chunk, the transfer was told to quit, and the skip was logged
    assert body == ""
    assert response.chunks_read == 3
    assert response.quit_now.is_set()
    assert response.closed is True
    assert "above the cap of 25 bytes" in caplog.text


@pytest.mark.asyncio
async def test_declared_length_above_the_cap_is_skipped_before_any_body_byte() -> None:
    # given
    response = _StreamedResponse([b"x" * 100], headers={"content-length": "100"})
    session = _FakeSession([response])

    # when
    body = await _fetch(session, max_bytes=10)

    # then
    assert body == ""
    assert response.chunks_read == 0
    assert response.quit_now.is_set()


@pytest.mark.asyncio
async def test_redirect_hops_are_pinned_streamed_and_closed() -> None:
    # given
    hop = _redirect(_HOP_URL)
    final = _StreamedResponse([b"<urlset/>"])
    session = _FakeSession([hop, final])

    # when
    body = await _fetch(session, max_bytes=100)

    # then every hop was pinned to its own checked address and the intermediate one closed
    assert body == "<urlset/>"
    assert session.requested == [_START_URL, _HOP_URL]
    assert session.resolved == [[f"start.example:443:{_PUBLIC}"], [f"hop.example:443:{_PUBLIC}"]]
    assert all(kwargs["stream"] is True for kwargs in session.kwargs)
    assert hop.closed is True
    assert hop.quit_now.is_set()


@pytest.mark.asyncio
async def test_capped_read_carries_the_validators_of_the_final_answer() -> None:
    # given
    hop = _redirect(_HOP_URL)
    final = _StreamedResponse([b"<urlset/>"], headers={"etag": 'W/"s1"', "last-modified": "Thu"})
    session = _FakeSession([hop, final])

    # when
    body = await _fetch(session, max_bytes=100)

    # then
    assert isinstance(body, FetchedHtml)
    assert (body.etag, body.last_modified) == ('W/"s1"', "Thu")


@pytest.mark.asyncio
async def test_private_redirect_hop_in_the_capped_path_raises_and_closes_the_first_hop() -> None:
    # given
    hop = _redirect("http://192.168.1.1/sitemap.xml")
    session = _FakeSession([hop, _StreamedResponse([b"secret"])])

    # when
    with pytest.raises(UnsafeUriError):
        await _fetch(session, max_bytes=100)

    # then
    assert session.requested == [_START_URL]
    assert hop.closed is True


@pytest.mark.asyncio
async def test_capped_body_is_decoded_as_utf8_whatever_charset_the_server_declares() -> None:
    # given
    response = _StreamedResponse(["<loc>zażółć</loc>".encode()], encoding="iso-8859-2")
    session = _FakeSession([response])

    # when
    body = await _fetch(session, max_bytes=100)

    # then
    assert body == "<loc>zażółć</loc>"


@pytest.mark.asyncio
async def test_capped_body_never_reaches_the_codec_the_server_names(hostile_codec: HostileCodec) -> None:
    # given
    response = _StreamedResponse([b"<loc>a</loc>"], encoding=hostile_codec.name)
    session = _FakeSession([response])

    # when
    body = await _fetch(session, max_bytes=100)

    # then
    assert body == "<loc>a</loc>"
    hostile_codec.decode.assert_not_called()


@pytest.mark.asyncio
async def test_capped_fetch_turns_off_decoding_and_asks_for_an_uncompressed_body() -> None:
    # given
    session = _FakeSession([_StreamedResponse([b"<urlset></urlset>"])])

    # when
    await _fetch(session, max_bytes=100)

    # then
    assert session.curl_options[CurlOpt.HTTP_CONTENT_DECODING] == 0
    headers = session.kwargs[0]["headers"]
    assert isinstance(headers, dict)
    assert headers["Accept-Encoding"] == "identity"


@pytest.mark.asyncio
async def test_capped_body_passes_through_the_unpack_step_before_decoding() -> None:
    # given
    response = _StreamedResponse([b"packed"], headers={"content-type": "application/gzip"})
    session = _FakeSession([response])
    seen: list[tuple[bytes, str | None]] = []

    def unpack(raw: bytes, content_type: str | None) -> bytes | None:
        seen.append((raw, content_type))

        return b"<urlset></urlset>"

    # when
    with (
        patch(_CHECK, side_effect=_pinned_check),
        patch(_LIBRARY_CHECK, side_effect=_pinned_check),
        patch(_SESSION, return_value=session),
        patch(_COOKIES, new=AsyncMock(return_value={})),
        patch(_USER_AGENT, new=AsyncMock(return_value=None)),
    ):
        body = await fetcher.fetch_with_curl_cffi(
            _START_URL, lambda: "UA", "crawl-sitemap", max_bytes=100, unpack=unpack
        )

    # then
    assert seen == [(b"packed", "application/gzip")]
    assert body == "<urlset></urlset>"


@pytest.mark.asyncio
async def test_capped_error_status_answers_no_content() -> None:
    # given
    response = _StreamedResponse([b"not found"], status_code=404)
    session = _FakeSession([response])

    # when
    body = await _fetch(session, max_bytes=100)

    # then
    assert body == ""
    assert response.closed is True


_PAGE_URL = _START_URL
_PAGE = "<html><body>" + "zażółć " * 4000 + "</body></html>"
_PAGE_BYTES = _PAGE.encode("utf-8")
_PAGE_ENCODERS: dict[str, Callable[[bytes], bytes]] = {
    "gzip": gzip.compress,
    "deflate": zlib.compress,
    "br": brotli.compress,
    "zstd": zstandard.ZstdCompressor().compress,
}


async def _read_page(session: _FakeSession) -> str:
    with (
        patch(_CHECK, side_effect=_pinned_check),
        patch(_LIBRARY_CHECK, side_effect=_pinned_check),
        patch(_SESSION, return_value=session),
        patch(_COOKIES, new=AsyncMock(return_value={})),
        patch(_USER_AGENT, new=AsyncMock(return_value=None)),
    ):
        return await fetcher.fetch_with_curl_cffi(_PAGE_URL, lambda: "UA", "page-read")


@pytest.mark.parametrize("coding", sorted(_PAGE_ENCODERS))
async def test_a_compressed_page_reads_correctly_with_libcurl_decoding_off(coding: str) -> None:
    # given
    answer = _StreamedResponse(
        [_PAGE_ENCODERS[coding](_PAGE_BYTES)],
        headers={"content-type": "text/html; charset=utf-8", "content-encoding": coding},
    )
    session = _FakeSession([answer])

    # when
    html = await _read_page(session)

    # then the page is the original text, streamed, and the fingerprint headers are not touched
    assert html == _PAGE
    assert session.kwargs[0]["stream"] is True
    assert session.curl_options[CurlOpt.HTTP_CONTENT_DECODING] == 0
    assert session.kwargs[0]["headers"] == {"User-Agent": "UA"}
    assert answer.closed is True


async def test_a_compressed_page_above_the_read_limit_ends_as_a_tier_failure_with_a_warning(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    # given
    monkeypatch.setattr(settings, "READ_RESPONSE_MAX_BYTES", 1024)
    answer = _StreamedResponse([gzip.compress(bytes(1024 * 1024))], headers={"content-encoding": "gzip"})

    # when
    with caplog.at_level(logging.WARNING, logger="src.reader.strategies.curl_cffi_fetcher"):
        html = await _read_page(_FakeSession([answer]))

    # then
    assert html == ""
    assert "above the cap of 1024 bytes" in caplog.text


async def test_a_page_at_exactly_the_read_limit_is_read(monkeypatch: pytest.MonkeyPatch) -> None:
    # given
    monkeypatch.setattr(settings, "READ_RESPONSE_MAX_BYTES", len(_PAGE_BYTES))
    answer = _StreamedResponse(
        [gzip.compress(_PAGE_BYTES)],
        headers={"content-type": "text/html; charset=utf-8", "content-encoding": "gzip"},
    )

    # when
    html = await _read_page(_FakeSession([answer]))

    # then
    assert html == _PAGE


async def test_a_page_with_a_corrupt_coding_ends_as_a_tier_failure(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # given
    answer = _StreamedResponse([b"not gzip"], headers={"content-encoding": "gzip"})

    # when
    with caplog.at_level(logging.WARNING, logger="src.reader.strategies.curl_cffi_fetcher"):
        html = await _read_page(_FakeSession([answer]))

    # then
    assert html == ""
    assert "failed to fetch URL" in caplog.text


async def test_a_page_read_stops_its_answer_before_following_a_redirect() -> None:
    # given
    redirect = _redirect(_HOP_URL)
    final = _StreamedResponse([_PAGE_BYTES], headers={"content-type": "text/html; charset=utf-8"})

    # when
    html = await _read_page(_FakeSession([redirect, final]))

    # then
    assert html == _PAGE
    assert redirect.quit_now.is_set()
    assert final.closed is True


async def test_a_sitemap_gzipped_as_a_file_and_as_a_transfer_is_unpacked_twice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # given a .xml.gz file the server also sends with Content-Encoding gzip
    xml = b"<urlset><url><loc>https://example.com/a</loc></url></urlset>"
    monkeypatch.setattr(settings, "CRAWL_SITEMAP_MAX_BYTES", 1024)
    answer = _StreamedResponse([gzip.compress(gzip.compress(xml))], headers={"content-encoding": "gzip"})
    session = _FakeSession([answer])

    # when
    with (
        patch(_CHECK, side_effect=_pinned_check),
        patch(_LIBRARY_CHECK, side_effect=_pinned_check),
        patch(_SESSION, return_value=session),
        patch(_COOKIES, new=AsyncMock(return_value={})),
        patch(_USER_AGENT, new=AsyncMock(return_value=None)),
    ):
        body = await fetcher.fetch_with_curl_cffi(
            _START_URL, lambda: "UA", "crawl-sitemap", max_bytes=1024, unpack=_unpack_sitemap
        )

    # then
    assert body == xml.decode()
    assert cast("dict[str, str]", session.kwargs[0]["headers"])["Accept-Encoding"] == "identity"


async def test_a_sitemap_transfer_coding_that_inflates_past_the_cap_is_skipped() -> None:
    # given a wire body well under the cap that inflates past it
    answer = _StreamedResponse([gzip.compress(bytes(1024 * 1024))], headers={"content-encoding": "gzip"})

    # when
    body = await _fetch(_FakeSession([answer]), 16 * 1024)

    # then
    assert body == ""

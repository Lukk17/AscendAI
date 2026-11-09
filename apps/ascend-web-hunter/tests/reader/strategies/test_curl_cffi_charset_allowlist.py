"""The whole-body curl_cffi path decodes only with a charset on the allowlist."""

import codecs
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from ascend_python_common.uri_guard import FetchPolicy, FetchTarget
from curl_cffi import CurlOpt
from curl_cffi.requests import Headers, Response

from src.reader.strategies import curl_cffi_fetcher as fetcher
from tests.reader.strategies.conftest import HostileCodec, make_streaming

_URL = "https://start.example/page"
_POLISH_PAGE = "<html><body>zażółć gęślą jaźń</body></html>"

_CHECK = "src.reader.strategies.curl_cffi_fetcher.check_fetch_uri"
_SESSION = "src.reader.strategies.curl_cffi_fetcher.requests.AsyncSession"
_COOKIES = "src.reader.strategies.curl_cffi_fetcher.cookie_manager.get_flat_cookies"
_USER_AGENT = "src.reader.strategies.curl_cffi_fetcher.cookie_manager.get_user_agent"


def _real_response(body: bytes, content_type: str | None) -> Response:
    response: Response = make_streaming(Response(), body)
    response.status_code = 200
    response.headers = Headers({} if content_type is None else {"Content-Type": content_type})
    response.url = _URL
    return response


class _FakeSession:
    def __init__(self, response: Response) -> None:
        self.curl_options: dict[Any, Any] = {}
        self.sent_headers: dict[str, str] = {}
        self._response = response

    async def __aenter__(self) -> "_FakeSession":
        return self

    async def __aexit__(self, *_exc: object) -> bool:
        return False

    async def get(self, _url: str, **kwargs: Any) -> Response:
        self.sent_headers = kwargs["headers"]
        return self._response


async def _checked(uri: str, _policy: FetchPolicy) -> FetchTarget:
    return FetchTarget(url=uri, host="start.example", port=443, addresses=("93.184.216.34",))


async def _read(session: _FakeSession) -> str:
    with (
        patch(_CHECK, side_effect=_checked),
        patch(_SESSION, return_value=session),
        patch(_COOKIES, new=AsyncMock(return_value={})),
        patch(_USER_AGENT, new=AsyncMock(return_value=None)),
    ):
        return await fetcher.fetch_with_curl_cffi(_URL, lambda: "UA", "test")


@pytest.mark.parametrize(
    ("content_type", "charset"),
    [
        ("text/html; charset=iso-8859-2", "iso-8859-2"),
        ("text/html; charset=windows-1250", "windows-1250"),
        ('text/html; charset="ISO-8859-2"', "iso-8859-2"),
        ("text/html; CHARSET=Windows-1250", "windows-1250"),
    ],
)
async def test_a_real_page_in_an_allowed_charset_decodes_correctly(content_type: str, charset: str) -> None:
    # given
    session = _FakeSession(_real_response(_POLISH_PAGE.encode(charset), content_type))

    # when
    html = await _read(session)

    # then
    assert html == _POLISH_PAGE


@pytest.mark.parametrize(
    ("label", "page"),
    [
        ("windows-874", "<html><body>สวัสดี</body></html>"),
        ("windows-31j", "<html><body>こんにちは</body></html>"),
    ],
)
async def test_a_web_label_python_spells_differently_still_decodes(label: str, page: str) -> None:
    # given
    codec = {"windows-874": "cp874", "windows-31j": "cp932"}[label]
    session = _FakeSession(_real_response(page.encode(codec), f"text/html; charset={label}"))

    # when
    html = await _read(session)

    # then
    assert html == page


@pytest.mark.parametrize(
    "content_type",
    [
        "text/html; charset=punycode",
        "text/html; charset=PunyCode",
        "text/html; charset=idna",
        "text/html; charset=utf-7",
        "text/html; charset=unicode_escape",
        "text/html; charset=no-such-charset",
        "text/html",
        None,
    ],
)
async def test_a_charset_off_the_allowlist_falls_back_to_utf8(content_type: str | None) -> None:
    # given
    session = _FakeSession(_real_response(_POLISH_PAGE.encode(), content_type))

    # when
    html = await _read(session)

    # then
    assert html == _POLISH_PAGE


async def test_a_body_invalid_in_utf8_is_replaced_and_does_not_fail() -> None:
    # given a body that is not utf-8 under a charset off the allowlist
    session = _FakeSession(
        _real_response(b"<html><body>caf\xe9</body></html>", "text/html; charset=punycode")
    )

    # when
    html = await _read(session)

    # then
    assert html == "<html><body>caf\ufffd</body></html>"


async def test_the_codec_a_server_names_off_the_allowlist_is_never_called(
    hostile_codec: HostileCodec,
) -> None:
    # given
    session = _FakeSession(_real_response(b"<html></html>", f"text/html; charset={hostile_codec.name}"))

    # when
    html = await _read(session)

    # then
    assert html == "<html></html>"
    hostile_codec.decode.assert_not_called()


async def test_the_page_read_keeps_the_impersonated_headers_with_libcurl_decoding_off() -> None:
    # given
    session = _FakeSession(_real_response(b"<html></html>", "text/html"))

    # when
    await _read(session)

    # then
    assert session.curl_options[CurlOpt.HTTP_CONTENT_DECODING] == 0
    assert "Accept-Encoding" not in session.sent_headers


@pytest.mark.parametrize("charset", sorted(fetcher.WEB_CHARSETS))
def test_every_allowed_charset_is_a_text_codec_python_can_read(charset: str) -> None:
    # when
    info = codecs.lookup(charset)

    # then
    assert info._is_text_encoding is True


@pytest.mark.parametrize(
    "label",
    [
        "ks_c_5601-1987",
        "euc_kr",
        "cp949",
        "iso-8859-11",
        "iso_8859-1",
        "iso_8859-2",
        *(f"iso8859-{part}" for part in (*range(1, 11), *range(13, 17))),
    ],
)
def test_a_web_label_real_sites_declare_is_allowed_and_decodes(label: str) -> None:
    # when
    charset = fetcher._allowed_charset(f"text/html; charset={label}")

    # then
    assert charset == label
    assert codecs.lookup(charset)._is_text_encoding is True


def test_windows_949_decodes_with_cp949() -> None:
    # when
    charset = fetcher._allowed_charset("text/html; charset=windows-949")

    # then
    assert charset == "cp949"
    assert "한글".encode(charset).decode(charset) == "한글"


@pytest.mark.parametrize("codec", ["punycode", "idna", "utf-7", "unicode_escape", "raw_unicode_escape"])
def test_no_quadratic_or_escaping_codec_is_on_the_allowlist(codec: str) -> None:
    # then
    assert codec not in fetcher.WEB_CHARSETS

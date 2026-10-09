from collections.abc import AsyncIterator
from pathlib import Path
from unittest.mock import patch

import pytest
from ascend_python_common.uri_guard import FetchPolicy, FetchTarget, check_fetch_uri
from ascend_python_common.uri_guard_aiohttp import current_pin
from fastmcp.exceptions import ToolError

from src.api.exception_handlers import DownloadFailedError
from src.api.mcp import mcp_server
from src.api.mcp.mcp_server import mcp
from src.config.config import settings


class _FakeContent:
    def __init__(self, body: bytes) -> None:
        self._body = body

    async def iter_chunked(self, size: int) -> AsyncIterator[bytes]:
        for offset in range(0, len(self._body), size):
            yield self._body[offset : offset + size]


class _FakeResponse:
    def __init__(self, status: int, body: bytes, headers: dict[str, str] | None = None) -> None:
        self.status = status
        self.headers = headers or {}
        self.content = _FakeContent(body)
        self.released = False

    def release(self) -> None:
        self.released = True


class _CountingSession:
    def __init__(self, response: _FakeResponse) -> None:
        self._response = response
        self.calls = 0

    async def get(self, url: str, **kwargs: object) -> _FakeResponse:
        self.calls += 1
        return self._response


async def test_tool_refuses_unsupported_scheme_with_unsafe_uri() -> None:
    # given
    uri = "ftp://example.com/scan.png"
    # when
    with pytest.raises(ToolError, match=r"^UNSAFE_URI: ") as exc_info:
        await mcp.call_tool("ocr_submit", {"file_uri": uri, "lang": "en"})
    # then
    assert str(exc_info.value).startswith("UNSAFE_URI: ")


async def test_tool_refuses_private_literal_with_unsafe_uri() -> None:
    # given
    uri = "http://169.254.169.254/latest/meta-data"
    # when
    with pytest.raises(ToolError, match=r"^UNSAFE_URI: ") as exc_info:
        await mcp.call_tool("ocr_submit", {"file_uri": uri, "lang": "en"})
    # then
    assert str(exc_info.value).startswith("UNSAFE_URI: ")


async def test_tool_refuses_user_info_uri_with_unsafe_uri_and_no_secret() -> None:
    # given
    uri = "https://user:secret@example.com/scan.png"
    # when
    with pytest.raises(ToolError, match=r"^UNSAFE_URI: ") as exc_info:
        await mcp.call_tool("ocr_submit", {"file_uri": uri, "lang": "en"})
    # then
    assert "secret" not in str(exc_info.value)


async def test_tool_refuses_file_uri_without_root_with_unsafe_uri(monkeypatch: pytest.MonkeyPatch) -> None:
    # given
    monkeypatch.setattr(settings, "MCP_FILE_URI_ROOT", None)
    uri = "file:///tmp/scan.png"
    # when
    with pytest.raises(ToolError, match=r"^UNSAFE_URI: ") as exc_info:
        await mcp.call_tool("ocr_submit", {"file_uri": uri, "lang": "en"})
    # then
    assert str(exc_info.value).startswith("UNSAFE_URI: ")


async def test_tool_refuses_file_uri_escaping_its_root_with_unsafe_uri(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # given
    jail = tmp_path / "jail"
    jail.mkdir()
    monkeypatch.setattr(settings, "MCP_FILE_URI_ROOT", str(jail))
    uri = (tmp_path / "outside.png").as_uri()
    # when
    with pytest.raises(ToolError, match=r"^UNSAFE_URI: ") as exc_info:
        await mcp.call_tool("ocr_submit", {"file_uri": uri, "lang": "en"})
    # then
    assert str(exc_info.value).startswith("UNSAFE_URI: ")


async def test_tool_refuses_host_without_name_with_unsafe_uri() -> None:
    # given
    uri = "http:///scan.png"
    # when
    with pytest.raises(ToolError, match=r"^UNSAFE_URI: ") as exc_info:
        await mcp.call_tool("ocr_submit", {"file_uri": uri, "lang": "en"})
    # then
    assert str(exc_info.value).startswith("UNSAFE_URI: ")


async def test_tool_answers_302_with_download_failed_and_sends_no_second_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # given
    monkeypatch.setattr(settings, "ALLOWED_PRIVATE_HOSTS", ("example.com",))
    session = _CountingSession(_FakeResponse(status=302, body=b"", headers={"Location": "/other.png"}))
    # when
    with (
        patch.object(mcp_server, "_http_session", session),
        pytest.raises(ToolError, match=r"^DOWNLOAD_FAILED: "),
    ):
        await mcp.call_tool("ocr_submit", {"file_uri": "http://example.com/scan.png", "lang": "en"})
    # then
    assert session.calls == 1


async def test_tool_follows_one_redirect_with_fetch_max_redirect_hops_1(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # given
    monkeypatch.setattr(settings, "ALLOWED_PRIVATE_HOSTS", ("example.com",))
    monkeypatch.setattr(settings, "FETCH_MAX_REDIRECT_HOPS", 1)
    session = _CountingSession(_FakeResponse(status=302, body=b"", headers={"Location": "/other.png"}))
    # when
    with (
        patch.object(mcp_server, "_http_session", session),
        pytest.raises(ToolError, match=r"^DOWNLOAD_FAILED: "),
    ):
        await mcp.call_tool("ocr_submit", {"file_uri": "http://example.com/scan.png", "lang": "en"})
    # then
    assert session.calls == 2


def _pinned_target() -> FetchTarget:
    return FetchTarget(
        url="http://example.com/scan.png",
        host="example.com",
        port=80,
        addresses=("93.184.216.34",),
    )


class _PinRecordingSession(_CountingSession):
    def __init__(self, response: _FakeResponse) -> None:
        super().__init__(response)
        self.pins: list[FetchTarget | None] = []

    async def get(self, url: str, **kwargs: object) -> _FakeResponse:
        self.pins.append(current_pin.get())
        return await super().get(url, **kwargs)


async def test_download_sends_pinned_to_the_checked_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # given
    target = _pinned_target()
    session = _PinRecordingSession(_FakeResponse(status=200, body=b"data"))
    monkeypatch.setattr(mcp_server, "_http_session", session)
    # when
    data, filename = await mcp_server._download_http(target)
    # then
    assert data == b"data"
    assert filename == "scan.png"
    assert session.calls == 1
    assert [pin.addresses if pin is not None else () for pin in session.pins] == [("93.184.216.34",)]


async def test_tool_checks_uri_once_before_download(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # given
    monkeypatch.setattr(settings, "ALLOWED_PRIVATE_HOSTS", ("example.com",))
    calls: list[str] = []

    async def _counting(uri: str, policy: FetchPolicy) -> FetchTarget:
        calls.append(uri)
        return await check_fetch_uri(uri, policy)

    monkeypatch.setattr("src.api.mcp.mcp_server.check_fetch_uri", _counting)
    session = _CountingSession(_FakeResponse(status=200, body=b"data"))
    # when
    with (
        patch.object(mcp_server, "_http_session", session),
        pytest.raises(ToolError, match=r"^UNSUPPORTED_FILE_TYPE: "),
    ):
        await mcp.call_tool("ocr_submit", {"file_uri": "http://example.com/scan.png", "lang": "en"})
    # then
    assert calls == ["http://example.com/scan.png"]
    assert session.calls == 1


async def test_malformed_content_length_answers_download_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # given
    session = _CountingSession(
        _FakeResponse(status=200, body=b"data", headers={"Content-Length": "not-a-number"})
    )
    monkeypatch.setattr(mcp_server, "_http_session", session)
    # when
    with pytest.raises(DownloadFailedError):
        await mcp_server._download_http(_pinned_target())
    # then
    assert session.calls == 1


async def test_tool_answers_malformed_content_length_with_download_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # given
    monkeypatch.setattr(settings, "ALLOWED_PRIVATE_HOSTS", ("example.com",))
    session = _CountingSession(
        _FakeResponse(status=200, body=b"data", headers={"Content-Length": "not-a-number"})
    )
    # when
    with (
        patch.object(mcp_server, "_http_session", session),
        pytest.raises(ToolError, match=r"^DOWNLOAD_FAILED: "),
    ):
        await mcp.call_tool("ocr_submit", {"file_uri": "http://example.com/scan.png", "lang": "en"})
    # then
    assert session.calls == 1

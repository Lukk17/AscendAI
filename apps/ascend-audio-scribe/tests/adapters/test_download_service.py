from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest
from anyio import Path as AsyncPath

from src.adapters import download_service
from src.api.exception_handlers import FileSizeExceededError
from src.config.config import settings


def _fake_guarded(response: "_FakeResponse") -> Any:
    # given
    import contextlib as _ctx

    @_ctx.asynccontextmanager
    async def _cm() -> AsyncIterator["_FakeResponse"]:
        # when
        yield response

    # then
    return _cm()


def test_extract_audio_suffix_found() -> None:
    # when
    suffix = download_service._extract_audio_suffix_from_query("file=foo.mp3&sig=abc")

    # then
    assert suffix == ".mp3"


def test_extract_audio_suffix_none() -> None:
    # when / then
    assert download_service._extract_audio_suffix_from_query("sig=abc") == ""


@pytest.mark.asyncio
async def test_download_to_temp_rejects_unsupported_scheme() -> None:
    # when / then
    with pytest.raises(ValueError, match="Unsupported URI scheme"):
        await download_service.download_to_temp_async("ftp://example.com/x.wav")


@pytest.mark.asyncio
async def test_download_to_temp_file_scheme_success(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # given
    source = tmp_path / "src.wav"
    source.write_bytes(b"abcd" * 256)
    monkeypatch.setattr(settings, "MCP_FILE_URI_ROOT", str(tmp_path))

    # when
    result = await download_service.download_to_temp_async("file:///src.wav")

    # then
    written = await AsyncPath(result).read_bytes()
    await AsyncPath(result).unlink()
    assert written == source.read_bytes()


@pytest.mark.asyncio
async def test_download_to_temp_file_scheme_enforces_cap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # given
    source = tmp_path / "big.wav"
    source.write_bytes(b"x" * 4096)
    monkeypatch.setattr(settings, "MCP_FILE_URI_ROOT", str(tmp_path))
    monkeypatch.setattr(settings, "MAX_DOWNLOAD_BYTES", 100)

    # when / then
    with pytest.raises(FileSizeExceededError):
        await download_service.download_to_temp_async("file:///big.wav")


class _FakeAsyncBody:
    """Async-iterable body. `iter_chunked` is genuinely async (yields under
    the asyncio loop) - the `await asyncio.sleep(0)` between chunks both
    satisfies the async-without-await lint and lets pytest-asyncio schedule
    cooperatively as a real aiohttp response would."""

    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = chunks

    async def iter_chunked(self, _size: int) -> AsyncIterator[bytes]:
        import asyncio as _aio

        for chunk in self._chunks:
            await _aio.sleep(0)
            yield chunk


class _FakeResponse:
    def __init__(
        self, status: int = 200, content_length: int | None = None, chunks: list[bytes] | None = None
    ) -> None:
        self.status = status
        self.content_length = content_length
        self.content = _FakeAsyncBody(chunks or [])


@pytest.mark.asyncio
async def test_download_http_success(monkeypatch: pytest.MonkeyPatch) -> None:
    # given
    monkeypatch.setattr(
        download_service,
        "check_fetch_uri",
        AsyncMock(return_value=None),
    )
    response = _FakeResponse(status=200, chunks=[b"abc", b"def"])
    monkeypatch.setattr(download_service, "guarded_get", lambda *_a, **_kw: _fake_guarded(response))

    # when
    path = await download_service.download_to_temp_async("http://example.com/a.wav")

    # then
    written = await AsyncPath(path).read_bytes()
    await AsyncPath(path).unlink()
    assert written == b"abcdef"


@pytest.mark.asyncio
async def test_download_http_non_200(monkeypatch: pytest.MonkeyPatch) -> None:
    # given
    monkeypatch.setattr(download_service, "check_fetch_uri", AsyncMock(return_value=None))
    response = _FakeResponse(status=500)
    monkeypatch.setattr(download_service, "guarded_get", lambda *_a, **_kw: _fake_guarded(response))

    # when / then
    with pytest.raises(ValueError, match="HTTP 500"):
        await download_service.download_to_temp_async("http://example.com/a.wav")


@pytest.mark.asyncio
async def test_download_http_content_length_too_big(monkeypatch: pytest.MonkeyPatch) -> None:
    # given
    monkeypatch.setattr(download_service, "check_fetch_uri", AsyncMock(return_value=None))
    monkeypatch.setattr(settings, "MAX_DOWNLOAD_BYTES", 100)
    response = _FakeResponse(status=200, content_length=200, chunks=[])
    monkeypatch.setattr(download_service, "guarded_get", lambda *_a, **_kw: _fake_guarded(response))

    # when / then
    with pytest.raises(FileSizeExceededError):
        await download_service.download_to_temp_async("http://example.com/a.wav")


@pytest.mark.asyncio
async def test_download_http_streamed_body_too_big(monkeypatch: pytest.MonkeyPatch) -> None:
    # given
    monkeypatch.setattr(download_service, "check_fetch_uri", AsyncMock(return_value=None))
    monkeypatch.setattr(settings, "MAX_DOWNLOAD_BYTES", 5)
    response = _FakeResponse(status=200, content_length=None, chunks=[b"hello", b"world"])
    monkeypatch.setattr(download_service, "guarded_get", lambda *_a, **_kw: _fake_guarded(response))

    # when / then
    with pytest.raises(FileSizeExceededError):
        await download_service.download_to_temp_async("http://example.com/a.wav")


@pytest.mark.asyncio
async def test_download_http_with_query_suffix(monkeypatch: pytest.MonkeyPatch) -> None:
    # given
    monkeypatch.setattr(download_service, "check_fetch_uri", AsyncMock(return_value=None))
    response = _FakeResponse(status=200, chunks=[b"q"])
    monkeypatch.setattr(download_service, "guarded_get", lambda *_a, **_kw: _fake_guarded(response))

    # when
    path = await download_service.download_to_temp_async("https://x.test/path?file=foo.mp3&sig=z")

    # then
    assert path.endswith(".mp3")
    await AsyncPath(path).unlink()

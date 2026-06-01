from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from src.adapters import download_service
from src.api.exception_handlers import FileSizeExceededError


def test_extract_audio_suffix_found() -> None:
    suffix = download_service._extract_audio_suffix_from_query("file=foo.mp3&sig=abc")
    assert suffix == ".mp3"


def test_extract_audio_suffix_none() -> None:
    assert download_service._extract_audio_suffix_from_query("sig=abc") == ""


def test_is_safe_ip_public() -> None:
    assert download_service._is_safe_ip("8.8.8.8") is True


@pytest.mark.parametrize("addr", ["10.0.0.1", "192.168.1.1", "127.0.0.1", "169.254.169.254", "::1", "fe80::1"])
def test_is_safe_ip_blocks_private(addr: str) -> None:
    assert download_service._is_safe_ip(addr) is False


def test_is_safe_ip_invalid() -> None:
    assert download_service._is_safe_ip("not-an-ip") is False


def test_validate_http_target_requires_hostname() -> None:
    with pytest.raises(ValueError, match="no hostname"):
        download_service._validate_http_target(None)


def test_validate_http_target_allows_listed_host(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(download_service.settings, "MCP_ALLOWED_HOSTS", ["minio"])
    download_service._validate_http_target("minio")


def test_validate_http_target_resolves_to_safe_ip() -> None:
    with patch.object(download_service, "_resolve_to_ips", return_value=["8.8.8.8"]):
        download_service._validate_http_target("example.com")


def test_validate_http_target_rejects_unresolvable() -> None:
    with patch.object(download_service, "_resolve_to_ips", return_value=[]), \
         pytest.raises(ValueError, match="Could not resolve"):
        download_service._validate_http_target("nope.invalid")


def test_validate_http_target_rejects_private_ip() -> None:
    with patch.object(download_service, "_resolve_to_ips", return_value=["169.254.169.254"]), \
         pytest.raises(ValueError, match="SSRF"):
        download_service._validate_http_target("attacker.com")


def test_resolve_to_ips_returns_empty_on_failure() -> None:
    import socket
    with patch.object(download_service.socket, "getaddrinfo", side_effect=socket.gaierror()):
        assert download_service._resolve_to_ips("never.invalid") == []


def test_resolve_to_ips_returns_list_on_success() -> None:
    fake_infos = [(0, 0, 0, "", ("203.0.113.5", 0))]
    with patch.object(download_service.socket, "getaddrinfo", return_value=fake_infos):
        assert download_service._resolve_to_ips("example.com") == ["203.0.113.5"]


def test_resolve_file_uri_requires_root(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(download_service.settings, "MCP_FILE_URI_ROOT", None)
    with pytest.raises(ValueError, match="disabled"):
        download_service._resolve_file_uri("/etc/passwd")


def test_resolve_file_uri_rejects_escape(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(download_service.settings, "MCP_FILE_URI_ROOT", str(tmp_path))
    with pytest.raises(ValueError, match="escapes"):
        download_service._resolve_file_uri("/../etc/passwd")


def test_resolve_file_uri_rejects_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(download_service.settings, "MCP_FILE_URI_ROOT", str(tmp_path))
    with pytest.raises(ValueError, match="not found"):
        download_service._resolve_file_uri("/missing.wav")


def test_resolve_file_uri_returns_jailed_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(download_service.settings, "MCP_FILE_URI_ROOT", str(tmp_path))
    (tmp_path / "ok.wav").write_text("data", encoding="utf-8")
    resolved = download_service._resolve_file_uri("/ok.wav")
    assert resolved == (tmp_path / "ok.wav").resolve()


@pytest.mark.asyncio
async def test_download_to_temp_rejects_unsupported_scheme() -> None:
    with pytest.raises(ValueError, match="Unsupported URI scheme"):
        await download_service.download_to_temp_async("ftp://example.com/x.wav")


@pytest.mark.asyncio
async def test_download_to_temp_file_scheme_success(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "src.wav"
    source.write_bytes(b"abcd" * 256)
    monkeypatch.setattr(download_service.settings, "MCP_FILE_URI_ROOT", str(tmp_path))

    result = await download_service.download_to_temp_async("file:///src.wav")
    written = Path(result).read_bytes()
    Path(result).unlink()
    assert written == source.read_bytes()


@pytest.mark.asyncio
async def test_download_to_temp_file_scheme_enforces_cap(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "big.wav"
    source.write_bytes(b"x" * 4096)
    monkeypatch.setattr(download_service.settings, "MCP_FILE_URI_ROOT", str(tmp_path))
    monkeypatch.setattr(download_service.settings, "MAX_DOWNLOAD_BYTES", 100)
    with pytest.raises(FileSizeExceededError):
        await download_service.download_to_temp_async("file:///big.wav")


class _FakeAsyncBody:
    """Async-iterable body. `iter_chunked` is genuinely async (yields under
    the asyncio loop) — the `await asyncio.sleep(0)` between chunks both
    satisfies the async-without-await lint and lets pytest-asyncio schedule
    cooperatively as a real aiohttp response would."""

    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = chunks

    async def iter_chunked(self, _size: int):
        import asyncio as _aio
        for chunk in self._chunks:
            await _aio.sleep(0)
            yield chunk


class _FakeResponse:
    """aiohttp response shim. Async-context-manager methods cooperatively
    yield via `asyncio.sleep(0)` so the lint and the asyncio scheduler
    both see real awaitable work."""

    def __init__(self, status: int = 200, content_length: int | None = None, chunks: list[bytes] | None = None) -> None:
        self.status = status
        self.content_length = content_length
        self.content = _FakeAsyncBody(chunks or [])

    async def __aenter__(self) -> "_FakeResponse":
        import asyncio as _aio
        await _aio.sleep(0)
        return self

    async def __aexit__(self, *_a: Any) -> None:
        import asyncio as _aio
        await _aio.sleep(0)


class _FakeSession:
    def __init__(self, response: _FakeResponse) -> None:
        self._response = response

    async def __aenter__(self) -> "_FakeSession":
        import asyncio as _aio
        await _aio.sleep(0)
        return self

    async def __aexit__(self, *_a: Any) -> None:
        import asyncio as _aio
        await _aio.sleep(0)

    def get(self, _url: str) -> _FakeResponse:
        return self._response


@pytest.mark.asyncio
async def test_download_http_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        download_service,
        "_validate_http_target",
        MagicMock(return_value=None),
    )
    response = _FakeResponse(status=200, chunks=[b"abc", b"def"])
    monkeypatch.setattr(download_service.aiohttp, "ClientSession", lambda *_a, **_kw: _FakeSession(response))
    monkeypatch.setattr(download_service.aiohttp, "ClientTimeout", lambda **_kw: None)

    path = await download_service.download_to_temp_async("http://example.com/a.wav")
    written = Path(path).read_bytes()
    Path(path).unlink()
    assert written == b"abcdef"


@pytest.mark.asyncio
async def test_download_http_non_200(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(download_service, "_validate_http_target", MagicMock(return_value=None))
    response = _FakeResponse(status=500)
    monkeypatch.setattr(download_service.aiohttp, "ClientSession", lambda *_a, **_kw: _FakeSession(response))
    monkeypatch.setattr(download_service.aiohttp, "ClientTimeout", lambda **_kw: None)
    with pytest.raises(ValueError, match="HTTP 500"):
        await download_service.download_to_temp_async("http://example.com/a.wav")


@pytest.mark.asyncio
async def test_download_http_content_length_too_big(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(download_service, "_validate_http_target", MagicMock(return_value=None))
    monkeypatch.setattr(download_service.settings, "MAX_DOWNLOAD_BYTES", 100)
    response = _FakeResponse(status=200, content_length=200, chunks=[])
    monkeypatch.setattr(download_service.aiohttp, "ClientSession", lambda *_a, **_kw: _FakeSession(response))
    monkeypatch.setattr(download_service.aiohttp, "ClientTimeout", lambda **_kw: None)
    with pytest.raises(FileSizeExceededError):
        await download_service.download_to_temp_async("http://example.com/a.wav")


@pytest.mark.asyncio
async def test_download_http_streamed_body_too_big(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(download_service, "_validate_http_target", MagicMock(return_value=None))
    monkeypatch.setattr(download_service.settings, "MAX_DOWNLOAD_BYTES", 5)
    response = _FakeResponse(status=200, content_length=None, chunks=[b"hello", b"world"])
    monkeypatch.setattr(download_service.aiohttp, "ClientSession", lambda *_a, **_kw: _FakeSession(response))
    monkeypatch.setattr(download_service.aiohttp, "ClientTimeout", lambda **_kw: None)
    with pytest.raises(FileSizeExceededError):
        await download_service.download_to_temp_async("http://example.com/a.wav")


@pytest.mark.asyncio
async def test_download_http_with_query_suffix(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(download_service, "_validate_http_target", MagicMock(return_value=None))
    response = _FakeResponse(status=200, chunks=[b"q"])
    monkeypatch.setattr(download_service.aiohttp, "ClientSession", lambda *_a, **_kw: _FakeSession(response))
    monkeypatch.setattr(download_service.aiohttp, "ClientTimeout", lambda **_kw: None)
    path = await download_service.download_to_temp_async("https://x.test/path?file=foo.mp3&sig=z")
    assert path.endswith(".mp3")
    Path(path).unlink()

import asyncio
import socket
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import aiohttp
import pytest
from anyio import Path as AsyncPath
from ascend_python_common.uri_guard import UnsafeUriError

from src.adapters import download_service
from src.api.exception_handlers import error_registry
from src.config.config import settings

PUBLIC_V4 = "93.184.216.34"


async def _fake_dns(monkeypatch: pytest.MonkeyPatch, ips: list[str]) -> None:
    # given
    loop = asyncio.get_running_loop()

    async def fake(
        host: str, port: int, *args: object, **kwargs: object
    ) -> list[tuple[int, int, int, str, tuple[str, int]]]:
        # when
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port)) for ip in ips]

    # then
    monkeypatch.setattr(loop, "getaddrinfo", fake)
    assert callable(loop.getaddrinfo)


class _StubBody:
    def __init__(self, chunks: list[bytes]) -> None:
        # given
        self._chunks = chunks

    async def iter_chunked(self, _size: int) -> AsyncIterator[bytes]:
        # when
        for chunk in self._chunks:
            await asyncio.sleep(0)
            yield chunk
        # then
        assert True


class _StubResponse:
    def __init__(
        self, url: str, status: int, location: str | None, chunks: list[bytes] | None = None
    ) -> None:
        # given
        self.url = url
        self.status = status
        self.headers = {"Location": location} if location is not None else {}
        self.content_length: int | None = None
        self.content = _StubBody(chunks or [])

    def release(self) -> None:
        # when
        pass

    def __await__(self) -> Any:
        # when
        async def _self() -> "_StubResponse":
            await asyncio.sleep(0)
            return self

        return _self().__await__()

    async def __aenter__(self) -> "_StubResponse":
        # when
        await asyncio.sleep(0)
        return self

    async def __aexit__(self, *args: object) -> None:
        # when
        await asyncio.sleep(0)


class _StubHttpServer:
    def __init__(
        self, table: dict[str, tuple[int, str | None]], bodies: dict[str, list[bytes]] | None = None
    ) -> None:
        # given
        self.table = table
        self.bodies = bodies or {}
        self.calls: list[str] = []

    async def __aenter__(self) -> "_StubHttpServer":
        # when
        await asyncio.sleep(0)
        return self

    async def __aexit__(self, *args: object) -> None:
        # when
        await asyncio.sleep(0)

    def get(self, url: str, **kwargs: object) -> _StubResponse:
        # when
        self.calls.append(url)
        if "allow_redirects" in kwargs:
            assert kwargs.get("allow_redirects") is False
        status, location = self.table[url]
        return _StubResponse(url, status, location, self.bodies.get(url, []))


def _patch_session(monkeypatch: pytest.MonkeyPatch, stub: _StubHttpServer) -> None:
    # given
    monkeypatch.setattr(aiohttp, "ClientSession", lambda *args, **kwargs: stub)
    monkeypatch.setattr(aiohttp, "ClientTimeout", lambda **kwargs: None)
    # then
    assert True


@pytest.mark.asyncio
async def test_public_url_redirecting_to_private_address_fails_with_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # given
    await _fake_dns(monkeypatch, [PUBLIC_V4])
    monkeypatch.setattr(settings, "ALLOWED_PRIVATE_HOSTS", ())
    monkeypatch.setattr(settings, "MCP_FILE_URI_ROOT", None)
    stub = _StubHttpServer({"https://public.example/a.mp3": (302, "http://10.0.0.5/a.mp3")})
    _patch_session(monkeypatch, stub)
    # when
    with pytest.raises(UnsafeUriError) as exc_info:
        await download_service.download_to_temp_async("https://public.example/a.mp3")
    # then
    assert error_registry.lookup(exc_info.value) is not None
    assert "http://10.0.0.5/a.mp3" not in stub.calls
    assert stub.calls == ["https://public.example/a.mp3"]


@pytest.mark.asyncio
async def test_relative_location_resolved_against_returning_hop(monkeypatch: pytest.MonkeyPatch) -> None:
    # given
    await _fake_dns(monkeypatch, [PUBLIC_V4])
    monkeypatch.setattr(settings, "ALLOWED_PRIVATE_HOSTS", ())
    monkeypatch.setattr(settings, "MCP_FILE_URI_ROOT", None)
    stub = _StubHttpServer(
        {
            "https://public.example/a.mp3": (302, "/b.mp3"),
            "https://public.example/b.mp3": (200, None),
        },
        bodies={"https://public.example/b.mp3": [b"audio-bytes"]},
    )
    _patch_session(monkeypatch, stub)
    # when
    path = await download_service.download_to_temp_async("https://public.example/a.mp3")
    # then
    written = await AsyncPath(path).read_bytes()
    await AsyncPath(path).unlink()
    assert written == b"audio-bytes"
    assert stub.calls == ["https://public.example/a.mp3", "https://public.example/b.mp3"]


@pytest.mark.asyncio
async def test_file_location_refused_with_validation(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    # given
    await _fake_dns(monkeypatch, [PUBLIC_V4])
    monkeypatch.setattr(settings, "ALLOWED_PRIVATE_HOSTS", ())
    monkeypatch.setattr(settings, "MCP_FILE_URI_ROOT", str(tmp_path))
    stub = _StubHttpServer({"https://public.example/a.mp3": (302, "file:///etc/passwd")})
    _patch_session(monkeypatch, stub)
    # when
    with pytest.raises(UnsafeUriError) as exc_info:
        await download_service.download_to_temp_async("https://public.example/a.mp3")
    # then
    assert error_registry.lookup(exc_info.value) is not None
    assert stub.calls == ["https://public.example/a.mp3"]


@pytest.mark.asyncio
async def test_hop_to_allowed_private_host_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    # given
    await _fake_dns(monkeypatch, [PUBLIC_V4])
    monkeypatch.setattr(settings, "ALLOWED_PRIVATE_HOSTS", ("internal.example",))
    monkeypatch.setattr(settings, "MCP_FILE_URI_ROOT", None)
    stub = _StubHttpServer(
        {
            "https://public.example/a.mp3": (302, "http://internal.example/b.mp3"),
            "http://internal.example/b.mp3": (200, None),
        },
        bodies={"http://internal.example/b.mp3": [b"allowed-bytes"]},
    )
    _patch_session(monkeypatch, stub)
    # when
    path = await download_service.download_to_temp_async("https://public.example/a.mp3")
    # then
    written = await AsyncPath(path).read_bytes()
    await AsyncPath(path).unlink()
    assert written == b"allowed-bytes"
    assert stub.calls == ["https://public.example/a.mp3", "http://internal.example/b.mp3"]


@pytest.mark.asyncio
async def test_third_redirect_with_two_hops_answered_as_non_200_download_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # given
    await _fake_dns(monkeypatch, [PUBLIC_V4])
    monkeypatch.setattr(settings, "ALLOWED_PRIVATE_HOSTS", ())
    monkeypatch.setattr(settings, "MCP_FILE_URI_ROOT", None)
    monkeypatch.setattr(settings, "FETCH_MAX_REDIRECT_HOPS", 2)
    urls = [f"https://public.example/{i}.mp3" for i in range(3)]
    table: dict[str, tuple[int, str | None]] = {urls[i]: (302, f"/{i + 1}.mp3") for i in range(3)}
    stub = _StubHttpServer(table)
    _patch_session(monkeypatch, stub)
    # when
    with pytest.raises(ValueError, match="HTTP 302"):
        await download_service.download_to_temp_async("https://public.example/0.mp3")
    # then
    assert len(stub.calls) == 3
    assert stub.calls[0] == "https://public.example/0.mp3"


@pytest.mark.asyncio
async def test_eleventh_redirect_answered_as_non_200_download_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # given
    await _fake_dns(monkeypatch, [PUBLIC_V4])
    monkeypatch.setattr(settings, "ALLOWED_PRIVATE_HOSTS", ())
    monkeypatch.setattr(settings, "MCP_FILE_URI_ROOT", None)
    urls = [f"https://public.example/{i}.mp3" for i in range(11)]
    table: dict[str, tuple[int, str | None]] = {urls[i]: (302, f"/{i + 1}.mp3") for i in range(10)}
    table[urls[10]] = (302, "/11.mp3")
    stub = _StubHttpServer(table)
    _patch_session(monkeypatch, stub)
    # when
    with pytest.raises(ValueError, match="HTTP 302"):
        await download_service.download_to_temp_async("https://public.example/0.mp3")
    # then
    assert len(stub.calls) == 11
    assert stub.calls[0] == "https://public.example/0.mp3"

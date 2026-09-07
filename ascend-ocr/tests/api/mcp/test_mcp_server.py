import ipaddress
import socket as socket_mod
from pathlib import Path
from unittest.mock import AsyncMock, patch
from urllib.parse import urlparse

import aiohttp
import pytest

from src.api.exception_handlers import (
    DownloadFailedError,
    FileSizeExceededError,
    OcrProcessingError,
    UnsafeUriError,
    UnsupportedFileTypeError,
)
from src.api.mcp import mcp_server
from src.api.mcp.mcp_server import (
    _download_http,
    _enforce_size,
    _fetch_file,
    _is_blocked,
    _is_within,
    _read_jailed_file,
    _validate_host,
    mcp_lifespan,
    ocr_process,
)
from src.config.config import settings
from tests.conftest import PNG_MAGIC_BYTES, VALID_PNG_BYTES, OcrResponseFactory


class _FakeResponse:
    def __init__(self, status: int, body: bytes, headers: dict[str, str] | None = None) -> None:
        self.status = status
        self.headers = headers or {}
        self.content = _FakeContent(body)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False


class _FakeContent:
    def __init__(self, body: bytes) -> None:
        self._body = body

    async def iter_chunked(self, size: int):
        for offset in range(0, len(self._body), size):
            yield self._body[offset : offset + size]


class _FakeSession:
    def __init__(self, response: _FakeResponse | Exception) -> None:
        self._response = response
        self.last_url: str | None = None
        self.last_kwargs: dict[str, object] | None = None

    def get(self, url: str, **kwargs):
        self.last_url = url
        self.last_kwargs = kwargs
        if isinstance(self._response, Exception):
            raise self._response

        return self._response


class TestOcrProcessHappyPaths:
    # ocr_process() dispatches OCR execution through dispatch_ocr_request(), the same
    # admission-gated entry point the REST surface uses. Patching it directly keeps
    # these tests fast and isolated without spawning a real worker process.
    @patch("src.api.mcp.mcp_server.dispatch_ocr_request")
    async def test_file_uri_resolves_within_jail(self, mock_dispatch, tmp_path: Path, monkeypatch):
        # Given
        monkeypatch.setattr(settings, "MCP_FILE_URI_ROOT", str(tmp_path))
        image_path = tmp_path / "scan.png"
        image_path.write_bytes(VALID_PNG_BYTES)
        mock_dispatch.return_value = OcrResponseFactory.with_single_line(filename="scan.png")

        # When
        result = await ocr_process(image_path.as_uri(), lang="en")

        # Then
        assert result["filename"] == "scan.png"
        assert result["language"] == "en"
        mock_dispatch.assert_called_once()
        passed = mock_dispatch.call_args.args
        assert passed[0] == VALID_PNG_BYTES
        assert passed[2] == "en"

    @patch("src.api.mcp.mcp_server.inject_trace_context")
    @patch("src.api.mcp.mcp_server.dispatch_ocr_request")
    async def test_trace_context_is_forwarded_to_worker(self, mock_dispatch, mock_inject, tmp_path: Path, monkeypatch):
        # Given — the carrier is captured from the span wrapping the executor call, so
        # the worker process can reattach its own span as that span's child
        monkeypatch.setattr(settings, "MCP_FILE_URI_ROOT", str(tmp_path))
        image_path = tmp_path / "scan.png"
        image_path.write_bytes(VALID_PNG_BYTES)
        mock_dispatch.return_value = OcrResponseFactory.with_single_line(filename="scan.png")
        mock_inject.return_value = {"traceparent": "00-fake-01"}

        # When
        await ocr_process(image_path.as_uri(), lang="en")

        # Then
        mock_inject.assert_called_once()
        assert mock_dispatch.call_args.args[5] == {"traceparent": "00-fake-01"}

    @patch("src.api.mcp.mcp_server._validate_host", new_callable=AsyncMock)
    @patch("src.api.mcp.mcp_server.dispatch_ocr_request")
    async def test_http_uri_uses_module_session(self, mock_dispatch, _validate_host_mock):
        # Given
        session = _FakeSession(_FakeResponse(status=200, body=VALID_PNG_BYTES))
        mock_dispatch.return_value = OcrResponseFactory.with_single_line(filename="remote.png")

        # When
        with patch.object(mcp_server, "_http_session", session):
            result = await ocr_process("http://host.docker.internal:9070/bucket/remote.png", lang="en")

        # Then
        assert session.last_url == "http://host.docker.internal:9070/bucket/remote.png"
        assert session.last_kwargs == {"allow_redirects": False}
        assert mock_dispatch.call_args.args[0] == VALID_PNG_BYTES
        assert result["filename"] == "remote.png"

    @patch("src.api.mcp.mcp_server._validate_host", new_callable=AsyncMock)
    @patch("src.api.mcp.mcp_server.dispatch_ocr_request")
    async def test_http_url_decodes_basename(self, mock_dispatch, _validate_host_mock):
        # Given
        session = _FakeSession(_FakeResponse(status=200, body=VALID_PNG_BYTES))
        mock_dispatch.return_value = OcrResponseFactory.with_single_line(filename="scan with space.png")

        # When
        with patch.object(mcp_server, "_http_session", session):
            await ocr_process(
                "http://host.docker.internal:9070/bucket/scan%20with%20space.png",
                lang="en",
            )

        # Then
        passed_filename = mock_dispatch.call_args.args[1]
        assert passed_filename == "scan with space.png"


class TestOcrProcessErrorCodes:
    async def test_unsafe_uri_error_code_in_message(self):
        # Given a URI with embedded credentials (triggers UnsafeUriError before any fetch)
        # When ocr_process raises, the re-raised message must contain the UNSAFE_URI code
        with pytest.raises(UnsafeUriError, match="UNSAFE_URI"):
            await ocr_process("http://user:pass@example.com/x.png", lang="en")

    async def test_unsupported_scheme_error_code_in_message(self):
        # Given a bare ftp:// URI (not http/https/file — triggers UnsafeUriError for scheme)
        with pytest.raises(UnsafeUriError, match="UNSAFE_URI"):
            await ocr_process("ftp://example.com/x.png", lang="en")

    @patch("src.api.mcp.mcp_server._validate_host", new_callable=AsyncMock)
    async def test_unsupported_file_type_error_code_in_message(self, _validate_host_mock):
        # Given a URL that returns non-image bytes (plain text), sniff_mime raises
        # UnsupportedFileTypeError; ocr_process re-raises with UNSUPPORTED_FILE_TYPE code
        session = _FakeSession(_FakeResponse(status=200, body=b"plain text data"))
        with (
            patch.object(mcp_server, "_http_session", session),
            pytest.raises(UnsupportedFileTypeError, match="UNSUPPORTED_FILE_TYPE"),
        ):
            await ocr_process("http://example.com/x.txt", lang="en")

    @patch("src.api.mcp.mcp_server._validate_host", new_callable=AsyncMock)
    async def test_file_too_large_error_code_in_message(self, _validate_host_mock, monkeypatch):
        # Given an oversized Content-Length header, FileSizeExceededError fires during
        # download; ocr_process re-raises with FILE_TOO_LARGE code
        monkeypatch.setattr(settings, "MAX_FILE_SIZE_MB", 1)
        oversize = 2 * 1024 * 1024
        session = _FakeSession(
            _FakeResponse(
                status=200,
                body=b"x",
                headers={"Content-Length": str(oversize)},
            )
        )
        with (
            patch.object(mcp_server, "_http_session", session),
            pytest.raises(FileSizeExceededError, match="FILE_TOO_LARGE"),
        ):
            await ocr_process("http://example.com/big.png", lang="en")

    @patch("src.api.mcp.mcp_server._validate_host", new_callable=AsyncMock)
    async def test_download_failed_error_code_in_message(self, _validate_host_mock):
        # Given a 404 response, DownloadFailedError fires; ocr_process re-raises
        # with DOWNLOAD_FAILED code
        session = _FakeSession(_FakeResponse(status=404, body=b""))
        with (
            patch.object(mcp_server, "_http_session", session),
            pytest.raises(DownloadFailedError, match="DOWNLOAD_FAILED"),
        ):
            await ocr_process("http://example.com/missing.png", lang="en")

    @patch("src.api.mcp.mcp_server.dispatch_ocr_request")
    async def test_ocr_failed_error_code_in_message(self, mock_dispatch, tmp_path: Path, monkeypatch):
        # Given — dispatch_ocr_request raised its own OcrProcessingError (an expired
        # budget, a worker that would not stop, a broken pool, or a genuine engine
        # failure); ocr_process re-raises it with the OCR_FAILED code
        monkeypatch.setattr(settings, "MCP_FILE_URI_ROOT", str(tmp_path))
        image_path = tmp_path / "scan.png"
        image_path.write_bytes(VALID_PNG_BYTES)
        mock_dispatch.side_effect = OcrProcessingError("worker did not stop")

        # Then
        with pytest.raises(OcrProcessingError, match="OCR_FAILED"):
            await ocr_process(image_path.as_uri(), lang="en")


class TestFetchFileRejections:
    async def test_unsupported_scheme(self):
        # Then
        with pytest.raises(UnsafeUriError, match="Unsupported URI scheme"):
            await _fetch_file("ftp://example.com/file.png")

    async def test_bare_path_is_rejected(self, tmp_path: Path):
        # Given a bare absolute path; urlparse gives empty scheme
        bare = str(tmp_path / "bare.png")

        # Then
        with pytest.raises(UnsafeUriError):
            await _fetch_file(bare)

    async def test_windows_path_is_rejected(self):
        # Then
        with pytest.raises(UnsafeUriError):
            await _fetch_file("C:\\Users\\foo.png")


class TestReadJailedFile:
    async def test_file_uri_disabled_when_root_unset(self, monkeypatch):
        # Given
        monkeypatch.setattr(settings, "MCP_FILE_URI_ROOT", None)

        # Then
        with pytest.raises(UnsafeUriError, match="MCP_FILE_URI_ROOT is unset"):
            await _read_jailed_file("/etc/passwd")

    async def test_traversal_outside_root_is_rejected(self, tmp_path: Path, monkeypatch):
        # Given
        jail = tmp_path / "jail"
        jail.mkdir()
        outside = tmp_path / "outside.png"
        outside.write_bytes(b"x")
        monkeypatch.setattr(settings, "MCP_FILE_URI_ROOT", str(jail))

        # Then
        with pytest.raises(UnsafeUriError, match="escapes MCP_FILE_URI_ROOT"):
            await _read_jailed_file("/" + str(outside).replace("\\", "/"))

    async def test_missing_file_inside_root(self, tmp_path: Path, monkeypatch):
        # Given a path inside the jail that does not exist on disk
        monkeypatch.setattr(settings, "MCP_FILE_URI_ROOT", str(tmp_path))
        ghost = tmp_path / "ghost.png"
        url_path = "/" + str(ghost).replace("\\", "/")

        # Then
        with pytest.raises(DownloadFailedError, match="File not found"):
            await _read_jailed_file(url_path)

    async def test_size_cap_enforced_after_read(self, tmp_path: Path, monkeypatch):
        # Given
        monkeypatch.setattr(settings, "MCP_FILE_URI_ROOT", str(tmp_path))
        monkeypatch.setattr(settings, "MAX_FILE_SIZE_MB", 1)
        big = tmp_path / "big.png"
        big.write_bytes(b"x" * (2 * 1024 * 1024))

        # Then
        with pytest.raises(FileSizeExceededError):
            await _read_jailed_file("/" + str(big).replace("\\", "/"))


class TestDownloadHttpRejections:
    async def test_credentials_in_uri_rejected(self):
        # Given
        parsed = urlparse("http://user:pass@host/x.png")

        # Then
        with pytest.raises(UnsafeUriError, match="Credentials in URI"):
            await _download_http("http://user:pass@host/x.png", parsed)

    async def test_missing_hostname_rejected(self):
        # Given
        parsed = urlparse("http:///x.png")

        # Then
        with pytest.raises(UnsafeUriError, match="no hostname"):
            await _download_http("http:///x.png", parsed)

    @patch("src.api.mcp.mcp_server._validate_host", new_callable=AsyncMock)
    async def test_session_uninitialised(self, _validate_host_mock):
        # Given
        parsed = urlparse("http://host.docker.internal/x.png")

        # Then
        with patch.object(mcp_server, "_http_session", None), pytest.raises(RuntimeError, match="not initialised"):
            await _download_http("http://host.docker.internal/x.png", parsed)

    @patch("src.api.mcp.mcp_server._validate_host", new_callable=AsyncMock)
    async def test_non_200_raises_download_failed(self, _validate_host_mock):
        # Given
        session = _FakeSession(_FakeResponse(status=404, body=b""))
        parsed = urlparse("http://host.docker.internal/missing.png")

        # Then
        with patch.object(mcp_server, "_http_session", session), pytest.raises(DownloadFailedError, match="HTTP 404"):
            await _download_http("http://host.docker.internal/missing.png", parsed)

    @patch("src.api.mcp.mcp_server._validate_host", new_callable=AsyncMock)
    async def test_content_length_over_cap(self, _validate_host_mock):
        # Given
        oversize_bytes = settings.MAX_FILE_SIZE_MB * 1024 * 1024 + 1
        session = _FakeSession(
            _FakeResponse(
                status=200,
                body=b"x",
                headers={"Content-Length": str(oversize_bytes)},
            )
        )
        parsed = urlparse("http://host.docker.internal/big.png")

        # Then
        with patch.object(mcp_server, "_http_session", session), pytest.raises(FileSizeExceededError):
            await _download_http("http://host.docker.internal/big.png", parsed)

    @patch("src.api.mcp.mcp_server._validate_host", new_callable=AsyncMock)
    async def test_streamed_body_over_cap(self, _validate_host_mock, monkeypatch):
        # Given
        monkeypatch.setattr(settings, "MAX_FILE_SIZE_MB", 1)
        session = _FakeSession(
            _FakeResponse(
                status=200,
                body=b"x" * (2 * 1024 * 1024),
            )
        )
        parsed = urlparse("http://host.docker.internal/big.png")

        # Then
        with patch.object(mcp_server, "_http_session", session), pytest.raises(FileSizeExceededError):
            await _download_http("http://host.docker.internal/big.png", parsed)

    @patch("src.api.mcp.mcp_server._validate_host", new_callable=AsyncMock)
    async def test_client_error_raises_download_failed(self, _validate_host_mock):
        # Given
        session = _FakeSession(aiohttp.ClientError("connection refused"))
        parsed = urlparse("http://host.docker.internal/x.png")

        # Then
        with (
            patch.object(mcp_server, "_http_session", session),
            pytest.raises(DownloadFailedError, match="HTTP fetch failed"),
        ):
            await _download_http("http://host.docker.internal/x.png", parsed)

    @patch("src.api.mcp.mcp_server._validate_host", new_callable=AsyncMock)
    async def test_http_path_without_basename_falls_back(self, _validate_host_mock):
        # Given
        session = _FakeSession(_FakeResponse(status=200, body=PNG_MAGIC_BYTES))
        parsed = urlparse("http://host.docker.internal/")

        # When
        with patch.object(mcp_server, "_http_session", session):
            content, filename = await _download_http("http://host.docker.internal/", parsed)

        # Then
        assert content == PNG_MAGIC_BYTES
        assert filename == "remote-file"


class TestValidateHost:
    async def test_allowlisted_host_skipped(self, monkeypatch):
        # Given
        monkeypatch.setattr(settings, "MCP_ALLOWED_HOSTS", ("host.docker.internal",))

        # When / Then — no raise
        await _validate_host("host.docker.internal")

    @patch("src.api.mcp.mcp_server.asyncio.get_running_loop")
    async def test_private_ip_rejected(self, mock_loop):
        # Given
        loop = mock_loop.return_value
        loop.getaddrinfo = AsyncMock(return_value=[(0, 0, 0, "", ("10.0.0.5", 0))])

        # Then
        with pytest.raises(UnsafeUriError, match="non-public"):
            await _validate_host("internal.example.com")

    @patch("src.api.mcp.mcp_server.asyncio.get_running_loop")
    async def test_public_ip_allowed(self, mock_loop):
        # Given
        loop = mock_loop.return_value
        loop.getaddrinfo = AsyncMock(return_value=[(0, 0, 0, "", ("93.184.216.34", 0))])

        # When / Then — no raise
        await _validate_host("example.com")

    @patch("src.api.mcp.mcp_server.asyncio.get_running_loop")
    async def test_dns_failure_rejected(self, mock_loop):
        # Given
        loop = mock_loop.return_value
        loop.getaddrinfo = AsyncMock(side_effect=socket_mod.gaierror("DNS down"))

        # Then
        with pytest.raises(UnsafeUriError, match="Cannot resolve"):
            await _validate_host("does-not-exist.invalid")


class TestPureHelpers:
    @pytest.mark.parametrize(
        "ip_str",
        [
            "127.0.0.1",
            "10.0.0.1",
            "192.168.1.1",
            "169.254.169.254",
            "0.0.0.0",  # noqa: S104
            "224.0.0.1",
            "::1",
            "240.0.0.1",
        ],
    )
    def test_is_blocked_true_for_private_and_special(self, ip_str: str):
        # Then
        assert _is_blocked(ipaddress.ip_address(ip_str)) is True

    def test_is_blocked_false_for_public(self):
        # Then
        assert _is_blocked(ipaddress.ip_address("8.8.8.8")) is False

    def test_is_within_true(self, tmp_path: Path):
        # Then
        assert _is_within(str(tmp_path / "x.png"), str(tmp_path)) is True

    def test_is_within_false_when_outside(self, tmp_path: Path):
        # Then
        assert _is_within(str(tmp_path / "elsewhere"), str(tmp_path / "jail")) is False

    def test_is_within_false_on_value_error(self):
        # Then
        assert _is_within("C:\\a", "D:\\b") is False

    def test_enforce_size_passes_within_cap(self):
        # When / Then
        _enforce_size(1)

    def test_enforce_size_raises_over_cap(self, monkeypatch):
        # Given
        monkeypatch.setattr(settings, "MAX_FILE_SIZE_MB", 1)

        # Then
        with pytest.raises(FileSizeExceededError):
            _enforce_size(2 * 1024 * 1024)


class TestMcpLifespan:
    async def test_lifespan_opens_and_closes_session(self):
        # Given
        with patch.object(mcp_server, "_http_session", None):
            # When
            async with mcp_lifespan(None):
                opened = mcp_server._http_session

            # Then
            assert opened is not None
            assert mcp_server._http_session is None

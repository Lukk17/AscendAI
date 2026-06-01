import asyncio
import ipaddress
import os
import socket
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from urllib.parse import ParseResult, unquote, urlparse
from urllib.request import url2pathname

import aiofiles
import aiohttp
from fastmcp import FastMCP

from src.api.exception_handlers import (
    DownloadFailedError,
    FileSizeExceededError,
    UnsafeUriError,
    UnsupportedFileTypeError,
)
from src.api.middleware.audit_log import emit_mcp_audit
from src.api.mime_sniffer import sniff_mime
from src.config.config import settings
from src.config.logging_config import get_logger
from src.observability.metrics import (
    MCP_DOWNLOAD_DURATION_SECONDS,
    OCR_DURATION_SECONDS,
    OCR_REQUESTS_TOTAL,
)
from src.observability.tracing import get_tracer
from src.service.ocr_service import ocr_service

logger = get_logger(__name__)
tracer = get_tracer()

_BYTES_PER_MB: int = 1024 * 1024
_DOWNLOAD_CHUNK_BYTES: int = 64 * 1024
_HTTP_OK: int = 200

_http_session: aiohttp.ClientSession | None = None


@asynccontextmanager
async def mcp_lifespan(_app: object) -> AsyncIterator[None]:
    global _http_session  # noqa: PLW0603  module-level session reassigned by FastMCP lifespan
    timeout = aiohttp.ClientTimeout(
        total=settings.MCP_DOWNLOAD_TIMEOUT_SECONDS,
        sock_connect=5,
        sock_read=10,
    )
    _http_session = aiohttp.ClientSession(timeout=timeout)
    logger.info("MCP HTTP session opened")

    try:
        yield
    finally:
        # Close the session opened above. The defensive None check was dropped because the
        # assignment runs before the try, so by the time `finally` executes the session is
        # guaranteed to exist.
        await _http_session.close()
        _http_session = None
        logger.info("MCP HTTP session closed")


mcp: FastMCP = FastMCP("PaddleOCR", lifespan=mcp_lifespan)


@mcp.tool()
async def ocr_process(file_uri: str, lang: str = "en") -> dict[str, object]:
    """
    Run OCR on a file referenced by URI.

    Args:
        file_uri: Source URI. Supported schemes:
            - file:// (only when MCP_FILE_URI_ROOT is configured; jailed to that root).
            - http://, https:// (subject to host allowlist and private-IP block).
        lang: Language code (e.g., 'en', 'pl').

    Returns:
        Serialised OcrJsonResponse as a dictionary.
    """
    OCR_REQUESTS_TOTAL.labels(surface="mcp", language=lang).inc()
    parsed = urlparse(file_uri)
    scheme = parsed.scheme.lower() or "(none)"
    host = parsed.hostname

    with tracer.start_as_current_span(
        "paddleocr.mcp.fetch",
        attributes={"scheme": scheme, "host": host or ""},
    ):
        file_bytes, filename = await _fetch_file(file_uri)

    sniff_mime(file_bytes)
    emit_mcp_audit("ocr_process", scheme, host, len(file_bytes), "ok")

    start = time.monotonic()
    with tracer.start_as_current_span("paddleocr.engine.predict", attributes={"language": lang}):
        result = await asyncio.wait_for(
            asyncio.to_thread(ocr_service.process_file, file_bytes, filename, lang),
            timeout=settings.OCR_REQUEST_TIMEOUT,
        )
    OCR_DURATION_SECONDS.labels(surface="mcp", language=lang).observe(time.monotonic() - start)

    return result.model_dump()


async def _fetch_file(file_uri: str) -> tuple[bytes, str]:
    parsed = urlparse(file_uri)
    scheme = parsed.scheme.lower()

    match scheme:
        case "file":
            return await _read_jailed_file(parsed.path)
        case "http" | "https":
            return await _download_http(file_uri, parsed)
        case _:
            raise UnsafeUriError(f"Unsupported URI scheme: {scheme!r}")


async def _read_jailed_file(url_path: str) -> tuple[bytes, str]:
    root = settings.MCP_FILE_URI_ROOT
    if not root:
        raise UnsafeUriError("file:// access is disabled (MCP_FILE_URI_ROOT is unset)")

    local_path = url2pathname(url_path)
    # realpath + isfile are pure-string / cheap stat operations; the actual file
    # read below is async via aiofiles. ASYNC240 is overly conservative here.
    resolved = os.path.realpath(local_path)  # noqa: ASYNC240
    resolved_root = os.path.realpath(root)  # noqa: ASYNC240

    if not _is_within(resolved, resolved_root):
        raise UnsafeUriError(f"Path escapes MCP_FILE_URI_ROOT: {url_path}")

    if not os.path.isfile(resolved):  # noqa: ASYNC240
        raise DownloadFailedError(f"File not found: {url_path}")

    async with aiofiles.open(resolved, "rb") as file_handle:
        file_bytes = await file_handle.read()

    _enforce_size(len(file_bytes))

    return file_bytes, os.path.basename(resolved)


async def _download_http(uri: str, parsed: ParseResult) -> tuple[bytes, str]:
    if parsed.username or parsed.password:
        raise UnsafeUriError("Credentials in URI are not permitted")

    host = parsed.hostname
    if host is None:
        raise UnsafeUriError("URI has no hostname")

    await _validate_host(host)

    session = _http_session
    if session is None:
        raise RuntimeError("MCP HTTP session is not initialised")

    start = time.monotonic()
    outcome = "ok"

    try:
        async with session.get(uri, allow_redirects=False) as response:
            if response.status != _HTTP_OK:
                outcome = "failed"
                raise DownloadFailedError(f"Upstream returned HTTP {response.status} for {host}")

            content_length = response.headers.get("Content-Length")
            if content_length is not None:
                _enforce_size(int(content_length))

            buffer = bytearray()
            async for chunk in response.content.iter_chunked(_DOWNLOAD_CHUNK_BYTES):
                buffer.extend(chunk)
                _enforce_size(len(buffer))

    except FileSizeExceededError:
        outcome = "size_exceeded"
        raise
    except aiohttp.ClientError as exc:
        outcome = "failed"
        raise DownloadFailedError(f"HTTP fetch failed: {exc}") from exc
    finally:
        MCP_DOWNLOAD_DURATION_SECONDS.labels(outcome=outcome).observe(time.monotonic() - start)

    filename = unquote(os.path.basename(parsed.path)) or "remote-file"

    return bytes(buffer), filename


async def _validate_host(host: str) -> None:
    if host in settings.MCP_ALLOWED_HOSTS:
        return

    loop = asyncio.get_running_loop()

    try:
        infos = await loop.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise UnsafeUriError(f"Cannot resolve host: {host}") from exc

    for info in infos:
        ip_str = info[4][0]
        ip = ipaddress.ip_address(ip_str)
        if _is_blocked(ip):
            raise UnsafeUriError(f"Refusing to fetch from non-public address: {host} -> {ip_str}")


def _is_blocked(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified


def _is_within(path: str, root: str) -> bool:
    try:
        common = os.path.commonpath([path, root])
    except ValueError:
        return False

    return common == root


def _enforce_size(byte_count: int) -> None:
    cap = settings.MAX_FILE_SIZE_MB * _BYTES_PER_MB
    if byte_count > cap:
        raise FileSizeExceededError(f"Source size {byte_count} bytes exceeds maximum {settings.MAX_FILE_SIZE_MB} MB")


__all__ = [
    "DownloadFailedError",
    "FileSizeExceededError",
    "UnsafeUriError",
    "UnsupportedFileTypeError",
    "mcp",
    "mcp_lifespan",
    "ocr_process",
]

import asyncio
import ipaddress
import logging
import os
import socket
import time
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from typing import Final
from urllib.parse import ParseResult, unquote, urlparse
from urllib.request import url2pathname

import aiofiles
import aiohttp
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

from src.api.exception_handlers import (
    ERROR_CODE_DOWNLOAD_FAILED,
    ERROR_CODE_FILE_TOO_LARGE,
    ERROR_CODE_JOB_NOT_FOUND,
    ERROR_CODE_QUEUE_FULL,
    ERROR_CODE_UNSAFE_URI,
    ERROR_CODE_UNSUPPORTED_FILE_TYPE,
    ERROR_CODE_UNSUPPORTED_LANGUAGE,
    DownloadFailedError,
    FileSizeExceededError,
    JobNotFoundError,
    QueueFullError,
    UnsafeUriError,
    UnsupportedFileTypeError,
    UnsupportedLanguageError,
    log_refusal,
)
from src.api.mcp.request_log_context import McpRequestLogContextMiddleware
from src.api.middleware.audit_log import emit_mcp_audit
from src.config.config import DEFAULT_QUALITY, QualityMode, settings
from src.config.logging_config import get_logger
from src.observability.metrics import (
    MCP_DOWNLOAD_DURATION_SECONDS,
    OCR_REQUESTS_TOTAL,
    request_language_label,
)
from src.observability.tracing import get_tracer
from src.service.job_service import ensure_language_supported, job_service

logger = get_logger(__name__)
tracer = get_tracer()

_BYTES_PER_MB: int = 1024 * 1024
_DOWNLOAD_CHUNK_BYTES: int = 64 * 1024
_HTTP_OK: int = 200
_SURFACE: str = "mcp"
_REFUSAL_CODES: Final[dict[type[Exception], str]] = {
    UnsafeUriError: ERROR_CODE_UNSAFE_URI,
    UnsupportedFileTypeError: ERROR_CODE_UNSUPPORTED_FILE_TYPE,
    FileSizeExceededError: ERROR_CODE_FILE_TOO_LARGE,
    DownloadFailedError: ERROR_CODE_DOWNLOAD_FAILED,
    QueueFullError: ERROR_CODE_QUEUE_FULL,
    JobNotFoundError: ERROR_CODE_JOB_NOT_FOUND,
    UnsupportedLanguageError: ERROR_CODE_UNSUPPORTED_LANGUAGE,
}
_FASTMCP_REFUSAL_LOG_LEVEL: Final[int] = logging.DEBUG

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


mcp: FastMCP = FastMCP("ascend-ocr", lifespan=mcp_lifespan, middleware=[McpRequestLogContextMiddleware()])


@contextmanager
def _mcp_error_codes() -> Iterator[None]:
    """Answer an expected refusal with the `CODE: detail` text MCP callers read.

    Raised as a ToolError so FastMCP logs its own line at debug rather than as an error with a
    traceback, which leaves the refusal as the one warning log_refusal writes.

    Raises:
        ToolError: for every refusal in _REFUSAL_CODES, chained to the service's own error.
    """
    try:
        yield
    except tuple(_REFUSAL_CODES) as exc:
        code = _REFUSAL_CODES[type(exc)]
        log_refusal(code, exc)
        raise ToolError(f"{code}: {exc}", log_level=_FASTMCP_REFUSAL_LOG_LEVEL) from exc


@mcp.tool()
async def ocr_submit(
    file_uri: str, lang: str = "en", quality: QualityMode = DEFAULT_QUALITY, straighten: bool = False
) -> dict[str, object]:
    """
    Submit a file referenced by URI to be read, and get an identifier back straight away.

    The document is not read during this call. Poll `ocr_job_status` with the identifier
    this returns, waiting `poll_after_seconds` between reads, and collect the Markdown
    from the object storage address the finished state carries.

    Args:
        file_uri: Source URI. Supported schemes:
            - file:// (only when MCP_FILE_URI_ROOT is configured; jailed to that root).
            - http://, https:// (subject to host allowlist and private-IP block).
        lang: Language code (e.g., 'en', 'pl'). A code outside the supported list is refused with
            UNSUPPORTED_LANGUAGE before the URI is fetched.
        quality: 'high' (default) renders at 300 dpi for small print and dense pages; 'normal'
            renders at 150 dpi and reads faster when the text is large.
        straighten: false (default) reads the page as it is. true also flattens the page before
            reading, meant for phone photos of bent, curled or crumpled paper and best with quality
            'high'. It harms clean scans and PDFs, so leave it off for them.

    Returns:
        Serialised JobSubmitResponse as a dictionary.
    """
    OCR_REQUESTS_TOTAL.labels(surface=_SURFACE, language=request_language_label(lang)).inc()
    parsed = urlparse(file_uri)
    scheme = parsed.scheme.lower() or "(none)"
    host = parsed.hostname

    with _mcp_error_codes():
        ensure_language_supported(lang)
        with tracer.start_as_current_span(
            "ascend-ocr.mcp.fetch",
            attributes={"scheme": scheme, "host": host or ""},
        ):
            file_bytes, filename = await _fetch_file(file_uri)

        emit_mcp_audit("ocr_submit", scheme, host, len(file_bytes), "ok")
        submitted = await job_service.submit(file_bytes, filename, lang, quality, "mcp", straighten=straighten)

    return submitted.model_dump()


@mcp.tool()
def ocr_job_status(job_id: str) -> dict[str, object]:
    """
    Read the state of submitted work.

    Args:
        job_id: The identifier `ocr_submit` returned.

    Returns:
        Serialised JobStatusResponse as a dictionary. While the work is waiting or
        running it carries `poll_after_seconds`. A terminal state carries no
        `poll_after_seconds` key at all, and a succeeded one carries the bucket, the key
        and a time-limited URL for the Markdown.
    """
    with _mcp_error_codes():
        return job_service.status(job_id).model_dump()


@mcp.tool()
def ocr_list_jobs() -> dict[str, object]:
    """
    List the work that is queued or running, in submission order.

    Returns:
        Serialised JobListResponse as a dictionary. Finished work is not listed.
    """
    return job_service.list_jobs().model_dump()


@mcp.tool()
async def ocr_cancel_job(job_id: str) -> dict[str, object]:
    """
    Stop work that has not finished, or forget work that has, along with its stored result.

    Args:
        job_id: The identifier `ocr_submit` returned.

    Returns:
        The identifier and the outcome, so a caller can tell the call was accepted.
    """
    with _mcp_error_codes():
        await job_service.delete(job_id)

    return {"job_id": job_id, "cancelled": True}


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


def _validate_jailed_path(url_path: str, root: str) -> tuple[str, str]:
    """Validate and resolve file path within the jail root (sync, runs in thread pool).

    Returns:
        Tuple of (resolved_path, basename) if valid.

    Raises:
        UnsafeUriError: if path escapes jail or scheme is invalid.
        DownloadFailedError: if file does not exist.
    """
    local_path = url2pathname(url_path)
    resolved = os.path.realpath(local_path)
    resolved_root = os.path.realpath(root)

    if not _is_within(resolved, resolved_root):
        raise UnsafeUriError(f"Path escapes MCP_FILE_URI_ROOT: {url_path}")

    if not os.path.isfile(resolved):
        raise DownloadFailedError(f"File not found: {url_path}")

    return resolved, os.path.basename(resolved)


async def _read_jailed_file(url_path: str) -> tuple[bytes, str]:
    root = settings.MCP_FILE_URI_ROOT
    if not root:
        raise UnsafeUriError("file:// access is disabled (MCP_FILE_URI_ROOT is unset)")

    resolved_path, basename = await asyncio.to_thread(_validate_jailed_path, url_path, root)

    async with aiofiles.open(resolved_path, "rb") as file_handle:
        file_bytes = await file_handle.read()

    _enforce_size(len(file_bytes))

    return file_bytes, basename


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
    "JobNotFoundError",
    "QueueFullError",
    "UnsafeUriError",
    "UnsupportedFileTypeError",
    "mcp",
    "mcp_lifespan",
    "ocr_cancel_job",
    "ocr_job_status",
    "ocr_list_jobs",
    "ocr_submit",
]

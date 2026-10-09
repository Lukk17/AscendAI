import asyncio
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import unquote, urlparse

import aiofiles
import aiohttp
from ascend_python_common.log_config import get_logger
from ascend_python_common.uri_guard import FetchTarget, HopAnswer, check_fetch_uri, follow_guarded_redirects
from ascend_python_common.uri_guard import UnsafeUriError as LibraryUnsafeUriError
from ascend_python_common.uri_guard_aiohttp import PinnedResolver, pinned_scope
from fastmcp import FastMCP

from src.api.exception_handlers import (
    DownloadFailedError,
    FileSizeExceededError,
    JobNotFoundError,
    QueueFullError,
    UnsafeUriError,
    UnsupportedFileTypeError,
)
from src.api.middleware.audit_log import emit_mcp_audit
from src.config.config import DEFAULT_QUALITY, QualityMode, settings
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

_http_session: aiohttp.ClientSession | None = None


@asynccontextmanager
async def mcp_lifespan(_app: object) -> AsyncIterator[None]:
    global _http_session  # noqa: PLW0603  module-level session reassigned by FastMCP lifespan
    timeout = aiohttp.ClientTimeout(
        total=settings.MCP_DOWNLOAD_TIMEOUT_SECONDS,
        sock_connect=5,
        sock_read=10,
    )
    connector = aiohttp.TCPConnector(resolver=PinnedResolver(), use_dns_cache=False)
    _http_session = aiohttp.ClientSession(timeout=timeout, connector=connector)
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


mcp: FastMCP = FastMCP(
    "ascend-ocr",
    lifespan=mcp_lifespan,
)


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
    await job_service.delete(job_id)

    return {"job_id": job_id, "cancelled": True}


async def _fetch_file(file_uri: str) -> tuple[bytes, str]:
    try:
        target = await check_fetch_uri(file_uri, settings.fetch_policy())
    except LibraryUnsafeUriError as exc:
        raise UnsafeUriError(str(exc)) from exc

    if target.file_path is not None:
        return await _read_target_file(target.file_path)

    return await _download_http(target)


async def _read_target_file(path: Path) -> tuple[bytes, str]:
    if not await asyncio.to_thread(path.is_file):
        raise DownloadFailedError(f"File not found: {path}")

    async with aiofiles.open(path, "rb") as file_handle:
        file_bytes = await file_handle.read()

    _enforce_size(len(file_bytes))

    return file_bytes, path.name


async def _download_http(target: FetchTarget) -> tuple[bytes, str]:
    session = _http_session
    if session is None:
        raise RuntimeError("MCP HTTP session is not initialised")

    start = time.monotonic()
    outcome = "ok"
    sent: list[aiohttp.ClientResponse] = []

    async def send_hop(hop: FetchTarget) -> HopAnswer[aiohttp.ClientResponse]:
        with pinned_scope(hop):
            hop_response = await session.get(hop.url, allow_redirects=False)
        sent.append(hop_response)
        return HopAnswer(
            status=hop_response.status,
            location=hop_response.headers.get("Location"),
            answer=hop_response,
        )

    try:
        final = await follow_guarded_redirects(target, settings.fetch_policy(), send_hop)
        for stale in sent[:-1]:
            stale.release()
        response = final.answer
        try:
            if response.status != _HTTP_OK:
                outcome = "failed"
                raise DownloadFailedError(f"Upstream returned HTTP {response.status} for {target.host}")

            content_length = response.headers.get("Content-Length")
            if content_length is not None:
                try:
                    declared = int(content_length)
                except ValueError as exc:
                    outcome = "failed"
                    raise DownloadFailedError(
                        f"Invalid Content-Length {content_length!r} for {target.host}"
                    ) from exc
                _enforce_size(declared)

            buffer = bytearray()
            async for chunk in response.content.iter_chunked(_DOWNLOAD_CHUNK_BYTES):
                buffer.extend(chunk)
                _enforce_size(len(buffer))
        finally:
            response.release()

    except FileSizeExceededError:
        outcome = "size_exceeded"
        raise
    except aiohttp.ClientError as exc:
        outcome = "failed"
        raise DownloadFailedError(f"HTTP fetch failed: {exc}") from exc
    finally:
        MCP_DOWNLOAD_DURATION_SECONDS.labels(outcome=outcome).observe(time.monotonic() - start)

    filename = unquote(Path(urlparse(target.url).path).name) or "remote-file"

    return bytes(buffer), filename


def _enforce_size(byte_count: int) -> None:
    cap = settings.MAX_FILE_SIZE_MB * _BYTES_PER_MB
    if byte_count > cap:
        raise FileSizeExceededError(
            f"Source size {byte_count} bytes exceeds maximum {settings.MAX_FILE_SIZE_MB} MB"
        )


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

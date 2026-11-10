"""Non-HTML routing to the platform services.

A PDF (by magic bytes or a ``.pdf`` suffix) goes to docling-serve
(``POST /v1/convert/file``, Markdown out). An image goes to the ascend-ocr job
API: ``POST /v1/ocr/jobs``, then ``GET /v1/ocr/jobs/{job_id}`` until the job
is final, then the result is read capped at ``DOCUMENT_MAX_BYTES``, and
``DELETE /v1/ocr/jobs/{job_id}`` runs in the background once the read ends in
any way. Audio goes to ascend-audio-scribe (``POST /api/v1/transcribe/local``
with ``stream=false``). Every routed file is fetched by ``stream_to_file`` of
``src/fetch/byte_fetch.py`` capped at ``DOCUMENT_MAX_BYTES``. An empty URL
setting turns its route off, and a routing failure returns a routing error,
never a failed read. A file refused for its size is the one routing error that
ends a direct read. Every route posts through the one ``shared_client``,
which ``close_document_router`` closes after the background deletes.
"""

import asyncio
import logging
import re
import time
from collections.abc import Coroutine
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urlsplit, urlunsplit

import httpx

from src.config.config import settings
from src.fetch.byte_fetch import DocumentTooLargeError, stream_to_file
from src.observability.safe_address import address_without_query
from src.reader.browser_guard import web_hunter_fetch_policy

logger = logging.getLogger(__name__)

ROUTE_PDF = "pdf"
ROUTE_IMAGE = "image"
ROUTE_AUDIO = "audio"

ROUTE_ERROR_FILE_TOO_LARGE = "file_too_large"

_PDF_SUFFIXES = frozenset({".pdf"})
_IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tiff"})
_AUDIO_SUFFIXES = frozenset({".mp3", ".wav", ".ogg", ".m4a", ".flac"})

DOCLING_CONVERT_PATH = "/v1/convert/file"
OCR_SUBMIT_PATH = "/v1/ocr/jobs"
AUDIO_TRANSCRIBE_PATH = "/api/v1/transcribe/local"

_TERMINAL_OCR_STATES = frozenset({"succeeded", "failed", "cancelled"})
_OCR_JOB_ID = re.compile(r"[A-Za-z0-9_-]{22}")
_USER_INFO_END = "@"
_PENDING_OCR_DELETES: set[asyncio.Task[None]] = set()
_HANDED_OVER_SPOOLS: set[Path] = set()


@dataclass(frozen=True, slots=True)
class RouteResult:
    """One routed read: content on success, a routing error otherwise."""

    route: str
    content: str | None
    error: str | None

    @property
    def ok(self) -> bool:
        return self.error is None

    @property
    def ends_read(self) -> bool:
        return self.error == ROUTE_ERROR_FILE_TOO_LARGE


def route_for_suffix(url: str) -> str | None:
    """Route guess from the URL path suffix, or None for a plain HTML path."""
    suffix = Path(urlparse(url).path).suffix.lower()
    if suffix in _PDF_SUFFIXES:
        return ROUTE_PDF
    if suffix in _IMAGE_SUFFIXES:
        return ROUTE_IMAGE
    if suffix in _AUDIO_SUFFIXES:
        return ROUTE_AUDIO

    return None


def sniff_route(path: Path) -> str | None:
    """Route guess from the downloaded magic bytes, the bytes decide."""
    try:
        with path.open("rb") as handle:
            head = handle.read(16)
    except OSError:
        return None
    if head.startswith(b"%PDF"):
        return ROUTE_PDF
    if head.startswith((b"\x89PNG", b"\xff\xd8\xff", b"GIF8")):
        return ROUTE_IMAGE
    if head.startswith((b"ID3", b"OggS")) or head[4:8] == b"ftyp":
        return ROUTE_AUDIO

    return None


class _SharedClientHolder:
    client: httpx.AsyncClient | None = None


def shared_client() -> httpx.AsyncClient:
    """The one HTTP client every route posts through."""
    if _SharedClientHolder.client is None:
        _SharedClientHolder.client = httpx.AsyncClient()

    return _SharedClientHolder.client


async def close_document_router() -> None:
    """Wait up to ``OCR_DELETE_DRAIN_SECONDS`` for the background OCR deletes, then close the client."""
    pending = tuple(_PENDING_OCR_DELETES)
    if pending:
        _, unfinished = await asyncio.wait(pending, timeout=settings.OCR_DELETE_DRAIN_SECONDS)
        if unfinished:
            logger.warning(
                "document_router: %s ocr job deletes still running at shutdown are cancelled",
                len(unfinished),
            )
            for task in unfinished:
                task.cancel()
            await asyncio.gather(*unfinished, return_exceptions=True)
    client = _SharedClientHolder.client
    _SharedClientHolder.client = None
    if client is not None:
        await client.aclose()


def _failure_text(exc: Exception) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        return f"{type(exc).__name__} status {exc.response.status_code}"

    return type(exc).__name__


def _route_base(route: str, setting_name: str, value: str) -> str | None:
    if not value.strip():
        logger.info("document_router: %s route is off (%s is empty)", route, setting_name)

        return None

    return value.rstrip("/")


async def _download(url: str) -> Path | None:
    try:
        async with asyncio.timeout(settings.DOCUMENT_FETCH_TIMEOUT_SECONDS):
            return await stream_to_file(url, settings.DOCUMENT_MAX_BYTES, policy=web_hunter_fetch_policy())
    except TimeoutError:
        logger.warning(
            "document_router: download of %s passed DOCUMENT_FETCH_TIMEOUT_SECONDS",
            address_without_query(url),
        )

        return None


def _spool_name(url: str) -> str:
    name = Path(urlparse(url).path).name

    return name or "document"


async def _convert_pdf(url: str, path: Path, client: httpx.AsyncClient) -> RouteResult:
    base = _route_base("pdf", "DOCLING_SERVE_URL", settings.DOCLING_SERVE_URL)
    if base is None:
        return RouteResult(ROUTE_PDF, None, "route_disabled")
    try:
        with path.open("rb") as handle:
            response = await client.post(
                f"{base}{DOCLING_CONVERT_PATH}",
                files={"files": (_spool_name(url), handle, "application/pdf")},
                data={"options": '{"to_formats": ["md"]}'},
                timeout=settings.OCR_ROUTE_TIMEOUT_SECONDS,
            )
        response.raise_for_status()
        payload: Any = response.json()
        markdown = payload["document"]["md_content"]
    except Exception as exc:
        logger.warning(
            "document_router: pdf conversion failed for %s: %s",
            address_without_query(url),
            _failure_text(exc),
        )

        return RouteResult(ROUTE_PDF, None, "conversion_failed")
    if not isinstance(markdown, str):
        return RouteResult(ROUTE_PDF, None, "conversion_failed")

    return RouteResult(ROUTE_PDF, markdown, None)


async def _poll_ocr_terminal(
    client: httpx.AsyncClient, base: str, job_id: str, deadline: float
) -> dict[str, Any] | None:
    """Poll one OCR job until a terminal state, honouring the poll hint."""
    while True:
        try:
            response = await client.get(
                f"{base}{OCR_SUBMIT_PATH}/{job_id}",
                timeout=settings.OCR_ROUTE_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            status: Any = response.json()
        except Exception as exc:
            logger.warning("document_router: ocr poll failed for job %s: %s", job_id, _failure_text(exc))

            return None
        if not isinstance(status, dict) or status.get("state") not in _TERMINAL_OCR_STATES:
            hint = status.get("poll_after_seconds") if isinstance(status, dict) else None
            wait = hint if isinstance(hint, (int, float)) and hint > 0 else 1.0
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            await asyncio.sleep(min(wait, remaining))
            continue

        return status


async def _submit_ocr_job(url: str, path: Path, client: httpx.AsyncClient, base: str) -> str | None:
    try:
        with path.open("rb") as handle:
            submitted = await client.post(
                f"{base}{OCR_SUBMIT_PATH}",
                files={"file": (_spool_name(url), handle, "application/octet-stream")},
                timeout=settings.OCR_ROUTE_TIMEOUT_SECONDS,
            )
        submitted.raise_for_status()
        job: Any = submitted.json()
        job_id = job["job_id"]
    except Exception as exc:
        logger.warning(
            "document_router: ocr submit failed for %s: %s", address_without_query(url), _failure_text(exc)
        )

        return None
    if not isinstance(job_id, str) or _OCR_JOB_ID.fullmatch(job_id) is None:
        logger.warning(
            "document_router: ocr submit for %s answered no valid job id", address_without_query(url)
        )

        return None

    return job_id


def _remove_handed_over_spool(spool: Path) -> None:
    _HANDED_OVER_SPOOLS.discard(spool)
    spool.unlink(missing_ok=True)


async def _delete_after_submit(
    submit: asyncio.Task[str | None], client: httpx.AsyncClient, base: str, spool: Path
) -> None:
    try:
        job_id = await submit
    finally:
        _remove_handed_over_spool(spool)
    if job_id is not None:
        await _delete_ocr_job(client, base, job_id)


async def _read_image(url: str, path: Path, client: httpx.AsyncClient) -> RouteResult:
    base = _route_base("image", "ASCEND_OCR_URL", settings.ASCEND_OCR_URL)
    if base is None:
        return RouteResult(ROUTE_IMAGE, None, "route_disabled")
    submit = asyncio.create_task(_submit_ocr_job(url, path, client, base))
    try:
        job_id = await asyncio.shield(submit)
    except asyncio.CancelledError:
        _HANDED_OVER_SPOOLS.add(path)
        _track_cleanup(_delete_after_submit(submit, client, base, path))
        raise
    if job_id is None:
        return RouteResult(ROUTE_IMAGE, None, "submit_failed")
    try:
        return await _read_ocr_result(client, base, job_id)
    finally:
        _start_ocr_delete(client, base, job_id)


def _origin(address: str) -> tuple[str, str, int | None] | None:
    try:
        parts = urlsplit(address)
        port = parts.port
    except ValueError:
        return None
    if not parts.scheme or not parts.hostname:
        return None

    return parts.scheme, parts.hostname, port


def _is_on_result_store(address: str) -> bool:
    expected = _origin(settings.OBJECT_STORE_S3_PUBLIC_ENDPOINT)

    return expected is not None and _origin(address) == expected


def _on_store_endpoint(signed_address: str) -> tuple[str, dict[str, str]]:
    """The same path and query on OBJECT_STORE_S3_ENDPOINT, and the Host header the signature covers."""
    signed = urlsplit(signed_address)
    endpoint = urlsplit(settings.OBJECT_STORE_S3_ENDPOINT)
    address = urlunsplit((endpoint.scheme, endpoint.netloc, signed.path, signed.query, ""))

    return address, {"Host": signed.netloc.rpartition(_USER_INFO_END)[2]}


async def _fetch_capped_text(client: httpx.AsyncClient, signed_address: str) -> str | None:
    address, headers = _on_store_endpoint(signed_address)
    async with client.stream(
        "GET",
        address,
        headers=headers,
        follow_redirects=False,
        timeout=settings.OCR_ROUTE_TIMEOUT_SECONDS,
    ) as response:
        response.raise_for_status()
        chunks: list[bytes] = []
        total = 0
        async for chunk in response.aiter_bytes():
            total += len(chunk)
            if total > settings.DOCUMENT_MAX_BYTES:
                return None
            chunks.append(chunk)

        return b"".join(chunks).decode(response.encoding or "utf-8", errors="replace")


async def _read_ocr_result(client: httpx.AsyncClient, base: str, job_id: str) -> RouteResult:
    status = await _poll_ocr_terminal(
        client, base, job_id, time.monotonic() + settings.OCR_ROUTE_TIMEOUT_SECONDS
    )
    if status is None:
        return RouteResult(ROUTE_IMAGE, None, "poll_failed")
    if status.get("state") != "succeeded":
        return RouteResult(ROUTE_IMAGE, None, f"job_{status.get('state')}")
    result = status.get("result")
    address = result.get("url") if isinstance(result, dict) else None
    if not isinstance(address, str):
        return RouteResult(ROUTE_IMAGE, None, "result_missing")
    if not _is_on_result_store(address):
        logger.warning(
            "document_router: ocr result address of job %s is not on OBJECT_STORE_S3_PUBLIC_ENDPOINT", job_id
        )

        return RouteResult(ROUTE_IMAGE, None, "result_failed")
    try:
        text = await _fetch_capped_text(client, address)
    except Exception as exc:
        logger.warning("document_router: ocr result fetch failed for job %s: %s", job_id, _failure_text(exc))

        return RouteResult(ROUTE_IMAGE, None, "result_failed")
    if text is None:
        logger.warning("document_router: ocr result of job %s passed DOCUMENT_MAX_BYTES", job_id)

        return RouteResult(ROUTE_IMAGE, None, "result_failed")

    return RouteResult(ROUTE_IMAGE, text, None)


async def _delete_ocr_job(client: httpx.AsyncClient, base: str, job_id: str) -> None:
    try:
        response = await client.delete(
            f"{base}{OCR_SUBMIT_PATH}/{job_id}",
            timeout=settings.OCR_ROUTE_TIMEOUT_SECONDS,
        )
    except Exception as exc:
        logger.warning("document_router: ocr job delete failed for job %s: %s", job_id, _failure_text(exc))

        return
    if response.is_success or response.status_code == httpx.codes.NOT_FOUND:
        return
    logger.warning(
        "document_router: ocr job delete failed for job %s: status %s", job_id, response.status_code
    )


def _track_cleanup(cleanup: Coroutine[Any, Any, None]) -> asyncio.Task[None]:
    task = asyncio.create_task(cleanup)
    _PENDING_OCR_DELETES.add(task)
    task.add_done_callback(_PENDING_OCR_DELETES.discard)

    return task


def _start_ocr_delete(client: httpx.AsyncClient, base: str, job_id: str) -> asyncio.Task[None]:
    """Start deleting one OCR job in a task that outlives the read."""
    return _track_cleanup(_delete_ocr_job(client, base, job_id))


async def _transcribe_audio(url: str, path: Path, client: httpx.AsyncClient) -> RouteResult:
    base = _route_base("audio", "AUDIO_SCRIBE_URL", settings.AUDIO_SCRIBE_URL)
    if base is None:
        return RouteResult(ROUTE_AUDIO, None, "route_disabled")
    try:
        with path.open("rb") as handle:
            response = await client.post(
                f"{base}{AUDIO_TRANSCRIBE_PATH}",
                files={"file": (_spool_name(url), handle, "audio/mpeg")},
                data={"stream": "false"},
                timeout=settings.OCR_ROUTE_TIMEOUT_SECONDS,
            )
        response.raise_for_status()
    except Exception as exc:
        logger.warning(
            "document_router: audio transcription failed for %s: %s",
            address_without_query(url),
            _failure_text(exc),
        )

        return RouteResult(ROUTE_AUDIO, None, "transcription_failed")

    return RouteResult(ROUTE_AUDIO, response.text, None)


_ROUTERS = {
    ROUTE_PDF: _convert_pdf,
    ROUTE_IMAGE: _read_image,
    ROUTE_AUDIO: _transcribe_audio,
}


async def route_document(url: str, client: httpx.AsyncClient | None = None) -> RouteResult | None:
    """Route one direct document read, or None when the URL is not routable."""
    guessed = route_for_suffix(url)
    if guessed is None:
        return None
    active = client if client is not None else shared_client()
    try:
        path = await _download(url)
    except DocumentTooLargeError:
        return RouteResult(guessed, None, ROUTE_ERROR_FILE_TOO_LARGE)
    if path is None:
        return RouteResult(guessed, None, "download_failed")
    try:
        route = sniff_route(path) or guessed
        return await _ROUTERS[route](url, path, active)
    finally:
        if path not in _HANDED_OVER_SPOOLS:
            path.unlink(missing_ok=True)

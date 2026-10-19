"""Non-HTML routing to the platform services (design D6).

A PDF (by magic bytes or a ``.pdf`` suffix) is converted by docling-serve at
``DOCLING_SERVE_URL``, endpoint ``/v1/convert/file`` asking for Markdown, an
image goes through the ascend-ocr job API (``POST /v1/ocr/jobs``, then
``GET /v1/ocr/jobs/{job_id}``), and audio is transcribed by
ascend-audio-scribe (``POST /api/v1/transcribe/local`` with
``stream=false``). Every routed file is fetched by the shared
``stream_to_file`` of ``src/fetch/byte_fetch.py`` capped at
``DOCUMENT_MAX_BYTES``. An empty URL setting turns that route off. A routing
failure returns a routing error, never a failed read.

No route opens an HTTP client of its own: the three clients share the one
module-level ``shared_client``.
"""

import asyncio
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
from ascend_python_common.uri_guard import FetchPolicy

from src.config.config import settings
from src.fetch.byte_fetch import stream_to_file

logger = logging.getLogger(__name__)

ROUTE_PDF = "pdf"
ROUTE_IMAGE = "image"
ROUTE_AUDIO = "audio"

_PDF_SUFFIXES = frozenset({".pdf"})
_IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tiff"})
_AUDIO_SUFFIXES = frozenset({".mp3", ".wav", ".ogg", ".m4a", ".flac"})

# docling-serve convert path, checked against the image pinned in compose.yaml
# (quay.io/docling-project/docling-serve:1.14.0) and recorded in design.md.
DOCLING_CONVERT_PATH = "/v1/convert/file"
OCR_SUBMIT_PATH = "/v1/ocr/jobs"
AUDIO_TRANSCRIBE_PATH = "/api/v1/transcribe/local"

_TERMINAL_OCR_STATES = frozenset({"succeeded", "failed", "cancelled"})


@dataclass(frozen=True, slots=True)
class RouteResult:
    """One routed read: content on success, a routing error otherwise."""

    route: str
    content: str | None
    error: str | None

    @property
    def ok(self) -> bool:
        return self.error is None


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


def _fetch_policy() -> FetchPolicy:
    return FetchPolicy(
        allowed_hosts=tuple(settings.ALLOWED_PRIVATE_HOSTS),
        file_root=None,
        max_redirect_hops=settings.FETCH_MAX_REDIRECT_HOPS,
    )


def _route_base(route: str, setting_name: str, value: str) -> str | None:
    if not value.strip():
        logger.info("document_router: %s route is off (%s is empty)", route, setting_name)

        return None

    return value.rstrip("/")


async def _download(url: str) -> Path | None:
    return await stream_to_file(url, settings.DOCUMENT_MAX_BYTES, policy=_fetch_policy())


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
        logger.warning("document_router: pdf conversion failed for %s: %s", url, exc)

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
            logger.warning("document_router: ocr poll failed for job %s: %s", job_id, exc)

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


async def _read_image(url: str, path: Path, client: httpx.AsyncClient) -> RouteResult:
    base = _route_base("image", "ASCEND_OCR_URL", settings.ASCEND_OCR_URL)
    if base is None:
        return RouteResult(ROUTE_IMAGE, None, "route_disabled")
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
        logger.warning("document_router: ocr submit failed for %s: %s", url, exc)

        return RouteResult(ROUTE_IMAGE, None, "submit_failed")
    if not isinstance(job_id, str):
        return RouteResult(ROUTE_IMAGE, None, "submit_failed")
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
    try:
        fetched = await client.get(address, timeout=settings.OCR_ROUTE_TIMEOUT_SECONDS)
        fetched.raise_for_status()
    except Exception as exc:
        logger.warning("document_router: ocr result fetch failed for job %s: %s", job_id, exc)

        return RouteResult(ROUTE_IMAGE, None, "result_failed")

    return RouteResult(ROUTE_IMAGE, fetched.text, None)


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
        logger.warning("document_router: audio transcription failed for %s: %s", url, exc)

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
    path = await _download(url)
    if path is None:
        return RouteResult(guessed, None, "download_failed")
    try:
        route = sniff_route(path) or guessed
        return await _ROUTERS[route](url, path, active)
    finally:
        path.unlink(missing_ok=True)

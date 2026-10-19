"""Tasks 4.1 and 4.2: non-HTML routing to docling-serve, ascend-ocr and audio-scribe."""

import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from unittest.mock import patch

import httpx
import pytest

from src.reader.document_router import (
    _SharedClientHolder,
    route_document,
    route_for_suffix,
    shared_client,
    sniff_route,
)

_PDF_MAGIC = b"%PDF-1.7 fake body"
_PNG_MAGIC = b"\x89PNG\r\n\x1a\x00fake body"


def _stub_client(handler: Any) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _write(path: Path, body: bytes) -> Path:
    target = path / "spool.bin"
    target.write_bytes(body)
    return target


def test_route_for_suffix() -> None:
    assert route_for_suffix("https://cdn.example.com/doc.PDF") == "pdf"
    assert route_for_suffix("https://cdn.example.com/i/photo.png") == "image"
    assert route_for_suffix("https://cdn.example.com/i/photo.JPG") == "image"
    assert route_for_suffix("https://cdn.example.com/a/clip.mp3") == "audio"
    assert route_for_suffix("https://example.com/article") is None


def test_sniff_route_reads_magic_bytes(tmp_path: Path) -> None:
    assert sniff_route(_write(tmp_path, _PDF_MAGIC)) == "pdf"
    assert sniff_route(_write(tmp_path, _PNG_MAGIC)) == "image"
    assert sniff_route(_write(tmp_path, b"ID3fake")) == "audio"
    assert sniff_route(_write(tmp_path, b"OggSfake")) == "audio"
    assert sniff_route(_write(tmp_path, b"xxxxftypfake")) == "audio"
    assert sniff_route(_write(tmp_path, b"plain text")) is None
    assert sniff_route(tmp_path / "absent.bin") is None


def test_shared_client_is_one_instance() -> None:
    # given
    _SharedClientHolder.client = None

    # when
    first = shared_client()

    # then
    assert shared_client() is first


@pytest.mark.asyncio
async def test_non_routable_url_is_none() -> None:
    assert await route_document("https://example.com/article", client=_stub_client(lambda r: None)) is None


@pytest.mark.asyncio
async def test_pdf_converted_by_docling(tmp_path: Path) -> None:
    # given
    seen: dict[str, Any] = {}

    async def handle(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        return httpx.Response(200, json={"document": {"md_content": "# Canary PDF text"}})

    path = _write(tmp_path, _PDF_MAGIC)

    # when
    with patch("src.reader.document_router._download", return_value=path):
        result = await route_document("https://cdn.example.com/doc.pdf", client=_stub_client(handle))

    # then
    assert result is not None
    assert result.ok
    assert result.content == "# Canary PDF text"
    assert result.route == "pdf"
    assert seen["path"] == "/v1/convert/file"
    assert not path.exists()


@pytest.mark.asyncio
async def test_magic_bytes_override_the_suffix(tmp_path: Path) -> None:
    # given
    seen: dict[str, Any] = {}

    async def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/ocr/jobs" and request.method == "POST":
            seen["submitted"] = True
            return httpx.Response(
                202, json={"job_id": "job1", "poll_after_seconds": 0.01, "state": "waiting"}
            )
        return httpx.Response(200, json={"state": "failed"})

    path = _write(tmp_path, _PNG_MAGIC)

    # when
    with patch("src.reader.document_router._download", return_value=path):
        result = await route_document("https://cdn.example.com/doc.pdf", client=_stub_client(handle))

    # then
    assert result is not None
    assert result.route == "image"
    assert seen.get("submitted") is True


@pytest.mark.asyncio
async def test_pdf_route_off_is_routing_error(tmp_path: Path) -> None:
    # given
    path = _write(tmp_path, _PDF_MAGIC)

    # when
    with (
        patch("src.reader.document_router._download", return_value=path),
        patch("src.reader.document_router.settings.DOCLING_SERVE_URL", "  "),
    ):
        result = await route_document("https://cdn.example.com/doc.pdf", client=_stub_client(lambda r: None))

    # then
    assert result is not None
    assert not result.ok
    assert result.error == "route_disabled"
    assert not path.exists()


@pytest.mark.asyncio
async def test_pdf_conversion_failure_is_routing_error(tmp_path: Path) -> None:
    # given
    async def handle(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "down"})

    # when
    with patch("src.reader.document_router._download", return_value=_write(tmp_path, _PDF_MAGIC)):
        result = await route_document("https://cdn.example.com/doc.pdf", client=_stub_client(handle))

    # then
    assert result is not None
    assert result.error == "conversion_failed"


@pytest.mark.asyncio
async def test_pdf_non_markdown_is_routing_error(tmp_path: Path) -> None:
    # given
    async def handle(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"document": {"md_content": 42}})

    # when
    with patch("src.reader.document_router._download", return_value=_write(tmp_path, _PDF_MAGIC)):
        result = await route_document("https://cdn.example.com/doc.pdf", client=_stub_client(handle))

    # then
    assert result is not None
    assert result.error == "conversion_failed"


@pytest.mark.asyncio
async def test_pdf_download_failure_is_routing_error() -> None:
    # when
    with patch("src.reader.document_router._download", return_value=None):
        result = await route_document("https://cdn.example.com/doc.pdf", client=_stub_client(lambda r: None))

    # then
    assert result is not None
    assert result.error == "download_failed"


@pytest.mark.asyncio
async def test_image_read_through_job_api(tmp_path: Path) -> None:
    # given
    seen: dict[str, Any] = {"posts": 0}

    async def handle(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path == "/v1/ocr/jobs":
            seen["posts"] += 1
            return httpx.Response(
                202,
                json={"job_id": "job1", "poll_after_seconds": 0.01, "state": "waiting"},
            )
        if request.method == "GET" and request.url.path == "/v1/ocr/jobs/job1":
            if seen["posts"] == 1:
                seen["posts"] += 1
                return httpx.Response(200, json={"state": "running", "poll_after_seconds": 0.01})
            return httpx.Response(
                200,
                json={
                    "state": "succeeded",
                    "result": {"url": "https://ocr.example.com/r/job1.md"},
                },
            )
        if str(request.url) == "https://ocr.example.com/r/job1.md":
            return httpx.Response(200, text="# OCR Markdown")
        raise AssertionError(f"unexpected {request.method} {request.url}")

    # when
    with patch("src.reader.document_router._download", return_value=_write(tmp_path, _PNG_MAGIC)):
        result = await route_document("https://cdn.example.com/i.png", client=_stub_client(handle))

    # then
    assert result is not None
    assert result.ok
    assert result.content == "# OCR Markdown"
    assert result.route == "image"


@pytest.mark.asyncio
async def test_image_route_uses_poll_hint_and_timeout(tmp_path: Path) -> None:
    # given
    async def handle(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(
                202, json={"job_id": "job1", "poll_after_seconds": 5, "state": "waiting"}
            )
        return httpx.Response(200, json={"state": "running", "poll_after_seconds": 5})

    # when
    with (
        patch("src.reader.document_router._download", return_value=_write(tmp_path, _PNG_MAGIC)),
        patch("src.reader.document_router.settings.OCR_ROUTE_TIMEOUT_SECONDS", 0.05),
    ):
        result = await route_document("https://cdn.example.com/i.png", client=_stub_client(handle))

    # then
    assert result is not None
    assert result.error == "poll_failed"


@pytest.mark.asyncio
async def test_image_job_failure_is_routing_error(tmp_path: Path) -> None:
    # given
    async def handle(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(
                202, json={"job_id": "job1", "poll_after_seconds": 0.01, "state": "waiting"}
            )
        return httpx.Response(200, json={"state": "failed"})

    # when
    with patch("src.reader.document_router._download", return_value=_write(tmp_path, _PNG_MAGIC)):
        result = await route_document("https://cdn.example.com/i.png", client=_stub_client(handle))

    # then
    assert result is not None
    assert result.error == "job_failed"


@pytest.mark.asyncio
async def test_image_missing_result_is_routing_error(tmp_path: Path) -> None:
    # given
    async def handle(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(
                202, json={"job_id": "job1", "poll_after_seconds": 0.01, "state": "waiting"}
            )
        return httpx.Response(200, json={"state": "succeeded", "result": None})

    # when
    with patch("src.reader.document_router._download", return_value=_write(tmp_path, _PNG_MAGIC)):
        result = await route_document("https://cdn.example.com/i.png", client=_stub_client(handle))

    # then
    assert result is not None
    assert result.error == "result_missing"


@pytest.mark.asyncio
async def test_image_poll_error_is_routing_error(tmp_path: Path) -> None:
    # given
    async def handle(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(
                202, json={"job_id": "job1", "poll_after_seconds": 0.01, "state": "waiting"}
            )
        return httpx.Response(500, json={"error": "down"})

    # when
    with patch("src.reader.document_router._download", return_value=_write(tmp_path, _PNG_MAGIC)):
        result = await route_document("https://cdn.example.com/i.png", client=_stub_client(handle))

    # then
    assert result is not None
    assert result.error == "poll_failed"


@pytest.mark.asyncio
async def test_image_result_fetch_error_is_routing_error(tmp_path: Path) -> None:
    # given
    async def handle(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(
                202, json={"job_id": "job1", "poll_after_seconds": 0.01, "state": "waiting"}
            )
        if request.url.path == "/v1/ocr/jobs/job1":
            return httpx.Response(
                200,
                json={"state": "succeeded", "result": {"url": "https://ocr.example.com/r/job1.md"}},
            )
        return httpx.Response(404, json={"error": "gone"})

    # when
    with patch("src.reader.document_router._download", return_value=_write(tmp_path, _PNG_MAGIC)):
        result = await route_document("https://cdn.example.com/i.png", client=_stub_client(handle))

    # then
    assert result is not None
    assert result.error == "result_failed"


@pytest.mark.asyncio
async def test_image_submit_failure_is_routing_error(tmp_path: Path) -> None:
    # given
    async def handle(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"error": "busy"})

    # when
    with patch("src.reader.document_router._download", return_value=_write(tmp_path, _PNG_MAGIC)):
        result = await route_document("https://cdn.example.com/i.png", client=_stub_client(handle))

    # then
    assert result is not None
    assert result.error == "submit_failed"


@pytest.mark.asyncio
async def test_image_submit_without_job_id_is_routing_error(tmp_path: Path) -> None:
    # given
    async def handle(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(202, json={"state": "waiting"})

    # when
    with patch("src.reader.document_router._download", return_value=_write(tmp_path, _PNG_MAGIC)):
        result = await route_document("https://cdn.example.com/i.png", client=_stub_client(handle))

    # then
    assert result is not None
    assert result.error == "submit_failed"


@pytest.mark.asyncio
async def test_image_submit_with_non_string_job_id_is_routing_error(tmp_path: Path) -> None:
    # given
    async def handle(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(202, json={"job_id": 42, "state": "waiting"})

    # when
    with patch("src.reader.document_router._download", return_value=_write(tmp_path, _PNG_MAGIC)):
        result = await route_document("https://cdn.example.com/i.png", client=_stub_client(handle))

    # then
    assert result is not None
    assert result.error == "submit_failed"


@pytest.mark.asyncio
async def test_image_route_off_is_routing_error(tmp_path: Path) -> None:
    # when
    with (
        patch("src.reader.document_router._download", return_value=_write(tmp_path, _PNG_MAGIC)),
        patch("src.reader.document_router.settings.ASCEND_OCR_URL", ""),
    ):
        result = await route_document("https://cdn.example.com/i.png", client=_stub_client(lambda r: None))

    # then
    assert result is not None
    assert result.error == "route_disabled"


@pytest.mark.asyncio
async def test_audio_transcribed(tmp_path: Path) -> None:
    # given
    seen: dict[str, Any] = {}

    async def handle(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        return httpx.Response(200, text="# invented canary transcript")

    # when
    with patch(
        "src.reader.document_router._download", return_value=_write(tmp_path, b"ID3fakeaudio")
    ):
        result = await route_document("https://cdn.example.com/a.mp3", client=_stub_client(handle))

    # then
    assert result is not None
    assert result.ok
    assert result.content == "# invented canary transcript"
    assert seen["path"] == "/api/v1/transcribe/local"


@pytest.mark.asyncio
async def test_audio_route_off_and_failure(tmp_path: Path) -> None:
    # when
    with (
        patch("src.reader.document_router._download", return_value=_write(tmp_path, b"ID3x")),
        patch("src.reader.document_router.settings.AUDIO_SCRIBE_URL", ""),
    ):
        off = await route_document("https://cdn.example.com/a.mp3", client=_stub_client(lambda r: None))

    async def failing(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "down"})

    with patch("src.reader.document_router._download", return_value=_write(tmp_path, b"ID3x")):
        failed = await route_document("https://cdn.example.com/a.mp3", client=_stub_client(failing))

    # then
    assert off is not None
    assert off.error == "route_disabled"
    assert failed is not None
    assert failed.error == "transcription_failed"


@pytest.mark.asyncio
async def test_default_client_comes_from_the_shared_singleton(tmp_path: Path) -> None:
    # given
    seen: dict[str, Any] = {}

    async def handle(_request: httpx.Request) -> httpx.Response:
        seen["hit"] = True
        return httpx.Response(200, json={"document": {"md_content": "# Hi"}})

    stub = _stub_client(handle)
    _SharedClientHolder.client = stub

    # when
    try:
        with patch("src.reader.document_router._download", return_value=_write(tmp_path, _PDF_MAGIC)):
            result = await route_document("https://cdn.example.com/doc.pdf")
    finally:
        _SharedClientHolder.client = None

    # then
    assert result is not None
    assert result.ok
    assert seen.get("hit") is True


class _OversizedHandler(BaseHTTPRequestHandler):
    def log_message(self, *_args: object) -> None:
        return

    def do_GET(self) -> None:
        if self.path == "/big.pdf":
            self.send_response(200)
            self.send_header("Content-Type", "application/pdf")
            self.send_header("Content-Length", str(52428801))
            self.end_headers()
        else:
            self.send_response(404)
            self.end_headers()


@pytest.fixture
def oversized_server() -> Iterator[str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _OversizedHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


@pytest.mark.asyncio
async def test_oversized_pdf_is_not_sent(oversized_server: str) -> None:
    # given
    async def handle(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("no service may be contacted for an oversized file")

    # when
    with (
        patch("src.reader.document_router.settings.ALLOWED_PRIVATE_HOSTS", ("127.0.0.1",)),
        patch("src.reader.document_router.settings.DOCUMENT_MAX_BYTES", 52428800),
    ):
        result = await route_document(f"{oversized_server}/big.pdf", client=_stub_client(handle))

    # then
    assert result is not None
    assert result.error == "download_failed"


@pytest.mark.asyncio
async def test_private_address_is_refused_without_a_request() -> None:
    # given
    posts = 0

    async def handle(_request: httpx.Request) -> httpx.Response:
        nonlocal posts
        posts += 1
        raise AssertionError("no service may be contacted for a refused address")

    # when
    result = await route_document("http://10.255.255.1/secret.pdf", client=_stub_client(handle))

    # then
    assert result is not None
    assert result.error == "download_failed"
    assert posts == 0

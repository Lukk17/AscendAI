"""Tasks 4.1 and 4.2: non-HTML routing to docling-serve, ascend-ocr and audio-scribe."""

import asyncio
import logging
import threading
from collections.abc import Awaitable, Callable, Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from unittest.mock import patch

import httpx
import pytest

from src.reader.document_router import (
    _HANDED_OVER_SPOOLS,
    _PENDING_OCR_DELETES,
    _SharedClientHolder,
    close_document_router,
    route_document,
    route_for_suffix,
    shared_client,
    sniff_route,
)

_PDF_MAGIC = b"%PDF-1.7 fake body"
_PNG_MAGIC = b"\x89PNG\r\n\x1a\x00fake body"
_JOB_ID = "AbCdEfGhIjKlMnOpQrSt_-"
_RESULT_URL = "https://store.example.com/ocr-results/result.md"
_RESULT_ENDPOINT = "https://store.example.com"
_SIGNED_QUERY = "?X-Amz-Credential=AKIDEXAMPLE%2F20261108&X-Amz-Signature=deadbeefsignature"


@pytest.fixture(autouse=True)
def _result_store_endpoint() -> Iterator[None]:
    with (
        patch("src.reader.document_router.settings.OBJECT_STORE_S3_PUBLIC_ENDPOINT", _RESULT_ENDPOINT),
        patch("src.reader.document_router.settings.OBJECT_STORE_S3_ENDPOINT", _RESULT_ENDPOINT),
    ):
        yield


def _stub_client(handler: Any) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def _settle_ocr_deletes() -> None:
    await asyncio.gather(*tuple(_PENDING_OCR_DELETES))
    await asyncio.sleep(0)


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
                202, json={"job_id": _JOB_ID, "poll_after_seconds": 0.01, "state": "waiting"}
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


async def test_a_download_past_its_deadline_is_the_download_failed_routing_error() -> None:
    # given
    async def never_finishes(*_args: object, **_kwargs: object) -> Path:
        await asyncio.Event().wait()

        return Path("never")

    # when
    with (
        patch("src.reader.document_router.stream_to_file", new=never_finishes),
        patch("src.reader.document_router.settings.DOCUMENT_FETCH_TIMEOUT_SECONDS", 0.05),
    ):
        result = await asyncio.wait_for(
            route_document("https://cdn.example.com/doc.pdf", client=_stub_client(lambda r: None)), timeout=5
        )

    # then
    assert result is not None
    assert result.error == "download_failed"


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
                json={"job_id": _JOB_ID, "poll_after_seconds": 0.01, "state": "waiting"},
            )
        if request.method == "GET" and request.url.path == f"/v1/ocr/jobs/{_JOB_ID}":
            if seen["posts"] == 1:
                seen["posts"] += 1
                return httpx.Response(200, json={"state": "running", "poll_after_seconds": 0.01})
            return httpx.Response(
                200,
                json={
                    "state": "succeeded",
                    "result": {"url": "https://store.example.com/r/job1.md"},
                },
            )
        if str(request.url) == "https://store.example.com/r/job1.md":
            seen["result_fetched_before_delete"] = "deleted" not in seen
            return httpx.Response(200, text="# OCR Markdown")
        if request.method == "DELETE" and request.url.path == f"/v1/ocr/jobs/{_JOB_ID}":
            seen["deleted"] = True
            return httpx.Response(204)
        raise AssertionError(f"unexpected {request.method} {request.url}")

    # when
    with patch("src.reader.document_router._download", return_value=_write(tmp_path, _PNG_MAGIC)):
        result = await route_document("https://cdn.example.com/i.png", client=_stub_client(handle))

    await _settle_ocr_deletes()

    # then
    assert result is not None
    assert result.ok
    assert result.content == "# OCR Markdown"
    assert result.route == "image"
    assert seen.get("deleted") is True
    assert not _PENDING_OCR_DELETES
    assert seen.get("result_fetched_before_delete") is True


@pytest.mark.asyncio
async def test_image_route_uses_poll_hint_and_timeout(tmp_path: Path) -> None:
    # given
    async def handle(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(202, json={"job_id": _JOB_ID, "poll_after_seconds": 5, "state": "waiting"})
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
                202, json={"job_id": _JOB_ID, "poll_after_seconds": 0.01, "state": "waiting"}
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
                202, json={"job_id": _JOB_ID, "poll_after_seconds": 0.01, "state": "waiting"}
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
                202, json={"job_id": _JOB_ID, "poll_after_seconds": 0.01, "state": "waiting"}
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
                202, json={"job_id": _JOB_ID, "poll_after_seconds": 0.01, "state": "waiting"}
            )
        if request.url.path == f"/v1/ocr/jobs/{_JOB_ID}":
            return httpx.Response(
                200,
                json={"state": "succeeded", "result": {"url": "https://store.example.com/r/job1.md"}},
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


class _OcrJobStub:
    """An ascend-ocr job API that records every DELETE of its job."""

    def __init__(self, final_state: str | None, delete_status: int = 204) -> None:
        self.final_state = final_state
        self.delete_status = delete_status
        self.deletes: list[str] = []
        self.polled = asyncio.Event()

    async def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(
                202, json={"job_id": _JOB_ID, "poll_after_seconds": 0.01, "state": "waiting"}
            )
        if request.method == "DELETE":
            self.deletes.append(request.url.path)
            return httpx.Response(self.delete_status)
        self.polled.set()
        if self.final_state is None:
            return httpx.Response(200, json={"state": "running", "poll_after_seconds": 5})
        return httpx.Response(200, json={"state": self.final_state})


@pytest.mark.asyncio
@pytest.mark.parametrize("final_state", ["failed", "cancelled"])
async def test_image_job_that_ended_unsuccessfully_is_deleted(tmp_path: Path, final_state: str) -> None:
    # given
    stub = _OcrJobStub(final_state)

    # when
    with patch("src.reader.document_router._download", return_value=_write(tmp_path, _PNG_MAGIC)):
        result = await route_document("https://cdn.example.com/i.png", client=_stub_client(stub))
    await _settle_ocr_deletes()

    # then
    assert result is not None
    assert result.error == f"job_{final_state}"
    assert stub.deletes == [f"/v1/ocr/jobs/{_JOB_ID}"]
    assert not _PENDING_OCR_DELETES


@pytest.mark.asyncio
async def test_image_job_is_deleted_when_the_poll_times_out(tmp_path: Path) -> None:
    # given
    stub = _OcrJobStub(None)

    # when
    with (
        patch("src.reader.document_router._download", return_value=_write(tmp_path, _PNG_MAGIC)),
        patch("src.reader.document_router.settings.OCR_ROUTE_TIMEOUT_SECONDS", 0.05),
    ):
        result = await route_document("https://cdn.example.com/i.png", client=_stub_client(stub))
    await _settle_ocr_deletes()

    # then
    assert result is not None
    assert result.error == "poll_failed"
    assert stub.deletes == [f"/v1/ocr/jobs/{_JOB_ID}"]
    assert not _PENDING_OCR_DELETES


class _BlockingDeleteOcrStub:
    """An ascend-ocr job API whose DELETE of its job waits until the test releases it."""

    def __init__(self, final_state: str | None) -> None:
        self.final_state = final_state
        self.polled = asyncio.Event()
        self.delete_started = asyncio.Event()
        self.release_delete = asyncio.Event()
        self.deleted = asyncio.Event()

    async def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(
                202, json={"job_id": _JOB_ID, "poll_after_seconds": 0.01, "state": "waiting"}
            )
        if request.method == "DELETE":
            self.delete_started.set()
            await self.release_delete.wait()
            self.deleted.set()
            return httpx.Response(204)
        if str(request.url) == _RESULT_URL:
            return httpx.Response(200, text="# OCR Markdown")
        self.polled.set()
        if self.final_state is None:
            return httpx.Response(200, json={"state": "running", "poll_after_seconds": 5})
        if self.final_state == "succeeded":
            return httpx.Response(200, json={"state": "succeeded", "result": {"url": _RESULT_URL}})
        return httpx.Response(200, json={"state": self.final_state})


@pytest.mark.asyncio
async def test_cancelled_read_ends_at_once_and_the_job_is_deleted_in_the_background(tmp_path: Path) -> None:
    # given
    stub = _BlockingDeleteOcrStub(None)

    with patch("src.reader.document_router._download", return_value=_write(tmp_path, _PNG_MAGIC)):
        read = asyncio.create_task(route_document("https://cdn.example.com/i.png", client=_stub_client(stub)))
        await asyncio.wait_for(stub.polled.wait(), timeout=5)

        # when
        read.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(read, timeout=1)
        stub.release_delete.set()

    # then
    await asyncio.wait_for(stub.deleted.wait(), timeout=5)
    await _settle_ocr_deletes()
    assert not _PENDING_OCR_DELETES


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("final_state", "content", "error"),
    [("succeeded", "# OCR Markdown", None), ("failed", None, "job_failed")],
)
async def test_read_answers_without_waiting_for_the_job_delete(
    tmp_path: Path, final_state: str, content: str | None, error: str | None
) -> None:
    # given
    stub = _BlockingDeleteOcrStub(final_state)

    # when
    with patch("src.reader.document_router._download", return_value=_write(tmp_path, _PNG_MAGIC)):
        result = await asyncio.wait_for(
            route_document("https://cdn.example.com/i.png", client=_stub_client(stub)), timeout=1
        )

    # then
    assert result is not None
    assert result.content == content
    assert result.error == error
    await asyncio.wait_for(stub.delete_started.wait(), timeout=5)
    assert not stub.deleted.is_set()
    stub.release_delete.set()
    await asyncio.wait_for(stub.deleted.wait(), timeout=5)
    await _settle_ocr_deletes()
    assert not _PENDING_OCR_DELETES


@pytest.mark.asyncio
async def test_unexpected_error_reaches_the_caller_without_waiting_for_the_job_delete(tmp_path: Path) -> None:
    # given
    stub = _BlockingDeleteOcrStub("succeeded")

    # when
    with (
        patch("src.reader.document_router._download", return_value=_write(tmp_path, _PNG_MAGIC)),
        patch("src.reader.document_router._read_ocr_result", side_effect=RuntimeError("unexpected")),
        pytest.raises(RuntimeError, match="unexpected"),
    ):
        await asyncio.wait_for(
            route_document("https://cdn.example.com/i.png", client=_stub_client(stub)), timeout=1
        )

    # then
    await asyncio.wait_for(stub.delete_started.wait(), timeout=5)
    assert not stub.deleted.is_set()
    stub.release_delete.set()
    await asyncio.wait_for(stub.deleted.wait(), timeout=5)
    await _settle_ocr_deletes()
    assert not _PENDING_OCR_DELETES


@pytest.mark.asyncio
async def test_unexpected_error_reaches_the_caller_and_the_job_is_deleted(tmp_path: Path) -> None:
    # given
    stub = _OcrJobStub("succeeded")

    # when
    with (
        patch("src.reader.document_router._download", return_value=_write(tmp_path, _PNG_MAGIC)),
        patch("src.reader.document_router._read_ocr_result", side_effect=RuntimeError("unexpected")),
        pytest.raises(RuntimeError, match="unexpected"),
    ):
        await route_document("https://cdn.example.com/i.png", client=_stub_client(stub))
    await _settle_ocr_deletes()

    # then
    assert stub.deletes == [f"/v1/ocr/jobs/{_JOB_ID}"]
    assert not _PENDING_OCR_DELETES


@pytest.mark.asyncio
async def test_image_job_already_gone_is_not_a_warning(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    # given
    stub = _OcrJobStub("failed", delete_status=404)

    # when
    with (
        caplog.at_level(logging.WARNING, logger="src.reader.document_router"),
        patch("src.reader.document_router._download", return_value=_write(tmp_path, _PNG_MAGIC)),
    ):
        result = await route_document("https://cdn.example.com/i.png", client=_stub_client(stub))
        await _settle_ocr_deletes()

    # then
    assert result is not None
    assert result.error == "job_failed"
    assert stub.deletes == [f"/v1/ocr/jobs/{_JOB_ID}"]
    assert not _PENDING_OCR_DELETES
    assert not [record for record in caplog.records if "delete" in record.getMessage()]


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["status", "exception"])
async def test_image_job_delete_failure_is_a_warning_and_keeps_the_read(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, failure: str
) -> None:
    # given
    async def handle(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(
                202, json={"job_id": _JOB_ID, "poll_after_seconds": 0.01, "state": "waiting"}
            )
        if request.method == "DELETE":
            if failure == "exception":
                raise httpx.ConnectError("ocr down")
            return httpx.Response(500, json={"error": "down"})
        if request.url.path == f"/v1/ocr/jobs/{_JOB_ID}":
            return httpx.Response(
                200, json={"state": "succeeded", "result": {"url": "https://store.example.com/r/job1.md"}}
            )
        return httpx.Response(200, text="# OCR Markdown")

    # when
    with (
        caplog.at_level(logging.WARNING, logger="src.reader.document_router"),
        patch("src.reader.document_router._download", return_value=_write(tmp_path, _PNG_MAGIC)),
    ):
        result = await route_document("https://cdn.example.com/i.png", client=_stub_client(handle))
        await _settle_ocr_deletes()

    # then
    assert result is not None
    assert result.ok
    assert result.content == "# OCR Markdown"
    assert not _PENDING_OCR_DELETES
    warnings = [record.getMessage() for record in caplog.records if record.levelno == logging.WARNING]
    assert any(f"ocr job delete failed for job {_JOB_ID}" in message for message in warnings)


def _warning_text(caplog: pytest.LogCaptureFixture) -> str:
    return "\n".join(record.getMessage() for record in caplog.records if record.levelno == logging.WARNING)


class _BlockingSubmitOcrStub:
    """An ascend-ocr job API whose submit waits until the test releases it."""

    def __init__(self, submit_status: int = 202) -> None:
        self.submit_status = submit_status
        self.submit_started = asyncio.Event()
        self.release_submit = asyncio.Event()
        self.deletes: list[str] = []

    async def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            self.submit_started.set()
            await self.release_submit.wait()
            if self.submit_status != httpx.codes.ACCEPTED:
                return httpx.Response(self.submit_status)
            return httpx.Response(
                202, json={"job_id": _JOB_ID, "poll_after_seconds": 0.01, "state": "waiting"}
            )
        if request.method == "DELETE":
            self.deletes.append(request.url.path)
            return httpx.Response(204)
        raise AssertionError(f"unexpected {request.method} {request.url}")


async def _cancel_during_the_submit(tmp_path: Path, stub: _BlockingSubmitOcrStub) -> None:
    with patch("src.reader.document_router._download", return_value=_write(tmp_path, _PNG_MAGIC)):
        read = asyncio.create_task(route_document("https://cdn.example.com/i.png", client=_stub_client(stub)))
        await asyncio.wait_for(stub.submit_started.wait(), timeout=5)
        read.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(read, timeout=1)
    stub.release_submit.set()
    await asyncio.wait_for(_settle_ocr_deletes(), timeout=5)


@pytest.mark.asyncio
async def test_read_cancelled_during_the_submit_deletes_the_job_the_submit_created(tmp_path: Path) -> None:
    # given
    stub = _BlockingSubmitOcrStub()

    # when
    await _cancel_during_the_submit(tmp_path, stub)

    # then
    assert stub.deletes == [f"/v1/ocr/jobs/{_JOB_ID}"]
    assert not _PENDING_OCR_DELETES


@pytest.mark.asyncio
async def test_read_cancelled_during_a_submit_that_fails_deletes_nothing(tmp_path: Path) -> None:
    # given
    stub = _BlockingSubmitOcrStub(submit_status=503)

    # when
    await _cancel_during_the_submit(tmp_path, stub)

    # then
    assert stub.deletes == []
    assert not _PENDING_OCR_DELETES


@pytest.mark.asyncio
@pytest.mark.parametrize("submit_status", [202, 503])
async def test_spool_file_outlives_a_submit_still_running_after_the_cancel(
    tmp_path: Path, submit_status: int
) -> None:
    # given
    stub = _BlockingSubmitOcrStub(submit_status=submit_status)
    spool = _write(tmp_path, _PNG_MAGIC)

    with patch("src.reader.document_router._download", return_value=spool):
        read = asyncio.create_task(route_document("https://cdn.example.com/i.png", client=_stub_client(stub)))
        await asyncio.wait_for(stub.submit_started.wait(), timeout=5)

        # when
        read.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(read, timeout=1)
        kept_while_the_submit_runs = spool.exists()
        stub.release_submit.set()
        await asyncio.wait_for(_settle_ocr_deletes(), timeout=5)

    # then
    assert kept_while_the_submit_runs
    assert not spool.exists()
    assert not _HANDED_OVER_SPOOLS
    assert not _PENDING_OCR_DELETES


@pytest.mark.asyncio
async def test_close_waits_for_the_pending_deletes_then_closes_the_shared_client(tmp_path: Path) -> None:
    # given
    stub = _BlockingDeleteOcrStub("failed")
    client = _stub_client(stub)
    _SharedClientHolder.client = client
    try:
        with patch("src.reader.document_router._download", return_value=_write(tmp_path, _PNG_MAGIC)):
            await asyncio.wait_for(route_document("https://cdn.example.com/i.png"), timeout=1)
        await asyncio.wait_for(stub.delete_started.wait(), timeout=5)

        # when
        closing = asyncio.create_task(close_document_router())
        await asyncio.sleep(0)
        closed_before_the_delete = closing.done()
        stub.release_delete.set()
        await asyncio.wait_for(closing, timeout=5)
    finally:
        _SharedClientHolder.client = None

    # then
    assert not closed_before_the_delete
    assert stub.deleted.is_set()
    assert client.is_closed
    assert not _PENDING_OCR_DELETES


@pytest.mark.asyncio
async def test_close_cancels_the_deletes_still_running_after_the_drain_window(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    # given
    stub = _BlockingDeleteOcrStub("failed")
    client = _stub_client(stub)
    _SharedClientHolder.client = client
    try:
        with patch("src.reader.document_router._download", return_value=_write(tmp_path, _PNG_MAGIC)):
            await asyncio.wait_for(route_document("https://cdn.example.com/i.png"), timeout=1)
        await asyncio.wait_for(stub.delete_started.wait(), timeout=5)

        # when
        with (
            caplog.at_level(logging.WARNING, logger="src.reader.document_router"),
            patch("src.reader.document_router.settings.OCR_DELETE_DRAIN_SECONDS", 0.05),
        ):
            await asyncio.wait_for(close_document_router(), timeout=5)
    finally:
        _SharedClientHolder.client = None

    # then
    assert not stub.deleted.is_set()
    assert client.is_closed
    assert not _PENDING_OCR_DELETES
    assert _warning_text(caplog) == (
        "document_router: 1 ocr job deletes still running at shutdown are cancelled"
    )


@pytest.mark.asyncio
async def test_close_without_pending_deletes_or_shared_client_does_nothing() -> None:
    # given
    _SharedClientHolder.client = None

    # when
    await close_document_router()

    # then
    assert _SharedClientHolder.client is None
    assert not _PENDING_OCR_DELETES


@pytest.mark.asyncio
async def test_failed_submit_logs_no_password_of_the_ocr_address_or_of_the_document(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    # given
    async def handle(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    # when
    with (
        caplog.at_level(logging.WARNING, logger="src.reader.document_router"),
        patch("src.reader.document_router._download", return_value=_write(tmp_path, _PNG_MAGIC)),
        patch("src.reader.document_router.settings.ASCEND_OCR_URL", "http://u:supersecret@ocr"),
    ):
        result = await route_document(
            "https://reader:docsecret@cdn.example.com/i.png?X-Amz-Signature=secret",
            client=_stub_client(handle),
        )

    # then
    assert result is not None
    assert result.error == "submit_failed"
    text = _warning_text(caplog)
    assert "supersecret" not in text
    assert "docsecret" not in text
    assert text == (
        "document_router: ocr submit failed for https://cdn.example.com/i.png: HTTPStatusError status 503"
    )


def _ocr_answering_result_at(
    address: str, fetched: list[str]
) -> Callable[[httpx.Request], Awaitable[httpx.Response]]:
    async def handle(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(202, json={"job_id": _JOB_ID, "poll_after_seconds": 0.01})
        if request.method == "DELETE":
            return httpx.Response(204)
        if request.url.path == f"/v1/ocr/jobs/{_JOB_ID}":
            return httpx.Response(200, json={"state": "succeeded", "result": {"url": address}})
        fetched.append(str(request.url))
        return httpx.Response(200, text="# OCR Markdown")

    return handle


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("endpoint", "address"),
    [
        (_RESULT_ENDPOINT, "http://store.example.com/r.md"),
        (_RESULT_ENDPOINT, "https://attacker.example.net/r.md"),
        (_RESULT_ENDPOINT, "https://store.example.com:8443/r.md"),
        (_RESULT_ENDPOINT, "https://store.example.com:notaport/r.md"),
        (_RESULT_ENDPOINT, "https://[broken/r.md"),
        (_RESULT_ENDPOINT, "/r.md"),
        ("", "https://store.example.com/r.md"),
        ("", "/r.md"),
    ],
    ids=[
        "scheme",
        "host",
        "port",
        "bad-port",
        "bad-host",
        "no-host",
        "empty-setting",
        "empty-setting-no-host",
    ],
)
async def test_ocr_result_outside_the_public_endpoint_is_never_fetched(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, endpoint: str, address: str
) -> None:
    # given
    fetched: list[str] = []
    handle = _ocr_answering_result_at(f"{address}{_SIGNED_QUERY}", fetched)

    # when
    with (
        caplog.at_level(logging.WARNING, logger="src.reader.document_router"),
        patch("src.reader.document_router.settings.OBJECT_STORE_S3_PUBLIC_ENDPOINT", endpoint),
        patch("src.reader.document_router._download", return_value=_write(tmp_path, _PNG_MAGIC)),
    ):
        result = await route_document("https://cdn.example.com/i.png", client=_stub_client(handle))
        await _settle_ocr_deletes()

    # then
    assert result is not None
    assert result.error == "result_failed"
    assert fetched == []
    assert _warning_text(caplog) == (
        f"document_router: ocr result address of job {_JOB_ID} is not on OBJECT_STORE_S3_PUBLIC_ENDPOINT"
    )


@pytest.mark.asyncio
async def test_ocr_result_on_the_public_endpoint_is_fetched_with_its_signature(tmp_path: Path) -> None:
    # given
    fetched: list[str] = []
    address = f"{_RESULT_URL}{_SIGNED_QUERY}"
    handle = _ocr_answering_result_at(address, fetched)

    # when
    with patch("src.reader.document_router._download", return_value=_write(tmp_path, _PNG_MAGIC)):
        result = await route_document("https://cdn.example.com/i.png", client=_stub_client(handle))
        await _settle_ocr_deletes()

    # then
    assert result is not None
    assert result.error is None
    assert result.content == "# OCR Markdown"
    assert fetched == [address]


@pytest.mark.asyncio
async def test_failed_result_fetch_logs_no_presigned_address(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    # given
    presigned = (
        "https://store.example.com/ocr-results/r.md"
        "?X-Amz-Credential=AKIDEXAMPLE%2F20261108&X-Amz-Signature=deadbeefsignature"
    )

    async def handle(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(202, json={"job_id": _JOB_ID, "poll_after_seconds": 0.01})
        if request.method == "DELETE":
            return httpx.Response(204)
        if request.url.path == f"/v1/ocr/jobs/{_JOB_ID}":
            return httpx.Response(200, json={"state": "succeeded", "result": {"url": presigned}})
        return httpx.Response(403)

    # when
    with (
        caplog.at_level(logging.WARNING, logger="src.reader.document_router"),
        patch("src.reader.document_router._download", return_value=_write(tmp_path, _PNG_MAGIC)),
    ):
        result = await route_document("https://cdn.example.com/i.png", client=_stub_client(handle))
        await _settle_ocr_deletes()

    # then
    assert result is not None
    assert result.error == "result_failed"
    text = _warning_text(caplog)
    assert "deadbeefsignature" not in text
    assert "X-Amz" not in text
    assert text == f"document_router: ocr result fetch failed for job {_JOB_ID}: HTTPStatusError status 403"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("setting", "document", "body", "message"),
    [
        (
            "DOCLING_SERVE_URL",
            "https://reader:docsecret@cdn.example.com/doc.pdf?X-Amz-Signature=secret",
            _PDF_MAGIC,
            "document_router: pdf conversion failed for https://cdn.example.com/doc.pdf: "
            "HTTPStatusError status 503",
        ),
        (
            "AUDIO_SCRIBE_URL",
            "https://reader:docsecret@cdn.example.com/a.mp3?X-Amz-Signature=secret",
            b"ID3fakeaudio",
            "document_router: audio transcription failed for https://cdn.example.com/a.mp3: "
            "HTTPStatusError status 503",
        ),
    ],
)
async def test_failed_conversion_logs_no_password(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    setting: str,
    document: str,
    body: bytes,
    message: str,
) -> None:
    # given
    async def handle(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    # when
    with (
        caplog.at_level(logging.WARNING, logger="src.reader.document_router"),
        patch("src.reader.document_router._download", return_value=_write(tmp_path, body)),
        patch(f"src.reader.document_router.settings.{setting}", "http://u:supersecret@svc"),
    ):
        result = await route_document(document, client=_stub_client(handle))

    # then
    assert result is not None
    assert not result.ok
    assert _warning_text(caplog) == message


@pytest.mark.asyncio
async def test_failed_poll_logs_the_error_type_only(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    # given
    async def handle(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(202, json={"job_id": _JOB_ID, "poll_after_seconds": 0.01})
        if request.method == "DELETE":
            return httpx.Response(204)
        raise httpx.ConnectError("connect to http://u:supersecret@ocr failed", request=request)

    # when
    with (
        caplog.at_level(logging.WARNING, logger="src.reader.document_router"),
        patch("src.reader.document_router._download", return_value=_write(tmp_path, _PNG_MAGIC)),
        patch("src.reader.document_router.settings.ASCEND_OCR_URL", "http://u:supersecret@ocr"),
    ):
        result = await route_document("https://cdn.example.com/i.png", client=_stub_client(handle))
        await _settle_ocr_deletes()

    # then
    assert result is not None
    assert result.error == "poll_failed"
    assert _warning_text(caplog) == f"document_router: ocr poll failed for job {_JOB_ID}: ConnectError"


def _succeeded_job_answering(result_body: bytes) -> Callable[[httpx.Request], Awaitable[httpx.Response]]:
    async def handle(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(202, json={"job_id": _JOB_ID, "poll_after_seconds": 0.01})
        if request.method == "DELETE":
            return httpx.Response(204)
        if request.url.path == f"/v1/ocr/jobs/{_JOB_ID}":
            return httpx.Response(200, json={"state": "succeeded", "result": {"url": _RESULT_URL}})
        return httpx.Response(200, content=result_body, headers={"content-type": "text/markdown"})

    return handle


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("size", "content", "error"),
    [(16, "x" * 16, None), (17, None, "result_failed")],
)
async def test_ocr_result_is_read_capped_at_document_max_bytes(
    tmp_path: Path, size: int, content: str | None, error: str | None
) -> None:
    # given
    handle = _succeeded_job_answering(b"x" * size)

    # when
    with (
        patch("src.reader.document_router._download", return_value=_write(tmp_path, _PNG_MAGIC)),
        patch("src.reader.document_router.settings.DOCUMENT_MAX_BYTES", 16),
    ):
        result = await route_document("https://cdn.example.com/i.png", client=_stub_client(handle))
        await _settle_ocr_deletes()

    # then
    assert result is not None
    assert result.content == content
    assert result.error == error


@pytest.mark.asyncio
async def test_ocr_result_is_decoded_with_its_declared_charset(tmp_path: Path) -> None:
    # given
    async def handle(request: httpx.Request) -> httpx.Response:
        answer = await _succeeded_job_answering(b"")(request)
        if str(request.url) != _RESULT_URL:
            return answer
        return httpx.Response(
            200,
            content="zażółć".encode("iso-8859-2"),
            headers={"content-type": "text/markdown; charset=iso-8859-2"},
        )

    # when
    with patch("src.reader.document_router._download", return_value=_write(tmp_path, _PNG_MAGIC)):
        result = await route_document("https://cdn.example.com/i.png", client=_stub_client(handle))
        await _settle_ocr_deletes()

    # then
    assert result is not None
    assert result.content == "zażółć"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "job_id",
    [
        "job1",
        "AbCdEfGhIjKlMnOpQrSt_-x",
        "AbCdEfGhIjKlMnOpQrS/..",
        "AbCdEfGhIjKlMnOpQrSt_\n",
        "../../../v1/ocr/jobs/AbC",
    ],
)
async def test_submit_answering_a_job_id_outside_the_ocr_format_is_submit_failed(
    tmp_path: Path, job_id: str
) -> None:
    # given
    seen: list[str] = []

    async def handle(request: httpx.Request) -> httpx.Response:
        seen.append(f"{request.method} {request.url.path}")
        if request.method == "POST":
            return httpx.Response(202, json={"job_id": job_id, "poll_after_seconds": 0.01})
        return httpx.Response(200, json={"state": "failed"})

    # when
    with patch("src.reader.document_router._download", return_value=_write(tmp_path, _PNG_MAGIC)):
        result = await route_document("https://cdn.example.com/i.png", client=_stub_client(handle))
        await _settle_ocr_deletes()

    # then
    assert result is not None
    assert result.error == "submit_failed"
    assert seen == ["POST /v1/ocr/jobs"]


@pytest.mark.asyncio
async def test_audio_transcribed(tmp_path: Path) -> None:
    # given
    seen: dict[str, Any] = {}

    async def handle(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        return httpx.Response(200, text="# invented canary transcript")

    # when
    with patch("src.reader.document_router._download", return_value=_write(tmp_path, b"ID3fakeaudio")):
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
    assert result.error == "file_too_large"
    assert result.ends_read is True


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
    assert result.ends_read is False
    assert posts == 0


_PUBLIC_RESULT_ADDRESS = (
    "http://localhost:9070/ocr-results/result.md"
    "?X-Amz-Credential=AKID%2F20261108&X-Amz-SignedHeaders=host&X-Amz-Signature=abc%2Bdef"
)


async def _route_image_answering_result(
    tmp_path: Path, address: str, on_result: Callable[[httpx.Request], httpx.Response]
) -> Any:
    async def handle(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(202, json={"job_id": _JOB_ID, "poll_after_seconds": 0.01})
        if request.method == "DELETE":
            return httpx.Response(204)
        if "/v1/ocr/jobs/" in str(request.url):
            return httpx.Response(200, json={"state": "succeeded", "result": {"url": address}})

        return on_result(request)

    with (
        patch("src.reader.document_router._download", return_value=_write(tmp_path, _PNG_MAGIC)),
        patch("src.reader.document_router.settings.ASCEND_OCR_URL", "http://ocr"),
        patch("src.reader.document_router.settings.OBJECT_STORE_S3_PUBLIC_ENDPOINT", "http://localhost:9070"),
        patch(
            "src.reader.document_router.settings.OBJECT_STORE_S3_ENDPOINT",
            "http://host.docker.internal:9070/",
        ),
    ):
        result = await route_document("https://cdn.example.com/i.png", client=_stub_client(handle))
    await _settle_ocr_deletes()

    return result


@pytest.mark.asyncio
async def test_the_ocr_result_is_read_on_the_store_address_with_the_signed_host(tmp_path: Path) -> None:
    # given
    seen: list[httpx.Request] = []

    def on_result(request: httpx.Request) -> httpx.Response:
        seen.append(request)

        return httpx.Response(200, text="recognised text")

    # when
    result = await _route_image_answering_result(tmp_path, _PUBLIC_RESULT_ADDRESS, on_result)

    # then
    assert result.error is None
    assert result.content == "recognised text"
    assert [request.url.host for request in seen] == ["host.docker.internal"]
    assert seen[0].url.port == 9070
    assert seen[0].url.raw_path.decode() == _PUBLIC_RESULT_ADDRESS.removeprefix("http://localhost:9070")
    assert seen[0].headers["host"] == "localhost:9070"


@pytest.mark.asyncio
async def test_a_redirect_from_the_store_is_not_followed(tmp_path: Path) -> None:
    # given
    seen: list[httpx.Request] = []

    def on_result(request: httpx.Request) -> httpx.Response:
        seen.append(request)

        return httpx.Response(302, headers={"location": "http://elsewhere.example.com/stolen"})

    # when
    result = await _route_image_answering_result(tmp_path, _PUBLIC_RESULT_ADDRESS, on_result)

    # then
    assert result.error == "result_failed"
    assert len(seen) == 1


@pytest.mark.asyncio
async def test_a_result_with_user_info_sends_only_the_host_and_port(tmp_path: Path) -> None:
    # given
    seen: list[httpx.Request] = []

    def on_result(request: httpx.Request) -> httpx.Response:
        seen.append(request)

        return httpx.Response(200, text="recognised text")

    # when
    await _route_image_answering_result(tmp_path, "http://u:pw@localhost:9070/r.md?sig=1", on_result)

    # then
    assert seen[0].headers["host"] == "localhost:9070"

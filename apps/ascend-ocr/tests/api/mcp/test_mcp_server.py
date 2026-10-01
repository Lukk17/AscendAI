import ipaddress
import logging
import socket as socket_mod
import time
from collections.abc import AsyncIterator
from pathlib import Path
from unittest.mock import AsyncMock, patch
from urllib.parse import urlparse

import aiohttp
import pytest
from fastmcp.exceptions import ToolError
from pydantic import ValidationError

from src.api.exception_handlers import (
    DownloadFailedError,
    FileSizeExceededError,
    UnsafeUriError,
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
    mcp,
    mcp_lifespan,
    ocr_cancel_job,
    ocr_job_status,
    ocr_list_jobs,
    ocr_submit,
)
from src.config.config import settings
from src.model.ocr_models import JobResultLocation, JobState
from src.observability.metrics import OCR_REQUESTS_TOTAL
from src.service.job_runner import JobRunner
from src.service.job_service import JobService
from src.service.job_store import JobStore, new_job_id
from tests.conftest import PNG_MAGIC_BYTES, VALID_PNG_BYTES, FakeResultStore, make_record, write_finished_record

SHIPPED_LANGUAGE_REFUSAL = "Language is not supported. Supported languages: en, pl, de, fr, es, it, pt, nl, ch, japan"


@pytest.fixture
def store(jobs_dir: Path, results: FakeResultStore) -> JobStore:
    _ = jobs_dir

    return JobStore(results)


@pytest.fixture
def runner(store: JobStore, results: FakeResultStore) -> JobRunner:
    return JobRunner(store, results)


@pytest.fixture(autouse=True)
def service(
    store: JobStore, results: FakeResultStore, runner: JobRunner, monkeypatch: pytest.MonkeyPatch
) -> JobService:
    """Every tool call in this module runs against this test's own store and bucket."""
    built = JobService(store, results, runner)
    monkeypatch.setattr("src.api.mcp.mcp_server.job_service", built)

    return built


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

    async def iter_chunked(self, size: int) -> AsyncIterator[bytes]:
        for offset in range(0, len(self._body), size):
            yield self._body[offset : offset + size]


class _FakeSession:
    def __init__(self, response: _FakeResponse | Exception) -> None:
        self._response = response
        self.last_url: str | None = None
        self.last_kwargs: dict[str, object] | None = None

    def get(self, url: str, **kwargs: object) -> _FakeResponse:
        self.last_url = url
        self.last_kwargs = kwargs
        if isinstance(self._response, Exception):
            raise self._response

        return self._response


class TestToolCatalogue:
    async def test_the_four_job_tools_are_advertised_and_the_removed_one_is_not(self):
        # When
        advertised = {tool.name for tool in await mcp.list_tools()}

        # Then
        assert advertised == {"ocr_submit", "ocr_job_status", "ocr_list_jobs", "ocr_cancel_job"}
        assert not any("process" in name for name in advertised)


class TestOcrSubmit:
    async def test_a_jailed_file_uri_is_accepted_and_answered_with_an_identifier(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, store: JobStore
    ) -> None:
        # Given
        monkeypatch.setattr(settings, "MCP_FILE_URI_ROOT", str(tmp_path))
        image_path = tmp_path / "scan.png"
        image_path.write_bytes(VALID_PNG_BYTES)

        # When
        result = await ocr_submit(image_path.as_uri(), lang="en")

        # Then
        assert result["state"] == "waiting"
        assert result["page_count"] == 1
        assert result["status_url"] == "/v1/ocr/jobs/" + str(result["job_id"])
        assert "pages" not in result
        stored = store.read(str(result["job_id"]))
        assert stored.filename == "scan.png"
        assert stored.surface == "mcp"

    async def test_the_requested_quality_mode_is_recorded(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, store: JobStore
    ) -> None:
        # Given
        monkeypatch.setattr(settings, "MCP_FILE_URI_ROOT", str(tmp_path))
        image_path = tmp_path / "scan.png"
        image_path.write_bytes(VALID_PNG_BYTES)

        # When
        result = await ocr_submit(image_path.as_uri(), lang="en", quality="normal")

        # Then
        assert store.read(str(result["job_id"])).quality == "normal"

    async def test_an_omitted_quality_mode_is_high(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, store: JobStore
    ) -> None:
        # Given
        monkeypatch.setattr(settings, "MCP_FILE_URI_ROOT", str(tmp_path))
        image_path = tmp_path / "scan.png"
        image_path.write_bytes(VALID_PNG_BYTES)

        # When
        result = await ocr_submit(image_path.as_uri(), lang="en")

        # Then
        assert store.read(str(result["job_id"])).quality == "high"

    async def test_the_tool_advertises_exactly_the_two_modes_with_high_as_default(self):
        # When
        tool = next(tool for tool in await mcp.list_tools() if tool.name == "ocr_submit")

        # Then
        quality = tool.parameters["properties"]["quality"]
        assert quality["enum"] == ["normal", "high"]
        assert quality["default"] == "high"

    async def test_an_unknown_quality_mode_is_refused_before_anything_is_fetched(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Given
        monkeypatch.setattr(settings, "MCP_FILE_URI_ROOT", str(tmp_path))
        image_path = tmp_path / "scan.png"
        image_path.write_bytes(VALID_PNG_BYTES)

        # When / Then
        with (
            patch("src.api.mcp.mcp_server._fetch_file", new_callable=AsyncMock) as fetch,
            pytest.raises(ValidationError, match="Input should be 'normal' or 'high'"),
        ):
            await mcp.call_tool("ocr_submit", {"file_uri": image_path.as_uri(), "quality": "ultra"})

        fetch.assert_not_awaited()

    async def test_a_straighten_request_is_recorded(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, store: JobStore
    ) -> None:
        # Given
        monkeypatch.setattr(settings, "MCP_FILE_URI_ROOT", str(tmp_path))
        image_path = tmp_path / "photo.png"
        image_path.write_bytes(VALID_PNG_BYTES)

        # When
        result = await ocr_submit(image_path.as_uri(), lang="en", straighten=True)

        # Then
        assert store.read(str(result["job_id"])).straighten is True

    async def test_an_omitted_straighten_choice_is_off(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, store: JobStore
    ) -> None:
        # Given
        monkeypatch.setattr(settings, "MCP_FILE_URI_ROOT", str(tmp_path))
        image_path = tmp_path / "scan.png"
        image_path.write_bytes(VALID_PNG_BYTES)

        # When
        result = await ocr_submit(image_path.as_uri(), lang="en")

        # Then
        assert store.read(str(result["job_id"])).straighten is False

    async def test_the_tool_advertises_straighten_as_an_optional_boolean_that_is_off(self):
        # When
        tool = next(tool for tool in await mcp.list_tools() if tool.name == "ocr_submit")

        # Then
        straighten = tool.parameters["properties"]["straighten"]
        assert straighten["type"] == "boolean"
        assert straighten["default"] is False
        assert "straighten" not in tool.parameters.get("required", [])

    async def test_a_straighten_value_that_is_not_a_boolean_is_refused_before_anything_is_fetched(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Given
        monkeypatch.setattr(settings, "MCP_FILE_URI_ROOT", str(tmp_path))
        image_path = tmp_path / "scan.png"
        image_path.write_bytes(VALID_PNG_BYTES)

        # When / Then
        with (
            patch("src.api.mcp.mcp_server._fetch_file", new_callable=AsyncMock) as fetch,
            pytest.raises(ValidationError, match="valid boolean"),
        ):
            await mcp.call_tool("ocr_submit", {"file_uri": image_path.as_uri(), "straighten": "sometimes"})

        fetch.assert_not_awaited()

    @patch("src.api.mcp.mcp_server._validate_host", new_callable=AsyncMock)
    async def test_an_http_uri_is_fetched_through_the_module_session(
        self, _validate_host_mock: AsyncMock, store: JobStore
    ) -> None:
        # Given
        session = _FakeSession(_FakeResponse(status=200, body=VALID_PNG_BYTES))

        # When
        with patch.object(mcp_server, "_http_session", session):
            result = await ocr_submit("http://host.docker.internal:9070/bucket/remote.png", lang="en")

        # Then
        assert session.last_url == "http://host.docker.internal:9070/bucket/remote.png"
        assert session.last_kwargs == {"allow_redirects": False}
        assert store.read(str(result["job_id"])).filename == "remote.png"

    @patch("src.api.mcp.mcp_server._validate_host", new_callable=AsyncMock)
    async def test_an_http_url_basename_is_decoded(self, _validate_host_mock: AsyncMock, store: JobStore) -> None:
        # Given
        session = _FakeSession(_FakeResponse(status=200, body=VALID_PNG_BYTES))

        # When
        with patch.object(mcp_server, "_http_session", session):
            result = await ocr_submit(
                "http://host.docker.internal:9070/bucket/scan%20with%20space.png",
                lang="en",
            )

        # Then
        assert store.read(str(result["job_id"])).filename == "scan with space.png"


class TestOcrSubmitErrorCodes:
    async def test_unsafe_uri_error_code_in_message(self):
        # Given a URI with embedded credentials (triggers UnsafeUriError before any fetch)
        with pytest.raises(ToolError, match=r"^UNSAFE_URI: "):
            await ocr_submit("http://user:pass@example.com/x.png", lang="en")

    async def test_unsupported_scheme_error_code_in_message(self):
        # Given a bare ftp:// URI (not http/https/file - triggers UnsafeUriError for scheme)
        with pytest.raises(ToolError, match=r"^UNSAFE_URI: "):
            await ocr_submit("ftp://example.com/x.png", lang="en")

    @patch("src.api.mcp.mcp_server._validate_host", new_callable=AsyncMock)
    async def test_unsupported_file_type_error_code_in_message(self, _validate_host_mock):
        # Given a URL that returns non-image bytes (plain text), sniff_mime raises
        session = _FakeSession(_FakeResponse(status=200, body=b"plain text data"))
        with (
            patch.object(mcp_server, "_http_session", session),
            pytest.raises(ToolError, match=r"^UNSUPPORTED_FILE_TYPE: "),
        ):
            await ocr_submit("http://example.com/x.txt", lang="en")

    @patch("src.api.mcp.mcp_server._validate_host", new_callable=AsyncMock)
    async def test_file_too_large_error_code_in_message(self, _validate_host_mock, monkeypatch):
        # Given an oversized Content-Length header, FileSizeExceededError fires during download
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
            pytest.raises(ToolError, match=r"^FILE_TOO_LARGE: "),
        ):
            await ocr_submit("http://example.com/big.png", lang="en")

    @patch("src.api.mcp.mcp_server._validate_host", new_callable=AsyncMock)
    async def test_download_failed_error_code_in_message(self, _validate_host_mock):
        # Given a 404 response, DownloadFailedError fires
        session = _FakeSession(_FakeResponse(status=404, body=b""))
        with (
            patch.object(mcp_server, "_http_session", session),
            pytest.raises(ToolError, match=r"^DOWNLOAD_FAILED: "),
        ):
            await ocr_submit("http://example.com/missing.png", lang="en")

    @pytest.mark.parametrize("language", ["korean", "ru"])
    async def test_an_unsupported_language_is_refused_before_anything_is_fetched_or_queued(
        self, runner: JobRunner, language: str
    ) -> None:
        # Given
        fetch = AsyncMock(return_value=(VALID_PNG_BYTES, "scan.png"))

        # When
        with (
            patch.object(mcp_server, "_fetch_file", fetch),
            pytest.raises(ToolError) as exc_info,
        ):
            await ocr_submit("http://example.com/scan.png", lang=language)

        # Then
        assert str(exc_info.value) == f"UNSUPPORTED_LANGUAGE: {SHIPPED_LANGUAGE_REFUSAL}"
        fetch.assert_not_awaited()
        assert runner.documents_waiting() == 0

    async def test_a_refused_language_is_counted_under_one_fixed_label(self):
        # Given
        before = OCR_REQUESTS_TOTAL.labels(surface="mcp", language="unsupported")._value.get()

        # When
        with pytest.raises(ToolError):
            await ocr_submit("http://example.com/scan.png", lang="qqzzxy")

        # Then
        assert OCR_REQUESTS_TOTAL.labels(surface="mcp", language="unsupported")._value.get() == before + 1
        labels = {sample.labels["language"] for metric in OCR_REQUESTS_TOTAL.collect() for sample in metric.samples}
        assert "qqzzxy" not in labels

    async def test_queue_full_error_code_in_message(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        # Given
        monkeypatch.setattr(settings, "MCP_FILE_URI_ROOT", str(tmp_path))
        monkeypatch.setattr(settings, "OCR_JOB_QUEUE_MAX_DOCUMENTS", 1)
        image_path = tmp_path / "scan.png"
        image_path.write_bytes(VALID_PNG_BYTES)
        await ocr_submit(image_path.as_uri(), lang="en")

        # Then
        with pytest.raises(ToolError, match=r"^QUEUE_FULL: "):
            await ocr_submit(image_path.as_uri(), lang="en")


class TestOcrJobStatus:
    async def test_the_state_of_waiting_work_is_readable(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        # Given
        monkeypatch.setattr(settings, "MCP_FILE_URI_ROOT", str(tmp_path))
        image_path = tmp_path / "scan.png"
        image_path.write_bytes(VALID_PNG_BYTES)
        submitted = await ocr_submit(image_path.as_uri(), lang="en")

        # When
        status = ocr_job_status(str(submitted["job_id"]))

        # Then
        assert status["state"] == "waiting"
        poll_after_seconds = status["poll_after_seconds"]
        assert isinstance(poll_after_seconds, float)
        assert poll_after_seconds >= 1.0
        assert status["result"] is None

    def test_successful_work_carries_the_address_and_no_hint(self, store: JobStore) -> None:
        # Given
        record = make_record(state="running", page_count=2, started_at=time.time())
        store.write(record)
        store.succeed(record, JobResultLocation(bucket="ocr-results", key=record.job_id + ".md"), 2.0)

        # When
        status = ocr_job_status(record.job_id)

        # Then
        assert status["state"] == "succeeded"
        assert "poll_after_seconds" not in status
        result = status["result"]
        assert isinstance(result, dict)
        assert result["bucket"] == "ocr-results"
        assert result["key"] == record.job_id + ".md"

    @pytest.mark.parametrize("state", ["succeeded", "failed", "cancelled"])
    def test_a_terminal_record_carries_no_hint_key_at_all(self, store: JobStore, state: JobState) -> None:
        # Given
        record = write_finished_record(store, state)

        # When
        status = ocr_job_status(record.job_id)

        # Then
        assert status["state"] == state
        assert "poll_after_seconds" not in status
        assert status["queue_position"] is None
        assert status["pages_ahead"] is None

    def test_a_running_record_carries_a_hint(self, store: JobStore) -> None:
        # Given
        record = make_record(state="running", started_at=time.time())
        store.write(record)

        # When
        status = ocr_job_status(record.job_id)

        # Then
        assert status["state"] == "running"
        poll_after_seconds = status["poll_after_seconds"]
        assert isinstance(poll_after_seconds, float)
        assert poll_after_seconds >= 1.0
        assert status["queue_position"] is None
        assert status["pages_ahead"] is None

    def test_an_unknown_identifier_carries_the_not_found_code(self):
        # Then
        with pytest.raises(ToolError, match=r"^JOB_NOT_FOUND: "):
            ocr_job_status(new_job_id())

    def test_an_identifier_that_is_not_shaped_like_one_carries_the_same_code(self):
        # Then
        with pytest.raises(ToolError, match=r"^JOB_NOT_FOUND: "):
            ocr_job_status("../../etc/passwd")


class TestOcrListJobs:
    def test_an_idle_service_lists_nothing(self):
        # Then
        assert ocr_list_jobs() == {"jobs": []}

    async def test_work_in_flight_is_listed_in_submission_order(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Given
        monkeypatch.setattr(settings, "MCP_FILE_URI_ROOT", str(tmp_path))
        image_path = tmp_path / "scan.png"
        image_path.write_bytes(VALID_PNG_BYTES)
        first = await ocr_submit(image_path.as_uri(), lang="en")
        second = await ocr_submit(image_path.as_uri(), lang="en")

        # When
        listing = ocr_list_jobs()

        # Then
        jobs = listing["jobs"]
        assert isinstance(jobs, list)
        assert [entry["job_id"] for entry in jobs] == [first["job_id"], second["job_id"]]
        assert [entry["queue_position"] for entry in jobs] == [0, 1]

    async def test_a_running_entry_carries_no_queue_position(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, runner: JobRunner
    ) -> None:
        # Given
        monkeypatch.setattr(settings, "MCP_FILE_URI_ROOT", str(tmp_path))
        image_path = tmp_path / "scan.png"
        image_path.write_bytes(VALID_PNG_BYTES)
        await ocr_submit(image_path.as_uri(), lang="en")
        await ocr_submit(image_path.as_uri(), lang="en")
        runner._running = runner._queue.popleft()

        # When
        listing = ocr_list_jobs()

        # Then
        jobs = listing["jobs"]
        assert isinstance(jobs, list)
        assert [entry["state"] for entry in jobs] == ["running", "waiting"]
        assert [entry["queue_position"] for entry in jobs] == [None, 1]


class TestOcrCancelJob:
    async def test_cancelling_waiting_work_answers_the_identifier(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, store: JobStore
    ) -> None:
        # Given
        monkeypatch.setattr(settings, "MCP_FILE_URI_ROOT", str(tmp_path))
        image_path = tmp_path / "scan.png"
        image_path.write_bytes(VALID_PNG_BYTES)
        submitted = await ocr_submit(image_path.as_uri(), lang="en")

        # When
        cancelled = await ocr_cancel_job(str(submitted["job_id"]))

        # Then
        assert cancelled == {"job_id": submitted["job_id"], "cancelled": True}
        assert store.read(str(submitted["job_id"])).state == "cancelled"

    async def test_cancelling_an_unknown_identifier_carries_the_not_found_code(self):
        # Then
        with pytest.raises(ToolError, match=r"^JOB_NOT_FOUND: "):
            await ocr_cancel_job(new_job_id())


class TestFetchFileRejections:
    async def test_unsupported_scheme(self):
        # Then
        with pytest.raises(UnsafeUriError, match="Unsupported URI scheme"):
            await _fetch_file("ftp://example.com/file.png")

    async def test_bare_path_is_rejected(self, tmp_path: Path) -> None:
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

    async def test_traversal_outside_root_is_rejected(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        # Given
        jail = tmp_path / "jail"
        jail.mkdir()
        outside = tmp_path / "outside.png"
        outside.write_bytes(b"x")
        monkeypatch.setattr(settings, "MCP_FILE_URI_ROOT", str(jail))

        # Then
        with pytest.raises(UnsafeUriError, match="escapes MCP_FILE_URI_ROOT"):
            await _read_jailed_file("/" + str(outside).replace("\\", "/"))

    async def test_missing_file_inside_root(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        # Given a path inside the jail that does not exist on disk
        monkeypatch.setattr(settings, "MCP_FILE_URI_ROOT", str(tmp_path))
        ghost = tmp_path / "ghost.png"
        url_path = "/" + str(ghost).replace("\\", "/")

        # Then
        with pytest.raises(DownloadFailedError, match="File not found"):
            await _read_jailed_file(url_path)

    async def test_size_cap_enforced_after_read(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
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

        # When / Then - no raise
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

        # When / Then - no raise
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
    def test_is_blocked_true_for_private_and_special(self, ip_str: str) -> None:
        # Then
        assert _is_blocked(ipaddress.ip_address(ip_str)) is True

    def test_is_blocked_false_for_public(self):
        # Then
        assert _is_blocked(ipaddress.ip_address("8.8.8.8")) is False

    def test_is_within_true(self, tmp_path: Path) -> None:
        # Then
        assert _is_within(str(tmp_path / "x.png"), str(tmp_path)) is True

    def test_is_within_false_when_outside(self, tmp_path: Path) -> None:
        # Then
        assert _is_within(str(tmp_path / "elsewhere"), str(tmp_path / "jail")) is False

    def test_is_within_false_on_value_error(self):
        # Given
        # os.path.commonpath raises ValueError when the paths cannot be compared at all
        # (e.g. different drives on Windows). Force that outcome directly instead of
        # relying on a platform-specific path shape, so the branch is exercised on Linux too.
        with patch("os.path.commonpath", side_effect=ValueError("paths don't have the same drive")):
            # Then
            assert _is_within("/a", "/b") is False

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


class TestRefusalLogging:
    @pytest.mark.parametrize(
        "file_uri",
        [
            "http://someone:secret-pass@example.com/x.png",
            "ftp://example.com/x.png",
            "file:///etc/passwd",
            "http://127.0.0.1/x.png",
        ],
    )
    async def test_a_refused_uri_is_one_warning_naming_its_code_with_no_traceback(
        self, emitted_logs, monkeypatch, file_uri
    ):
        # Given
        monkeypatch.setattr(settings, "MCP_FILE_URI_ROOT", None)
        monkeypatch.setattr(settings, "MCP_ALLOWED_HOSTS", [])

        # When
        with pytest.raises(ToolError, match=r"^UNSAFE_URI: "):
            await mcp.call_tool("ocr_submit", {"file_uri": file_uri, "lang": "en"})

        # Then
        visible = [record for record in emitted_logs if record.levelno >= logging.WARNING]
        assert [(record.levelno, "UNSAFE_URI" in record.getMessage(), record.exc_info) for record in visible] == [
            (logging.WARNING, True, None)
        ]

    async def test_the_credentials_of_a_refused_uri_are_never_logged(self, emitted_logs):
        # When
        with pytest.raises(ToolError):
            await mcp.call_tool("ocr_submit", {"file_uri": "http://someone:secret-pass@example.com/x.png"})

        # Then
        assert not any("secret-pass" in record.getMessage() for record in emitted_logs)

    async def test_an_unsupported_language_is_one_warning_naming_its_code(self, emitted_logs):
        # When
        with pytest.raises(ToolError, match=r"^UNSUPPORTED_LANGUAGE: "):
            await mcp.call_tool("ocr_submit", {"file_uri": "http://example.com/x.png", "lang": "qqzzxy"})

        # Then
        visible = [record for record in emitted_logs if record.levelno >= logging.WARNING]
        assert [(record.levelno, "UNSUPPORTED_LANGUAGE" in record.getMessage()) for record in visible] == [
            (logging.WARNING, True)
        ]

    async def test_an_unknown_job_is_one_warning_naming_its_code(self, emitted_logs):
        # When
        with pytest.raises(ToolError, match=r"^JOB_NOT_FOUND: "):
            await mcp.call_tool("ocr_job_status", {"job_id": new_job_id()})

        # Then
        visible = [record for record in emitted_logs if record.levelno >= logging.WARNING]
        assert [(record.levelno, "JOB_NOT_FOUND" in record.getMessage()) for record in visible] == [
            (logging.WARNING, True)
        ]

    async def test_a_refusal_keeps_the_service_error_as_its_cause(self):
        # When
        with pytest.raises(ToolError) as exc_info:
            await ocr_submit("ftp://example.com/x.png", lang="en")

        # Then
        assert isinstance(exc_info.value.__cause__, UnsafeUriError)

    async def test_an_unexpected_failure_is_still_an_error_with_its_traceback(self, emitted_logs, service):
        # When
        with patch.object(service, "status", side_effect=RuntimeError("boom")), pytest.raises(ToolError):
            await mcp.call_tool("ocr_job_status", {"job_id": new_job_id()})

        # Then
        visible = [record for record in emitted_logs if record.levelno >= logging.WARNING]
        assert [record.levelno for record in visible] == [logging.ERROR]
        assert visible[0].exc_info is not None

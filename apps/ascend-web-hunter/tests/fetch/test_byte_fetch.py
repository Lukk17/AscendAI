"""Task 1.4: stream_to_file against a local test server."""

import asyncio
import gzip
import logging
import socket
import tempfile
import threading
import time
import zlib
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import asynccontextmanager, contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from ascend_python_common.uri_guard import FetchPolicy
from curl_cffi.requests.exceptions import RequestException
from curl_cffi.requests.headers import Headers

from src.fetch.byte_fetch import DocumentTooLargeError, stream_to_file
from src.fetch.pinned_fetch import stopping_hops
from src.reader.document_router import _download

_SMALL_BODY = b"hello"
_BIG_BODY = b"x" * 100
_ERROR_BODY = b"<html>server error</html>"
_REQUEST_READ_BYTES = 65536
_SERVER_JOIN_SECONDS = 5
_CAP_BYTES = 1024
_ABOVE_CAP_BYTES = 52428801
_UNDER_CAP_BYTES = 10
_INFLATED_BOMB_BYTES = 8 * 1024 * 1024
_DRIP_BYTES = 200
_DRIP_PAUSE_SECONDS = 0.02
_FETCH_DEADLINE_SECONDS = 0.3


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args: object) -> None:
        return

    def do_GET(self) -> None:
        if self.path == "/small":
            self._send_body(_SMALL_BODY, declared=True)
        elif self.path == "/stream-big":
            self._send_body(_BIG_BODY, declared=False)
        elif self.path == "/error":
            self.send_response(500)
            self.send_header("Content-Length", str(len(_ERROR_BODY)))
            self.end_headers()
            self.wfile.write(_ERROR_BODY)
        elif self.path == "/gzip-small":
            self._send_coded_body(gzip.compress(_SMALL_BODY), "gzip")
        elif self.path == "/gzip-bomb":
            self._send_coded_body(gzip.compress(bytes(_INFLATED_BOMB_BYTES)), "gzip")
        elif self.path == "/gzip-cut":
            self._send_declared_coded_body(gzip.compress(_SMALL_BODY * 2000)[:-6], "gzip")
        elif self.path == "/zlib-as-gzip":
            self._send_declared_coded_body(zlib.compress(_SMALL_BODY), "gzip")
        elif self.path == "/compress":
            self._send_coded_body(b"not a supported coding", "compress")
        elif self.path == "/drip":
            self._send_dripped_body()
        elif self.path == "/redir":
            self.send_response(302)
            self.send_header("Location", "/small")
            self.end_headers()
        else:
            self.send_response(404)
            self.end_headers()

    def _send_dripped_body(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "application/pdf")
        self.end_headers()
        try:
            for _ in range(_DRIP_BYTES):
                self.wfile.write(b"x")
                self.wfile.flush()
                time.sleep(_DRIP_PAUSE_SECONDS)
        except (BrokenPipeError, ConnectionResetError):
            return

    def _send_coded_body(self, body: bytes, coding: str) -> None:
        self.send_response(200)
        self.send_header("Content-Encoding", coding)
        self.end_headers()
        self.wfile.write(body)

    def _send_declared_coded_body(self, body: bytes, coding: str) -> None:
        self.send_response(200)
        self.send_header("Content-Encoding", coding)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_body(self, body: bytes, *, declared: bool) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        if declared:
            self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if declared:
            self.wfile.write(body)
        else:
            for i in range(0, len(body), 10):
                self.wfile.write(body[i : i + 10])
                self.wfile.flush()


@pytest.fixture
def local_server() -> Iterator[str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


_HUGE_CHUNK = b"x" * 65536
_HUGE_CHUNK_COUNT = 1024


class _HugeBodyServer(ThreadingHTTPServer):
    def __init__(self) -> None:
        super().__init__(("127.0.0.1", 0), _HugeBodyHandler)
        self.sent_whole_body = threading.Event()
        self.handler_finished = threading.Event()


class _HugeBodyHandler(BaseHTTPRequestHandler):
    def log_message(self, *_args: object) -> None:
        return

    def do_GET(self) -> None:
        server = self.server
        assert isinstance(server, _HugeBodyServer)
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.end_headers()
        try:
            for _ in range(_HUGE_CHUNK_COUNT):
                self.wfile.write(_HUGE_CHUNK)
            server.sent_whole_body.set()
        except (BrokenPipeError, ConnectionResetError):
            return
        finally:
            server.handler_finished.set()


@pytest.fixture
def huge_body_server() -> Iterator[_HugeBodyServer]:
    server = _HugeBodyServer()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


@contextmanager
def _declares_then_closes(status_line: str, declared_bytes: int) -> Iterator[str]:
    """A real socket server that sends the headers of one answer and closes without any body."""
    head = (
        f"HTTP/1.1 {status_line}\r\n"
        "Content-Type: application/pdf\r\n"
        f"Content-Length: {declared_bytes}\r\n"
        "Connection: close\r\n\r\n"
    ).encode()
    with socket.create_server(("127.0.0.1", 0)) as listener:

        def answer_once() -> None:
            connection, _ = listener.accept()
            with connection:
                connection.recv(_REQUEST_READ_BYTES)
                connection.sendall(head)

        thread = threading.Thread(target=answer_once, daemon=True)
        thread.start()
        yield f"http://127.0.0.1:{listener.getsockname()[1]}/file.pdf"
        thread.join(_SERVER_JOIN_SECONDS)


def _tmpdir_is_empty(path: Path) -> bool:
    return list(path.iterdir()) == []


def _path_is_gone(name: str) -> bool:
    return not Path(name).exists()


def _policy() -> FetchPolicy:
    return FetchPolicy(allowed_hosts=("127.0.0.1",), file_root=None, max_redirect_hops=10)


async def test_body_under_limit_is_written_whole(local_server: str, tmp_path: Path, monkeypatch: Any) -> None:
    # given
    monkeypatch.setenv("TMPDIR", str(tmp_path))

    # when
    result = await stream_to_file(f"{local_server}/small", 1024, policy=_policy())

    # then
    assert result is not None
    assert result.read_bytes() == _SMALL_BODY


async def test_declared_length_above_limit_is_refused_before_reading(
    local_server: str, tmp_path: Path, monkeypatch: Any
) -> None:
    # given
    monkeypatch.setenv("TMPDIR", str(tmp_path))

    # when
    with pytest.raises(DocumentTooLargeError):
        await stream_to_file(f"{local_server}/small", len(_SMALL_BODY) - 1, policy=_policy())

    # then
    assert _tmpdir_is_empty(tmp_path)


async def test_undeclared_body_passing_limit_is_stopped_and_deleted(
    local_server: str, tmp_path: Path, monkeypatch: Any
) -> None:
    # given
    monkeypatch.setenv("TMPDIR", str(tmp_path))

    # when
    with pytest.raises(DocumentTooLargeError):
        await stream_to_file(f"{local_server}/stream-big", 10, policy=_policy())

    # then
    assert _tmpdir_is_empty(tmp_path)


async def test_redirect_is_followed_to_the_file(local_server: str, tmp_path: Path, monkeypatch: Any) -> None:
    # given
    monkeypatch.setenv("TMPDIR", str(tmp_path))

    # when
    result = await stream_to_file(
        f"{local_server}/redir",
        1024,
        policy=_policy(),
        headers={"X-Test": "yes"},
        cookies={"session": "abc"},
    )

    # then
    assert result is not None
    assert result.read_bytes() == _SMALL_BODY


async def test_private_address_is_refused() -> None:
    # when
    result = await stream_to_file("http://169.254.169.254/secret", 1024, policy=_policy())

    # then
    assert result is None


async def test_transport_error_returns_no_file() -> None:
    # given
    policy = FetchPolicy(allowed_hosts=("127.0.0.1",), file_root=None, max_redirect_hops=10)

    # when
    result = await stream_to_file("http://127.0.0.1:1/closed", 1024, policy=policy)

    # then
    assert result is None


async def test_a_failed_fetch_logs_no_signature_and_only_the_exception_type(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    # given
    url = "http://127.0.0.1:1/doc.pdf?X-Amz-Signature=secret"
    policy = FetchPolicy(allowed_hosts=("127.0.0.1",), file_root=None, max_redirect_hops=10)

    def lose_connection(*_args: Any, **_kwargs: Any) -> Any:
        raise OSError(f"lost {url}")

    monkeypatch.setattr("src.fetch.byte_fetch.requests.AsyncSession", lose_connection)
    caplog.set_level(logging.WARNING, logger="src.fetch.byte_fetch")

    # when
    result = await stream_to_file(url, 1024, policy=policy)

    # then
    assert result is None
    assert "X-Amz-Signature" not in caplog.text
    assert "byte_fetch failed for URL http://127.0.0.1:1/doc.pdf: OSError" in caplog.text


async def test_a_refused_address_logs_no_signature(caplog: pytest.LogCaptureFixture) -> None:
    # given
    policy = FetchPolicy(allowed_hosts=(), file_root=None, max_redirect_hops=10)
    caplog.set_level(logging.WARNING, logger="src.fetch.byte_fetch")

    # when
    result = await stream_to_file("http://127.0.0.1:1/doc.pdf?X-Amz-Signature=secret", 1024, policy=policy)

    # then
    assert result is None
    assert "X-Amz-Signature" not in caplog.text
    assert "SSRF guard refused http://127.0.0.1:1/doc.pdf" in caplog.text


async def test_a_gzip_file_cut_short_with_a_correct_length_is_a_failure(
    local_server: str, tmp_path: Path, monkeypatch: Any
) -> None:
    # given
    monkeypatch.setenv("TMPDIR", str(tmp_path))

    # when
    result = await stream_to_file(f"{local_server}/gzip-cut", 1024 * 1024, policy=_policy())

    # then
    assert result is None
    assert _tmpdir_is_empty(tmp_path)


async def test_a_zlib_body_labelled_gzip_is_written_inflated(local_server: str) -> None:
    # when
    result = await stream_to_file(f"{local_server}/zlib-as-gzip", 1024, policy=_policy())

    # then
    assert result is not None
    assert result.read_bytes() == _SMALL_BODY
    result.unlink()


async def test_a_cancelled_download_leaves_no_partial_file_and_stays_cancelled(
    local_server: str, tmp_path: Path, monkeypatch: Any
) -> None:
    # given a download cancelled after its first bytes reached the file
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    written: list[Path] = []
    real_named = tempfile.NamedTemporaryFile

    def _recording(*args: Any, **kwargs: Any) -> Any:
        tmp = real_named(*args, **kwargs)
        written.append(Path(tmp.name))

        return tmp

    async def cancelled(_response: Any, _limit: int, write: Any, **_kwargs: Any) -> None:
        write(b"partial")

        raise asyncio.CancelledError

    # when
    with (
        patch("src.fetch.byte_fetch.drain_inflated", new=cancelled),
        patch("tempfile.NamedTemporaryFile", side_effect=_recording),
        pytest.raises(asyncio.CancelledError),
    ):
        await stream_to_file(f"{local_server}/small", 1024, policy=_policy())

    # then
    assert len(written) == 1
    assert not written[0].exists()
    assert _tmpdir_is_empty(tmp_path)


class _HopSession:
    def __init__(self, *answers: Any) -> None:
        self.curl_options: dict[Any, Any] = {}
        self._answers = list(answers)
        self.first_stopped_when_second_was_sent: bool | None = None
        self._first: Any = None

    async def __aenter__(self) -> "_HopSession":
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    async def request(self, _method: str, _url: str, **_kwargs: Any) -> Any:
        if self._first is not None:
            self.first_stopped_when_second_was_sent = self._first.quit_now.is_set()
        answer = self._answers.pop(0)
        self._first = self._first or answer

        return answer


def _hop_answer(status: int, headers: dict[str, str], body: bytes = b"") -> MagicMock:
    async def body_chunks() -> AsyncIterator[bytes]:
        yield body

    answer = MagicMock()
    answer.status_code = status
    answer.headers = Headers(headers)
    answer.quit_now = asyncio.Event()
    answer.aclose = AsyncMock()
    answer.aiter_content = body_chunks

    return answer


async def test_a_redirect_answer_is_stopped_before_the_next_hop_is_sent() -> None:
    # given
    first = _hop_answer(302, {"Location": "/landing"})
    last = _hop_answer(200, {}, _SMALL_BODY)
    session = _HopSession(first, last)

    # when
    with patch("src.fetch.byte_fetch.requests.AsyncSession", return_value=session):
        result = await stream_to_file("http://127.0.0.1:1/start", 1024, policy=_policy())

    # then the first answer was stopped undrained before the second hop, and each only once
    assert session.first_stopped_when_second_was_sent is True
    assert first.aclose.await_count == 1
    assert last.quit_now.is_set()
    assert last.aclose.await_count == 1
    assert result is not None
    assert result.read_bytes() == _SMALL_BODY
    result.unlink()


async def test_an_unreadable_content_length_is_read_within_the_cap() -> None:
    # given
    session = _HopSession(_hop_answer(200, {"Content-Length": "5, 5"}, _SMALL_BODY))

    # when
    with patch("src.fetch.byte_fetch.requests.AsyncSession", return_value=session):
        result = await stream_to_file("http://127.0.0.1:1/doc", 1024, policy=_policy())

    # then
    assert result is not None
    assert result.read_bytes() == _SMALL_BODY
    result.unlink()


async def test_write_error_deletes_partial_file(local_server: str, tmp_path: Path, monkeypatch: Any) -> None:
    # given
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    created: list[str] = []

    real_named = __import__("tempfile").NamedTemporaryFile

    def _failing(*args: Any, **kwargs: Any) -> Any:
        tmp = real_named(*args, **kwargs)
        created.append(tmp.name)

        def _boom(_data: bytes) -> int:
            raise OSError("disk is gone")

        tmp.write = _boom
        return tmp

    # when
    with patch("tempfile.NamedTemporaryFile", side_effect=_failing):
        result = await stream_to_file(f"{local_server}/small", 1024, policy=_policy())

    # then
    assert result is None
    assert len(created) == 1
    assert _path_is_gone(created[0])
    assert _tmpdir_is_empty(tmp_path)


@pytest.mark.parametrize("path", ["/missing", "/error"])
async def test_non_2xx_answer_is_never_written(
    path: str, local_server: str, tmp_path: Path, monkeypatch: Any
) -> None:
    # given
    monkeypatch.setenv("TMPDIR", str(tmp_path))

    # when
    result = await stream_to_file(f"{local_server}{path}", 1024, policy=_policy())

    # then
    assert result is None
    assert _tmpdir_is_empty(tmp_path)


async def test_temp_file_creation_failure_reports_its_own_cause(
    local_server: str, caplog: pytest.LogCaptureFixture
) -> None:
    # given
    caplog.set_level(logging.WARNING, logger="src.fetch.byte_fetch")

    # when
    with patch("tempfile.NamedTemporaryFile", side_effect=OSError("no space left on device")):
        result = await stream_to_file(f"{local_server}/small", 1024, policy=_policy())

    # then
    assert result is None
    assert any(
        "byte_fetch failed for URL" in message and message.endswith(": OSError")
        for message in (record.getMessage() for record in caplog.records)
    )


async def test_body_passing_the_cap_stops_the_transfer(
    huge_body_server: _HugeBodyServer, tmp_path: Path, monkeypatch: Any
) -> None:
    # given a 64 MiB undeclared body and a cap of 10 bytes
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    url = f"http://127.0.0.1:{huge_body_server.server_port}/huge"

    # when
    with pytest.raises(DocumentTooLargeError):
        await stream_to_file(url, 10, policy=_policy())

    # then the client aborted the download, so the server never wrote the whole body
    assert await asyncio.to_thread(huge_body_server.handler_finished.wait, 10)
    assert not huge_body_server.sent_whole_body.is_set()


async def test_a_2xx_answer_that_declares_above_the_cap_and_closes_is_refused_for_its_size(
    tmp_path: Path, monkeypatch: Any
) -> None:
    # given
    monkeypatch.setenv("TMPDIR", str(tmp_path))

    # when
    with (
        _declares_then_closes("200 OK", _ABOVE_CAP_BYTES) as url,
        pytest.raises(DocumentTooLargeError),
    ):
        await stream_to_file(url, _CAP_BYTES, policy=_policy())

    # then
    assert _tmpdir_is_empty(tmp_path)


@pytest.mark.parametrize(
    ("status_line", "declared_bytes"),
    [("503 Service Unavailable", _ABOVE_CAP_BYTES), ("200 OK", _UNDER_CAP_BYTES)],
)
async def test_a_cut_answer_that_is_not_a_2xx_above_the_cap_is_a_plain_failure(
    status_line: str, declared_bytes: int, tmp_path: Path, monkeypatch: Any
) -> None:
    # given
    monkeypatch.setenv("TMPDIR", str(tmp_path))

    # when
    with _declares_then_closes(status_line, declared_bytes) as url:
        result = await stream_to_file(url, _CAP_BYTES, policy=_policy())

    # then
    assert result is None
    assert _tmpdir_is_empty(tmp_path)


async def test_a_transport_error_without_an_answer_returns_no_file() -> None:
    # given
    failure = RequestException("no answer")

    # when
    with patch("src.fetch.byte_fetch.requests.AsyncSession.request", side_effect=failure):
        result = await stream_to_file("http://127.0.0.1:1/file.pdf", _CAP_BYTES, policy=_policy())

    # then
    assert result is None


async def test_a_gzip_file_lands_inflated(local_server: str, tmp_path: Path, monkeypatch: Any) -> None:
    # given
    monkeypatch.setenv("TMPDIR", str(tmp_path))

    # when
    result = await stream_to_file(f"{local_server}/gzip-small", _CAP_BYTES, policy=_policy())

    # then
    assert result is not None
    assert result.read_bytes() == _SMALL_BODY


async def test_a_gzip_bomb_raises_too_large_and_leaves_no_file(
    local_server: str, tmp_path: Path, monkeypatch: Any
) -> None:
    # given
    monkeypatch.setenv("TMPDIR", str(tmp_path))

    # when / then
    with pytest.raises(DocumentTooLargeError):
        await stream_to_file(f"{local_server}/gzip-bomb", _CAP_BYTES, policy=_policy())
    assert _tmpdir_is_empty(tmp_path)


async def test_an_unsupported_coding_returns_no_file(
    local_server: str, tmp_path: Path, monkeypatch: Any
) -> None:
    # given
    monkeypatch.setenv("TMPDIR", str(tmp_path))

    # when
    result = await stream_to_file(f"{local_server}/compress", _CAP_BYTES, policy=_policy())

    # then
    assert result is None
    assert _tmpdir_is_empty(tmp_path)


async def test_a_dripping_body_past_the_deadline_is_a_failed_download_with_no_file_left(
    local_server: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # given
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))

    # when
    with (
        patch("src.reader.document_router.settings.DOCUMENT_FETCH_TIMEOUT_SECONDS", _FETCH_DEADLINE_SECONDS),
        patch("src.reader.document_router.web_hunter_fetch_policy", return_value=_policy()),
    ):
        result = await _download(f"{local_server}/drip")

    # then
    assert result is None
    assert _tmpdir_is_empty(tmp_path)


def _hops_ending_with(failure: BaseException) -> Callable[..., Any]:
    @asynccontextmanager
    async def failing_hops(send_hop: Any) -> AsyncIterator[Any]:
        async with stopping_hops(send_hop) as tracked_hop:
            yield tracked_hop
        raise failure

    return failing_hops


async def test_a_cancel_after_the_body_was_written_leaves_no_file(
    local_server: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # given
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))

    # when
    with (
        patch("src.fetch.byte_fetch.stopping_hops", _hops_ending_with(asyncio.CancelledError())),
        pytest.raises(asyncio.CancelledError),
    ):
        await stream_to_file(f"{local_server}/small", _CAP_BYTES, policy=_policy())

    # then
    assert _tmpdir_is_empty(tmp_path)


async def test_a_teardown_failure_after_the_body_was_written_is_a_failed_download_with_no_file_left(
    local_server: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # given
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))

    # when
    with patch("src.fetch.byte_fetch.stopping_hops", _hops_ending_with(RuntimeError("teardown"))):
        result = await stream_to_file(f"{local_server}/small", _CAP_BYTES, policy=_policy())

    # then
    assert result is None
    assert _tmpdir_is_empty(tmp_path)

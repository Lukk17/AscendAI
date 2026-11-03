"""Task 1.4: stream_to_file against a local test server."""

import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from ascend_python_common.uri_guard import FetchPolicy

from src.fetch.byte_fetch import stream_to_file

_SMALL_BODY = b"hello"
_BIG_BODY = b"x" * 100


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args: object) -> None:
        return

    def do_GET(self) -> None:
        if self.path == "/small":
            self._send_body(_SMALL_BODY, declared=True)
        elif self.path == "/stream-big":
            self._send_body(_BIG_BODY, declared=False)
        elif self.path == "/redir":
            self.send_response(302)
            self.send_header("Location", "/small")
            self.end_headers()
        else:
            self.send_response(404)
            self.end_headers()

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
    result = await stream_to_file(f"{local_server}/small", len(_SMALL_BODY) - 1, policy=_policy())

    # then
    assert result is None
    assert _tmpdir_is_empty(tmp_path)


async def test_undeclared_body_passing_limit_is_stopped_and_deleted(
    local_server: str, tmp_path: Path, monkeypatch: Any
) -> None:
    # given
    monkeypatch.setenv("TMPDIR", str(tmp_path))

    # when
    result = await stream_to_file(f"{local_server}/stream-big", 10, policy=_policy())

    # then
    assert result is None
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

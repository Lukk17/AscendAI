"""Live-browser read through `5-crawlee_adaptive` leaves the process logging unchanged.

Real Chromium against a local test server. Crawlee configures the root logger with
its own colored handler when a crawler is built, unless the tier turns that off, so
after one real read the root, uvicorn and httpx loggers must hold what they held
before, and the crawler's own records must still reach the service's handlers.

Not part of the unit gate: excluded through `--ignore=tests/integration` in
`pyproject.toml`, run alone as `python -m pytest tests/integration -q --no-cov`.
"""

import logging
import threading
from collections.abc import Iterator
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import AsyncMock, patch

import pytest

from src.reader.strategies.crawlee_strategy import CrawleeStrategy
from src.validator.url_validator import url_validator

pytestmark = pytest.mark.filterwarnings("ignore:Implicitly cleaning up:ResourceWarning")
"""Crawlee launches persistent browser contexts in temp dirs it never closes
itself; their GC-time cleanup warning is third-party noise."""

_ARTICLE_BODY = (
    b"<html><head><title>Article</title></head><body><article><p>"
    + b"word " * 400
    + b"</p></article></body></html>"
)

_WATCHED_LOGGER_NAMES = ("uvicorn", "uvicorn.error", "uvicorn.access", "httpx")


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"

    def log_message(self, *args: object) -> None:
        pass

    def do_GET(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(_ARTICLE_BODY)))
        self.end_headers()
        self.wfile.write(_ARTICLE_BODY)


@dataclass(frozen=True)
class _LoggerState:
    handlers: tuple[logging.Handler, ...]
    formatters: tuple[logging.Formatter | None, ...]
    level: int
    propagate: bool


def _state_of(logger: logging.Logger) -> _LoggerState:
    return _LoggerState(
        handlers=tuple(logger.handlers),
        formatters=tuple(handler.formatter for handler in logger.handlers),
        level=logger.level,
        propagate=logger.propagate,
    )


def _process_logging() -> dict[str, _LoggerState]:
    states = {name: _state_of(logging.getLogger(name)) for name in _WATCHED_LOGGER_NAMES}
    states["root"] = _state_of(logging.getLogger())

    return states


class _ListHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@pytest.fixture(scope="module")
def web_server() -> Iterator[str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://localhost:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


@pytest.fixture(autouse=True)
def allow_localhost(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("src.config.config.settings.ALLOWED_PRIVATE_HOSTS", ("localhost",))
    monkeypatch.setattr("src.config.config.settings.PLAYWRIGHT_HEADLESS", True)


@pytest.fixture
def service_handler() -> Iterator[_ListHandler]:
    handler = _ListHandler()
    root = logging.getLogger()
    root.addHandler(handler)
    yield handler
    root.removeHandler(handler)


@pytest.mark.asyncio
async def test_a_real_crawlee_read_leaves_the_process_logging_unchanged(
    web_server: str, service_handler: _ListHandler
) -> None:
    # given
    before = _process_logging()

    # when
    with patch(
        "src.reader.strategies.crawlee_strategy.cookie_manager.get_storage_state",
        new=AsyncMock(return_value=None),
    ):
        html = await CrawleeStrategy(url_validator).get_html(f"{web_server}/article")

    # then
    assert "word word" in html
    assert _process_logging() == before
    assert any(record.name.startswith("crawlee") for record in service_handler.records)

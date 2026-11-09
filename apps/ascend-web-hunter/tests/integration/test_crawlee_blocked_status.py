"""Live-browser read of a 403 wall page through `5-crawlee_adaptive`.

Real Chromium against a local test server whose page answers 403 with the
`cf-mitigated: challenge` header. The tier must judge that answer itself: one
wall verdict under crawlee, the challenge exception, and one fetch of the page,
with no Crawlee session rotation or retry.

Not part of the unit gate: excluded through `--ignore=tests/integration` in
`pyproject.toml`, run alone as `python -m pytest tests/integration -q --no-cov`.
"""

import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import ClassVar
from unittest.mock import AsyncMock, patch

import pytest
from prometheus_client import REGISTRY

from src.api.exceptions import ChallengeDetectedException
from src.reader.strategies.crawlee_strategy import CrawleeStrategy
from src.validator.url_validator import url_validator

pytestmark = pytest.mark.filterwarnings("ignore:Implicitly cleaning up:ResourceWarning")
"""Crawlee launches persistent browser contexts in temp dirs it never closes
itself; their GC-time cleanup warning is third-party noise."""

_WALL_PATH = "/wall-403"

_WALL_BODY = b"<html><head><title>Checking</title></head><body><p>One moment.</p></body></html>"


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"
    requested_paths: ClassVar[list[str]] = []

    def log_message(self, *args: object) -> None:
        pass

    def do_GET(self) -> None:
        type(self).requested_paths.append(self.path)
        self.send_response(403)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(_WALL_BODY)))
        self.send_header("cf-mitigated", "challenge")
        self.end_headers()
        self.wfile.write(_WALL_BODY)


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


def _verdicts(verdict: str) -> float:
    return (
        REGISTRY.get_sample_value("challenge_verdicts_total", {"verdict": verdict, "tier": "crawlee"}) or 0.0
    )


@pytest.mark.asyncio
async def test_crawlee_read_of_a_403_wall_records_one_wall_verdict_and_fetches_once(web_server: str) -> None:
    # given
    hits_before = _Handler.requested_paths.count(_WALL_PATH)
    walls_before = _verdicts("wall")
    others_before = _verdicts("content") + _verdicts("no_content")

    # when
    with (
        patch(
            "src.reader.strategies.crawlee_strategy.cookie_manager.get_storage_state",
            new=AsyncMock(return_value=None),
        ),
        pytest.raises(ChallengeDetectedException) as exc,
    ):
        await CrawleeStrategy(url_validator).get_html(f"{web_server}{_WALL_PATH}")

    # then
    assert exc.value.verdict.wall is True
    assert "definitive_header" in {signal.id for signal in exc.value.verdict.signals}
    assert _verdicts("wall") == walls_before + 1.0
    assert _verdicts("content") + _verdicts("no_content") == others_before
    assert _Handler.requested_paths.count(_WALL_PATH) - hits_before == 1

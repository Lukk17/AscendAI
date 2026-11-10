"""Live reads of a page that redirects anonymous visitors to a login page.

Real Chromium through the pinned tunnel and the real curl_cffi fetch against a local test server shaped
like the old.reddit.com subreddit read measured on 2026-11-07: the article
address answers 302 to a login path, and the login page answers 200 with a
title and markup that carry no login wording. Both tiers must raise a login
wall, and an article that only links to the login page must stay content.

Not part of the unit gate: excluded through `--ignore=tests/integration` in
`pyproject.toml`, run alone as `python -m pytest tests/integration -q --no-cov`.
"""

import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import AsyncMock, patch

import pytest

from src.api.exceptions import ChallengeDetectedException
from src.reader.strategies.curl_cffi_fetcher import fetch_with_curl_cffi
from src.reader.strategies.playwright_strategy import PlaywrightStrategy
from src.validator.url_validator import url_validator

_UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"

_ARTICLE_PATH = "/r/programming/"
_LOGIN_PATH = "/login/?reason=lor2&dest=%2Fr%2Fprogramming%2F"
_LINKING_ARTICLE_PATH = "/news/release"

_WELCOME_PAGE = (
    b"<html><head><title>Welcome to Example</title></head><body><main>"
    b"<example-auth-flow><p>To keep Example safe, accounts are required to read this community."
    b" Continue with your account.</p></example-auth-flow></main></body></html>"
)

_LINKING_ARTICLE = (
    b'<html><head><title>Release notes</title></head><body><header><a href="/login/?dest=%2Fnews">'
    b"Log in</a></header><main><article><h1>Release notes</h1><p>"
    + b"The release adds faster reads and fixes the export of long reports. " * 30
    + b"</p></article></main></body></html>"
)


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"

    def log_message(self, *args: object) -> None:
        pass

    def do_GET(self) -> None:
        if self.path == _ARTICLE_PATH:
            self.send_response(302)
            self.send_header("Location", _LOGIN_PATH)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        body = _LINKING_ARTICLE if self.path == _LINKING_ARTICLE_PATH else _WELCOME_PAGE
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture(scope="module")
def web_server() -> Iterator[str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://localhost:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


@pytest.fixture(autouse=True)
def allow_localhost(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr("src.config.config.settings.ALLOWED_PRIVATE_HOSTS", ("localhost",))
    monkeypatch.setattr("src.config.config.settings.PLAYWRIGHT_HEADLESS", True)
    with (
        patch(
            "src.reader.strategies.playwright_strategy.cookie_manager.get_storage_state",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "src.reader.strategies.playwright_strategy.cookie_manager.get_user_agent",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "src.reader.strategies.curl_cffi_fetcher.cookie_manager.get_flat_cookies",
            new=AsyncMock(return_value={}),
        ),
        patch(
            "src.reader.strategies.curl_cffi_fetcher.cookie_manager.get_user_agent",
            new=AsyncMock(return_value=None),
        ),
    ):
        yield


@pytest.mark.asyncio
async def test_browser_read_redirected_to_a_login_page_raises_a_login_wall(web_server: str) -> None:
    # when
    with pytest.raises(ChallengeDetectedException) as raised:
        await PlaywrightStrategy(lambda: _UA, url_validator).get_html(f"{web_server}{_ARTICLE_PATH}")

    # then
    assert raised.value.verdict.intervention_type == "login"


@pytest.mark.asyncio
async def test_static_read_redirected_to_a_login_page_raises_a_login_wall(web_server: str) -> None:
    # when
    with pytest.raises(ChallengeDetectedException) as raised:
        await fetch_with_curl_cffi(f"{web_server}{_ARTICLE_PATH}", lambda: _UA, "test")

    # then
    assert raised.value.verdict.intervention_type == "login"


@pytest.mark.asyncio
async def test_browser_read_of_an_article_that_links_to_the_login_page_is_content(web_server: str) -> None:
    # when
    html = await PlaywrightStrategy(lambda: _UA, url_validator).get_html(
        f"{web_server}{_LINKING_ARTICLE_PATH}"
    )

    # then
    assert "Release notes" in html

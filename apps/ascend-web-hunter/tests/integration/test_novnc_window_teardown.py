"""Closing a NoVNC window leaves no orphaned Playwright work behind, in a real Chromium.

`site.test` on 127.0.0.2 stands for a public host: the guard's own lookup answers it
and the page reaches it only through the pinned tunnel.

Not part of the unit gate: excluded through `--ignore=tests/integration` in
`pyproject.toml`, run alone as `python -m pytest tests/integration -q --no-cov`.
"""

import asyncio
import gc
import socket
import threading
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from unittest.mock import AsyncMock

import pytest
from patchright.async_api import async_playwright as patchright_playwright
from playwright.async_api import Page, async_playwright

from src.config.config import settings
from src.reader.browser_guard import BrowserFamily, browser_tunnel, chromium_guard_args, install_browser_guard
from src.reader.cloudflare.cookie_manager import cookie_manager
from src.reader.novnc.flow_registry import NoVNCFlow, flow_key_for, novnc_flow_registry
from src.reader.novnc.window_layout import rect_for_slot
from src.reader.strategies import novnc_strategy
from src.reader.strategies.browser_read import _HTML_LENGTH_SCRIPT
from src.reader.strategies.novnc_strategy import _monitor_for_cookies
from src.validator.url_validator import url_validator
from tests.reader.novnc.test_flow_registry import FakeRedis

pytestmark = pytest.mark.filterwarnings("ignore:Implicitly cleaning up:ResourceWarning")

_HOST = "site.test"
_ADDRESS = "127.0.0.2"
_SLOW_ANSWER_TIMEOUT_SECONDS = 10
_POLL_STEP_SECONDS = 0.05
_CALL_REACHES_THE_BROWSER_SECONDS = 0.3
_ROUTE_SETTLE_TIMEOUT_SECONDS = 5.0
_LONGEST_WINDOW_CLOSE_SECONDS = 8.0
_BUSY_PAGE = b"<html><body><script>while (true) {}</script></body></html>"
_SLOW_SCRIPT_PAGE = b"<html><body><script src='/slow.js'></script></body></html>"


class _NetworkRedis(FakeRedis):
    """Yields to the loop on a write, as the real client does on its socket."""

    async def set(self, *args: Any, **kwargs: Any) -> Any:
        await asyncio.sleep(_POLL_STEP_SECONDS)

        return await super().set(*args, **kwargs)


@dataclass
class _Site:
    port: int = 0
    slow_requested: threading.Event = field(default_factory=threading.Event)
    release_slow: threading.Event = field(default_factory=threading.Event)

    def url(self, path: str) -> str:
        return f"http://{_HOST}:{self.port}{path}"


def _handler(site: _Site) -> type[BaseHTTPRequestHandler]:
    class _Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args: object) -> None:
            pass

        def _send(self, body: bytes, content_type: str) -> None:
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            match self.path:
                case "/busy":
                    self._send(_BUSY_PAGE, "text/html")
                case "/slow.js":
                    site.slow_requested.set()
                    site.release_slow.wait(_SLOW_ANSWER_TIMEOUT_SECONDS)
                    self._send(b"var done = true;", "text/javascript")
                case _:
                    self._send(_SLOW_SCRIPT_PAGE, "text/html")

    return _Handler


@pytest.fixture
def site(monkeypatch: pytest.MonkeyPatch) -> Iterator[_Site]:
    from ascend_python_common import uri_guard

    answers = _Site()
    server = ThreadingHTTPServer((_ADDRESS, 0), _handler(answers))
    answers.port = server.server_address[1]
    real_lookup = uri_guard._lookup
    real_is_blocked = uri_guard._is_blocked

    async def _lookup(host: str, port: int) -> Any:
        if host == _HOST:
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (_ADDRESS, port))]

        return await real_lookup(host, port)

    def _is_blocked(address: Any) -> bool:
        return str(address) != _ADDRESS and real_is_blocked(address)

    monkeypatch.setattr("src.config.config.settings.ALLOWED_PRIVATE_HOSTS", ())
    monkeypatch.setattr(uri_guard, "_lookup", _lookup)
    monkeypatch.setattr(uri_guard, "_is_blocked", _is_blocked)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield answers
    answers.release_slow.set()
    server.shutdown()
    server.server_close()


@pytest.fixture
async def loop_errors() -> AsyncIterator[list[str]]:
    """What the event loop reported to its exception handler, as messages."""
    errors: list[str] = []
    loop = asyncio.get_running_loop()
    loop.set_exception_handler(lambda _loop, context: errors.append(str(context["message"])))
    yield errors
    loop.set_exception_handler(None)


def _flow(url: str) -> NoVNCFlow:
    window = rect_for_slot(
        0,
        settings.NOVNC_DISPLAY_SIZE,
        (settings.NOVNC_WINDOW_WIDTH_PX, settings.NOVNC_WINDOW_HEIGHT_PX),
        settings.NOVNC_WINDOW_CASCADE_OFFSET_PX,
    )

    return NoVNCFlow(
        flow_id="a7b8c9d0e1f2",
        key=flow_key_for(url, "default"),
        url=url,
        profile="default",
        intervention_type="captcha",
        window=window,
        vnc_url="http://vnc/vnc.html?autoconnect=true",
        started_at=time.time(),
        request_id="test-request",
        lease_started=time.monotonic(),
    )


class _HeadlessChromium:
    def __init__(self, chromium: Any) -> None:
        self._chromium = chromium

    async def launch(self, **options: Any) -> Any:
        return await self._chromium.launch(**{**options, "headless": True})


@asynccontextmanager
async def _headless_playwright() -> AsyncIterator[Any]:
    async with async_playwright() as playwright:
        driver = type("_Driver", (), {"chromium": _HeadlessChromium(playwright.chromium)})
        yield driver()


def _tasks_running(coroutine_name: str) -> list[asyncio.Task[Any]]:
    return [task for task in asyncio.all_tasks() if coroutine_name in repr(task.get_coro())]


async def _wait_for_route_tasks_to_end() -> list[asyncio.Task[Any]]:
    routes = _tasks_running("_on_route")
    if routes:
        await asyncio.wait(routes, timeout=_ROUTE_SETTLE_TIMEOUT_SECONDS)

    return _tasks_running("_on_route")


async def _collected_errors(errors: list[str]) -> list[str]:
    await asyncio.sleep(_POLL_STEP_SECONDS)
    gc.collect()

    return errors


async def _wait_for(event: threading.Event) -> None:
    assert await asyncio.to_thread(event.wait, _SLOW_ANSWER_TIMEOUT_SECONDS)


def _isolate_monitor(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(novnc_flow_registry, "_redis", _NetworkRedis())
    monkeypatch.setattr(novnc_strategy, "async_playwright", _headless_playwright)
    monkeypatch.setattr(cookie_manager, "get_storage_state", AsyncMock(return_value=None))
    monkeypatch.setattr(cookie_manager, "has_valid_login", AsyncMock(return_value=False))


def _signal_when_the_page_is_measured(monkeypatch: pytest.MonkeyPatch) -> asyncio.Event:
    measured = asyncio.Event()
    real_evaluate = Page.evaluate

    async def _evaluate(page: Page, expression: str, arg: Any = None) -> Any:
        if expression == _HTML_LENGTH_SCRIPT:
            measured.set()

        return await real_evaluate(page, expression, arg)

    monkeypatch.setattr(Page, "evaluate", _evaluate)

    return measured


async def test_closing_a_window_with_a_poll_in_flight_leaves_no_failed_future_behind(
    site: _Site, loop_errors: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    # given a window whose page never answers, so the poll's size check of the page stays open
    measured = _signal_when_the_page_is_measured(monkeypatch)
    flow = _flow(site.url("/busy"))
    _isolate_monitor(monkeypatch)
    task = asyncio.create_task(_monitor_for_cookies(flow))
    await asyncio.wait_for(measured.wait(), timeout=_SLOW_ANSWER_TIMEOUT_SECONDS)
    await asyncio.sleep(_CALL_REACHES_THE_BROWSER_SECONDS)
    closing_from = time.monotonic()

    # when
    task.cancel()
    await asyncio.wait({task})
    closed_after = time.monotonic() - closing_from
    del task

    # then
    assert await _collected_errors(loop_errors) == []
    assert closed_after < _LONGEST_WINDOW_CLOSE_SECONDS


async def test_closing_a_window_while_the_driver_starts_stops_the_driver(
    site: _Site, monkeypatch: pytest.MonkeyPatch
) -> None:
    # given
    _isolate_monitor(monkeypatch)
    task = asyncio.create_task(_monitor_for_cookies(_flow(site.url("/busy"))))
    await asyncio.sleep(_POLL_STEP_SECONDS)

    # when
    task.cancel()
    await asyncio.wait({task})

    # then
    assert _tasks_running("Connection.run") == []


async def test_a_closed_window_leaves_no_tunnel_connection_open(
    site: _Site, monkeypatch: pytest.MonkeyPatch
) -> None:
    # given a window that has fetched its page through the tunnel
    measured = _signal_when_the_page_is_measured(monkeypatch)
    _isolate_monitor(monkeypatch)
    task = asyncio.create_task(_monitor_for_cookies(_flow(site.url("/busy"))))
    await asyncio.wait_for(measured.wait(), timeout=_SLOW_ANSWER_TIMEOUT_SECONDS)

    # when
    task.cancel()
    await asyncio.wait({task})
    await _wait_for_no_tunnel_connection()

    # then
    assert browser_tunnel._connections == set()


async def _wait_for_no_tunnel_connection() -> None:
    if browser_tunnel._connections:
        await asyncio.wait(browser_tunnel._connections, timeout=_ROUTE_SETTLE_TIMEOUT_SECONDS)


async def _close_browser(_playwright: Any, browser: Any) -> None:
    await browser.close()


async def _stop_driver(playwright: Any, _browser: Any) -> None:
    await playwright.stop()


@pytest.mark.parametrize("close", [_close_browser, _stop_driver], ids=["browser-closed", "driver-stopped"])
async def test_a_route_still_fetching_when_its_browser_goes_ends_without_a_warning(
    site: _Site,
    loop_errors: list[str],
    close: Callable[[Any, Any], Awaitable[None]],
    caplog: pytest.LogCaptureFixture,
) -> None:
    # given a page waiting for a script whose answer the site holds back
    playwright = await async_playwright().start()
    browser = await playwright.chromium.launch(headless=True, args=list(chromium_guard_args()))
    context = await browser.new_context(service_workers="block")
    await install_browser_guard(context, url_validator, family=BrowserFamily.CHROMIUM)
    page = await context.new_page()
    navigation = asyncio.create_task(page.goto(site.url("/page"), wait_until="load"))
    await _wait_for(site.slow_requested)

    # when
    with caplog.at_level("WARNING", logger="src.reader.browser_guard"):
        await close(playwright, browser)
        site.release_slow.set()
        pending_routes = await _wait_for_route_tasks_to_end()
    await asyncio.gather(navigation, return_exceptions=True)
    await playwright.stop()

    # then
    assert pending_routes == []
    assert caplog.records == []
    assert await _collected_errors(loop_errors) == []


async def test_a_patchright_novnc_window_reaches_the_site_through_the_tunnel(
    site: _Site, monkeypatch: pytest.MonkeyPatch
) -> None:
    # given the driver the window really starts, kept headless for the test run
    launched: list[list[str]] = []
    assert vars(novnc_strategy)["async_playwright"] is patchright_playwright

    class _HeadlessPatchright:
        def __init__(self, chromium: Any) -> None:
            self._chromium = chromium

        async def launch(self, **options: Any) -> Any:
            launched.append(list(options["args"]))

            return await self._chromium.launch(**{**options, "headless": True})

    class _Manager:
        def __init__(self) -> None:
            self._manager = patchright_playwright()

        async def __aenter__(self) -> Any:
            driver = await self._manager.__aenter__()

            return type("_Driver", (), {"chromium": _HeadlessPatchright(driver.chromium)})()

        async def __aexit__(self, *details: object) -> None:
            await self._manager.__aexit__(*details)

    _isolate_monitor(monkeypatch)
    monkeypatch.setattr(novnc_strategy, "async_playwright", _Manager)
    task = asyncio.create_task(_monitor_for_cookies(_flow(site.url("/page"))))

    # when
    await _wait_for(site.slow_requested)
    connections_while_open = len(browser_tunnel._connections)
    task.cancel()
    await asyncio.wait({task})

    # then
    assert any(arg == f"--proxy-server=http://127.0.0.1:{browser_tunnel.port}" for arg in launched[0])
    assert connections_while_open >= 1

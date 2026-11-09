"""A NoVNC poll opens no helper tab in a real Chromium, whatever cross-origin frames the window holds.

Not part of the unit gate: excluded through `--ignore=tests/integration` in
`pyproject.toml`, run alone as `python -m pytest tests/integration -q --no-cov`.
"""

import asyncio
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

import pytest
from playwright.async_api import async_playwright

from src.config.config import settings
from src.reader.novnc.flow_registry import NoVNCFlow, flow_key_for
from src.reader.novnc.window_layout import rect_for_slot
from src.reader.strategies.main_frame_response import MainFrameResponses
from src.reader.strategies.novnc_strategy import _FlowProgress, _poll_once

_POLLS = 3
_SITE = "shop-site.com"
_MAIN_URL = "https://www.shop-site.com/account"
_AUTH_ORIGIN = "https://auth.shop-site.com"
_EVENT_SETTLE_SECONDS = 0.2
_FRAMES = (
    "<iframe src='https://captcha-widget.net/challenge'></iframe>"
    f"<iframe src='{_AUTH_ORIGIN}/widget'></iframe>"
    f"<iframe sandbox='allow-scripts' src='{_AUTH_ORIGIN}/sandboxed'></iframe>"
)
_LOGIN_PAGE = (
    "<html><head><title>Shop</title></head><body><form action='/session' method='post'>"
    "<input type='text' name='user'><input type='password' name='password'>"
    f"<button type='submit'>Go</button></form>{_FRAMES}</body></html>"
)
_FRAME_PAGE = "<html><body><script>localStorage.setItem('seen', 'yes')</script>frame</body></html>"


def _flow(intervention_type: str) -> NoVNCFlow:
    window = rect_for_slot(
        0,
        settings.NOVNC_DISPLAY_SIZE,
        (settings.NOVNC_WINDOW_WIDTH_PX, settings.NOVNC_WINDOW_HEIGHT_PX),
        settings.NOVNC_WINDOW_CASCADE_OFFSET_PX,
    )

    return NoVNCFlow(
        flow_id="f6a7b8c9d0e1",
        key=flow_key_for(_MAIN_URL, "default"),
        url=_MAIN_URL,
        profile="default",
        intervention_type=intervention_type,
        window=window,
        vnc_url="http://vnc/vnc.html?autoconnect=true",
        started_at=time.time(),
        request_id="test-request",
        lease_started=time.monotonic(),
    )


@dataclass
class _Window:
    page: Any
    context: Any
    responses: MainFrameResponses
    created_pages: list[str] = field(default_factory=list)


def _fulfil(challenge: bool) -> Any:
    async def handle(route: Any) -> None:
        url = route.request.url
        if url == _MAIN_URL and challenge:
            await route.fulfill(
                status=403,
                headers={"cf-mitigated": "challenge", "content-type": "text/html"},
                body=f"<html><body>Checking your browser{_FRAMES}</body></html>",
            )
        elif url == _MAIN_URL:
            await route.fulfill(status=200, content_type="text/html", body=_LOGIN_PAGE)
        else:
            await route.fulfill(status=200, content_type="text/html", body=_FRAME_PAGE)

    return handle


@pytest.fixture
async def open_window() -> AsyncIterator[Any]:
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)

        async def build(*, challenge: bool) -> _Window:
            context = await browser.new_context()
            await context.route("**/*", _fulfil(challenge))
            page = await context.new_page()
            responses = MainFrameResponses(page)
            await page.goto(_MAIN_URL, wait_until="load")
            window = _Window(page, context, responses)
            cdp = await browser.new_browser_cdp_session()

            def record(event: dict[str, Any]) -> None:
                if event["targetInfo"]["type"] == "page":
                    window.created_pages.append(event["targetInfo"]["url"])

            cdp.on("Target.targetCreated", record)
            await cdp.send("Target.setDiscoverTargets", {"discover": True})
            await asyncio.sleep(_EVENT_SETTLE_SECONDS)
            window.created_pages.clear()

            return window

        try:
            yield build
        finally:
            await browser.close()


async def _polled(window: _Window, flow: NoVNCFlow, progress: _FlowProgress, polls: int) -> list[Any]:
    results = [
        await _poll_once(window.page, window.responses, window.context, flow, progress) for _ in range(polls)
    ]
    await asyncio.sleep(_EVENT_SETTLE_SECONDS)

    return results


async def test_a_captcha_window_with_a_cross_origin_frame_opens_no_page_target(open_window: Any) -> None:
    # given
    window = await open_window(challenge=True)

    # when
    results = await _polled(window, _flow("captcha"), _FlowProgress(site=_SITE), _POLLS)

    # then
    assert results == [(None, True)] * _POLLS
    assert window.created_pages == []


async def test_later_polls_of_a_login_window_open_no_page_target_and_read_a_live_site_frame(
    open_window: Any,
) -> None:
    # given
    window = await open_window(challenge=False)
    flow = _flow("login")
    progress = _FlowProgress(site=_SITE)
    await _polled(window, flow, progress, 1)
    window.created_pages.clear()
    auth_frame = next(frame for frame in window.page.frames if frame.url == f"{_AUTH_ORIGIN}/widget")

    # when
    await auth_frame.evaluate("localStorage.setItem('auth_token', 'signed-in')")
    results = await _polled(window, flow, progress, _POLLS)

    # then
    assert results == [(None, True)] * _POLLS
    assert window.created_pages == []
    assert {"name": "auth_token", "value": "signed-in"} in progress.site_storage[_AUTH_ORIGIN]

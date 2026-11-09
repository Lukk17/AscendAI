"""Tests for the guarded browser route handler."""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

import pytest
from ascend_python_common.uri_guard import FetchTarget, UnsafeUriError
from patchright._impl._errors import TargetClosedError as PatchrightTargetClosedError
from playwright._impl._errors import TargetClosedError as PlaywrightTargetClosedError
from playwright.async_api import Error as PlaywrightError

from src.reader import browser_guard
from src.reader.browser_guard import (
    BrowserFamily,
    browser_tunnel,
    chromium_guard_args,
    firefox_guard_prefs,
    guard_page_goto,
    guarded_goto,
    handle_guarded_route,
    handle_guarded_web_socket,
    headers_without_cache_directives,
    install_browser_guard,
    web_hunter_fetch_policy,
)

_CHECK = "src.reader.browser_guard.check_fetch_uri"
_TUNNEL_PORT = 41234


def _make_validator(blocked: bool = False) -> MagicMock:
    validator = MagicMock()
    validator.should_block = MagicMock(return_value=blocked)

    return validator


def _make_context() -> MagicMock:
    context = MagicMock()
    context.route = AsyncMock()
    context.route_web_socket = AsyncMock()
    context.add_init_script = AsyncMock()

    return context


_NO_FRAME_YET = "Frame for this navigation request is not available"


def _make_route(
    url: str,
    *,
    navigation: bool = False,
    sub_frame: bool = False,
    popup: bool = False,
    frame_exists: bool = True,
) -> MagicMock:
    request = MagicMock()
    request.url = url
    request.is_navigation_request = MagicMock(return_value=navigation)
    request.frame = MagicMock()
    request.frame.parent_frame = MagicMock() if sub_frame else None
    if not (sub_frame or popup):
        browser_guard._read_frames.add(request.frame)
    if not frame_exists:
        type(request).frame = PropertyMock(side_effect=PlaywrightError(_NO_FRAME_YET))
    route = MagicMock()
    route.request = request
    route.abort = AsyncMock()
    route.continue_ = AsyncMock()
    route.fallback = AsyncMock()

    return route


def _make_websocket(url: str) -> MagicMock:
    websocket = MagicMock()
    websocket.url = url
    websocket.close = AsyncMock()
    websocket.connect_to_server = MagicMock()

    return websocket


@contextmanager
def _checked(check: AsyncMock) -> Iterator[AsyncMock]:
    with patch(_CHECK, new=check):
        yield check


def _passing_check() -> AsyncMock:
    async def _check(url: str, policy: object) -> FetchTarget:
        return FetchTarget(url=url, host="example.com", port=443, addresses=("93.184.216.34",))

    return AsyncMock(side_effect=_check)


async def _route(
    route: MagicMock,
    *,
    refused: list[str] | None = None,
    validator: MagicMock | None = None,
    family: BrowserFamily = BrowserFamily.CHROMIUM,
) -> None:
    await handle_guarded_route(route, validator or _make_validator(), refused, family=family)


def test_cache_headers_are_left_out_whatever_their_case() -> None:
    # given
    headers = {"Pragma": "no-cache", "cache-control": "no-cache", "accept": "text/html", "cookie": "a=b"}

    # when
    forwarded = headers_without_cache_directives(headers)

    # then
    assert forwarded == {"accept": "text/html", "cookie": "a=b"}
    assert len(headers) == 4


async def test_a_chromium_navigation_continues_with_its_own_headers_minus_the_cache_headers() -> None:
    # given
    route = _make_route("https://example.com/page", navigation=True)
    route.request.headers = {"pragma": "no-cache", "cache-control": "no-cache", "accept": "text/html"}

    # when
    with _checked(_passing_check()):
        await _route(route)

    # then
    route.continue_.assert_awaited_once_with(headers={"accept": "text/html"})


async def test_a_chromium_subresource_continues_untouched_so_its_headers_never_follow_a_redirect() -> None:
    # given
    route = _make_route("https://example.com/api", navigation=False)
    route.request.headers = {"authorization": "Bearer t", "accept": "*/*"}

    # when
    with _checked(_passing_check()):
        await _route(route)

    # then
    route.continue_.assert_awaited_once_with()


async def test_a_firefox_navigation_continues_untouched_so_its_cookies_never_follow_a_redirect() -> None:
    # given
    route = _make_route("https://example.com/page", navigation=True)
    route.request.headers = {"cookie": "a=b", "host": "example.com"}

    # when
    with _checked(_passing_check()):
        await _route(route, family=BrowserFamily.FIREFOX)

    # then
    route.continue_.assert_awaited_once_with()


async def test_allowed_request_is_continued_so_the_browser_makes_its_own_connection() -> None:
    # given
    route = _make_route("https://example.com/page")

    # when
    with _checked(_passing_check()) as check:
        await _route(route)

    # then
    route.continue_.assert_awaited_once_with()
    route.abort.assert_not_awaited()
    assert check.await_args is not None
    assert check.await_args.args[0] == "https://example.com/page"


async def test_private_url_is_aborted_and_never_continued() -> None:
    # given
    route = _make_route("http://169.254.169.254/latest/meta-data")

    # when
    await _route(route)

    # then
    route.abort.assert_awaited_once_with("blockedbyclient")
    route.continue_.assert_not_awaited()


async def test_guard_log_lines_carry_no_query(caplog: pytest.LogCaptureFixture) -> None:
    # given
    route = _make_route("http://169.254.169.254/?token=secret")

    # when
    with caplog.at_level("WARNING", logger="src.reader.browser_guard"):
        await _route(route)

    # then
    assert "http://169.254.169.254/" in caplog.text
    assert "token=secret" not in caplog.text


async def test_blocklisted_url_is_aborted() -> None:
    # given
    route = _make_route("https://example.com/ads/banner.js")

    # when
    await _route(route, validator=_make_validator(blocked=True))

    # then
    route.abort.assert_awaited_once_with()
    route.continue_.assert_not_awaited()


async def test_blocklisted_navigation_raises() -> None:
    # given
    route = _make_route("https://example.com/ads/page", navigation=True)

    # when / then
    with pytest.raises(UnsafeUriError):
        await _route(route, validator=_make_validator(blocked=True))

    route.abort.assert_awaited_once_with()


async def test_blocklisted_navigation_is_recorded_when_list_given() -> None:
    # given
    route = _make_route("https://example.com/ads/page", navigation=True)
    refused: list[str] = []

    # when
    await _route(route, refused=refused, validator=_make_validator(blocked=True))

    # then
    assert refused == ["https://example.com/ads/page"]
    route.abort.assert_awaited_once_with()


@pytest.mark.parametrize(
    "url", ["data:text/html,hello", "blob:https://example.com/550e8400-e29b-41d4-a716-446655440000"]
)
async def test_local_scheme_is_continued_without_a_check(url: str) -> None:
    # given
    route = _make_route(url)

    # when
    with _checked(_passing_check()) as check:
        await _route(route)

    # then
    route.continue_.assert_awaited_once_with()
    route.abort.assert_not_awaited()
    check.assert_not_awaited()


async def test_ftp_url_is_refused() -> None:
    # given
    route = _make_route("ftp://example.com/file.txt")

    # when
    await _route(route)

    # then
    route.abort.assert_awaited_once_with("blockedbyclient")
    route.continue_.assert_not_awaited()


async def test_refused_main_navigation_raises() -> None:
    # given
    route = _make_route("http://169.254.169.254/", navigation=True)

    # when / then
    with pytest.raises(UnsafeUriError):
        await _route(route)

    route.abort.assert_awaited_once_with("blockedbyclient")


async def test_refused_navigation_is_recorded_when_list_given() -> None:
    # given
    route = _make_route("http://169.254.169.254/", navigation=True)
    refused: list[str] = []

    # when
    await _route(route, refused=refused)

    # then
    assert refused == ["http://169.254.169.254/"]
    route.abort.assert_awaited_once_with("blockedbyclient")


@pytest.mark.parametrize("refused", [None, []], ids=["no list", "list"])
async def test_refused_sub_frame_navigation_is_aborted_and_not_recorded(refused: list[str] | None) -> None:
    # given
    route = _make_route("http://169.254.169.254/", navigation=True, sub_frame=True)

    # when
    await _route(route, refused=refused)

    # then
    route.abort.assert_awaited_once_with("blockedbyclient")
    assert not refused


@pytest.mark.parametrize("refused", [None, []], ids=["no list", "list"])
async def test_refused_popup_navigation_is_aborted_and_not_recorded(refused: list[str] | None) -> None:
    # given
    route = _make_route("http://169.254.169.254/", navigation=True, popup=True)

    # when
    await _route(route, refused=refused)

    # then
    route.abort.assert_awaited_once_with("blockedbyclient")
    assert not refused


async def test_blocklisted_popup_navigation_is_aborted_and_not_recorded() -> None:
    # given
    route = _make_route("https://example.com/ads/page", navigation=True, popup=True)
    refused: list[str] = []

    # when
    await _route(route, refused=refused, validator=_make_validator(blocked=True))

    # then
    route.abort.assert_awaited_once_with()
    assert refused == []


async def test_refused_first_navigation_of_a_popup_without_a_frame_is_aborted_and_not_recorded() -> None:
    # given
    route = _make_route("http://169.254.169.254/", navigation=True, popup=True, frame_exists=False)
    refused: list[str] = []

    # when
    await _route(route, refused=refused)

    # then
    route.abort.assert_awaited_once_with("blockedbyclient")
    assert refused == []


async def test_blocklisted_sub_frame_navigation_is_aborted_and_not_recorded() -> None:
    # given
    route = _make_route("https://example.com/ads/page", navigation=True, sub_frame=True)
    refused: list[str] = []

    # when
    await _route(route, refused=refused, validator=_make_validator(blocked=True))

    # then
    route.abort.assert_awaited_once_with()
    assert refused == []


async def test_sub_frame_navigation_with_an_unsupported_scheme_is_aborted_and_not_recorded() -> None:
    # given
    route = _make_route("ftp://example.com/page", navigation=True, sub_frame=True)
    refused: list[str] = []

    # when
    await _route(route, refused=refused)

    # then
    route.abort.assert_awaited_once_with("blockedbyclient")
    assert refused == []


async def test_refused_request_without_a_frame_is_aborted_and_not_recorded() -> None:
    # given
    route = _make_route("http://169.254.169.254/worker.js", frame_exists=False)
    route.request.is_navigation_request = MagicMock(return_value=True)
    refused: list[str] = []

    # when
    await _route(route, refused=refused)

    # then
    route.abort.assert_awaited_once_with("blockedbyclient")
    assert refused == []


async def _installed_handler(context: MagicMock | None = None) -> Any:
    target = context or _make_context()
    await install_browser_guard(target, _make_validator(), family=BrowserFamily.CHROMIUM)

    return target.route.await_args.args[1]


@pytest.mark.parametrize("closed", [PlaywrightTargetClosedError(), PatchrightTargetClosedError()])
async def test_a_route_whose_page_closed_is_handed_back_and_logs_no_warning(
    closed: Exception, caplog: pytest.LogCaptureFixture
) -> None:
    # given
    route = _make_route("https://example.com/api.js")
    route.continue_ = AsyncMock(side_effect=closed)
    route.abort = AsyncMock(side_effect=closed)
    handler = await _installed_handler()

    # when
    with _checked(_passing_check()), caplog.at_level("WARNING", logger="src.reader.browser_guard"):
        await handler(route)

    # then
    route.fallback.assert_awaited_once_with()
    assert caplog.records == []


async def test_a_failed_abort_on_a_live_page_does_not_hand_the_route_back() -> None:
    # given
    route = _make_route("https://example.com/")
    route.continue_ = AsyncMock(side_effect=PlaywrightError("Route is already handled!"))
    route.abort = AsyncMock(side_effect=PlaywrightError("Route is already handled!"))
    handler = await _installed_handler()

    # when
    with _checked(_passing_check()):
        await handler(route)

    # then
    route.abort.assert_awaited_once_with("failed")
    route.fallback.assert_not_awaited()


async def test_a_failure_while_handling_a_route_is_a_warning_without_a_query(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # given
    route = _make_route("https://example.com/page?token=secret")
    route.continue_ = AsyncMock(side_effect=RuntimeError("boom at https://example.com/page?token=secret"))
    handler = await _installed_handler()

    # when
    with _checked(_passing_check()), caplog.at_level("WARNING", logger="src.reader.browser_guard"):
        await handler(route)

    # then
    assert "browser_guard: handling https://example.com/page failed" in caplog.text
    assert "token=secret" not in caplog.text
    route.abort.assert_awaited_once_with("failed")


@pytest.mark.parametrize(
    "url", ["wss://example.com/socket", "ws://169.254.169.254/socket", "https://example.com/socket"]
)
async def test_every_websocket_is_closed_before_the_browser_connects(
    url: str, caplog: pytest.LogCaptureFixture
) -> None:
    # given
    websocket = _make_websocket(url)

    # when
    with caplog.at_level("WARNING", logger="src.reader.browser_guard"):
        await handle_guarded_web_socket(websocket, _make_validator())

    # then
    websocket.close.assert_awaited_once_with()
    websocket.connect_to_server.assert_not_called()
    assert [url in record.getMessage() for record in caplog.records] == [True]


async def test_a_closed_websocket_logs_no_query(caplog: pytest.LogCaptureFixture) -> None:
    # given
    websocket = _make_websocket("wss://example.com/socket?token=secret")

    # when
    with caplog.at_level("WARNING", logger="src.reader.browser_guard"):
        await handle_guarded_web_socket(websocket, _make_validator())

    # then
    assert "wss://example.com/socket" in caplog.text
    assert "token=secret" not in caplog.text


async def test_blocklisted_websocket_is_closed_without_a_warning(caplog: pytest.LogCaptureFixture) -> None:
    # given
    websocket = _make_websocket("wss://example.com/ads/socket")

    # when
    with caplog.at_level("WARNING", logger="src.reader.browser_guard"):
        await handle_guarded_web_socket(websocket, _make_validator(blocked=True))

    # then
    websocket.close.assert_awaited_once_with()
    websocket.connect_to_server.assert_not_called()
    assert caplog.records == []


async def test_install_routes_every_request_through_the_handler() -> None:
    # given
    context = _make_context()
    route = _make_route("https://example.com/")

    # when
    with _checked(_passing_check()):
        await install_browser_guard(context, _make_validator(), family=BrowserFamily.CHROMIUM)
        route_handler = context.route.call_args.args[1]
        await route_handler(route)

    # then
    assert context.route.call_args.args[0] == "**/*"
    route.continue_.assert_awaited_once_with()


async def test_install_wires_the_websocket_handler_for_chromium() -> None:
    # given
    context = _make_context()
    websocket = _make_websocket("wss://example.com/socket")

    # when
    await install_browser_guard(context, _make_validator(), family=BrowserFamily.CHROMIUM)
    websocket_handler = context.route_web_socket.call_args.args[1]
    await websocket_handler(websocket)

    # then
    assert context.route_web_socket.call_args.args[0] == "**/*"
    websocket.close.assert_awaited_once_with()
    context.add_init_script.assert_not_awaited()


async def test_install_without_websocket_routing_skips_it() -> None:
    # given
    context = _make_context()
    del context.route_web_socket

    # when
    await install_browser_guard(context, _make_validator(), family=BrowserFamily.CHROMIUM)

    # then
    context.route.assert_awaited_once()


async def test_install_closes_page_websockets_for_firefox_in_the_main_world() -> None:
    # given
    context = _make_context()

    # when
    await install_browser_guard(context, _make_validator(), family=BrowserFamily.FIREFOX)

    # then
    script = context.add_init_script.await_args.args[0]
    assert script.startswith("mw:")
    assert "WebSocket" in script
    context.route_web_socket.assert_not_awaited()


async def test_install_returns_the_refused_navigation_list() -> None:
    # given
    context = _make_context()
    route = _make_route("http://169.254.169.254/", navigation=True)

    # when
    refused = await install_browser_guard(context, _make_validator(), family=BrowserFamily.CHROMIUM)
    route_handler = context.route.call_args.args[1]
    await route_handler(route)

    # then
    assert refused == ["http://169.254.169.254/"]


def _event_handler(context: MagicMock, event: str) -> Any:
    return next(call.args[1] for call in context.on.call_args_list if call.args[0] == event)


async def test_a_tunnel_refusal_of_the_read_page_main_frame_is_recorded_on_requestfailed() -> None:
    # given
    context = _make_context()
    route = _make_route("https://10.0.0.5/", navigation=True)
    refused = await install_browser_guard(context, _make_validator(), family=BrowserFamily.CHROMIUM)

    # when
    with patch.object(browser_tunnel, "was_refused", return_value=True) as was_refused:
        _event_handler(context, "requestfailed")(route.request)

    # then
    assert refused == ["https://10.0.0.5/"]
    was_refused.assert_called_once_with("https://10.0.0.5/")


async def test_a_tunnel_refusal_of_a_plain_http_redirect_hop_is_recorded_on_response() -> None:
    # given
    context = _make_context()
    route = _make_route("http://10.0.0.5/", navigation=True)
    response = MagicMock(request=route.request, status=403)
    refused = await install_browser_guard(context, _make_validator(), family=BrowserFamily.CHROMIUM)

    # when
    with patch.object(browser_tunnel, "was_refused", return_value=True):
        _event_handler(context, "response")(response)

    # then
    assert refused == ["http://10.0.0.5/"]


@pytest.mark.parametrize("status", [200, 404, 503])
async def test_a_response_of_a_connection_that_succeeded_is_not_a_tunnel_refusal(status: int) -> None:
    # given
    context = _make_context()
    route = _make_route("http://flaky.example/", navigation=True)
    response = MagicMock(request=route.request, status=status)
    refused = await install_browser_guard(context, _make_validator(), family=BrowserFamily.CHROMIUM)

    # when
    with patch.object(browser_tunnel, "was_refused", return_value=True):
        _event_handler(context, "response")(response)

    # then
    assert refused == []


@pytest.mark.parametrize(
    ("navigation", "sub_frame", "was_refused"),
    [(False, False, True), (True, True, True), (True, False, False)],
    ids=["subresource", "sub frame", "not refused"],
)
async def test_only_a_refusal_of_the_read_page_main_frame_is_recorded(
    navigation: bool, sub_frame: bool, was_refused: bool
) -> None:
    # given
    context = _make_context()
    route = _make_route("https://10.0.0.5/", navigation=navigation, sub_frame=sub_frame)
    refused = await install_browser_guard(context, _make_validator(), family=BrowserFamily.CHROMIUM)

    # when
    with patch.object(browser_tunnel, "was_refused", return_value=was_refused):
        _event_handler(context, "requestfailed")(route.request)

    # then
    assert refused == []


def test_fetch_policy_disables_file_root() -> None:
    # when
    policy = web_hunter_fetch_policy()

    # then
    assert policy.file_root is None


def test_chromium_is_left_no_way_out_except_the_tunnel() -> None:
    # given
    with patch.object(browser_tunnel, "_port", _TUNNEL_PORT):
        # when
        args = chromium_guard_args()

    # then
    assert f"--proxy-server=http://127.0.0.1:{_TUNNEL_PORT}" in args
    assert "--proxy-bypass-list=<-loopback>" in args
    assert "--force-webrtc-ip-handling-policy=disable_non_proxied_udp" in args
    assert "--disable-quic" in args


def test_firefox_is_left_no_way_out_except_the_tunnel() -> None:
    # given
    with patch.object(browser_tunnel, "_port", _TUNNEL_PORT):
        # when
        prefs = firefox_guard_prefs()

    # then
    assert prefs["network.proxy.type"] == 1
    assert prefs["network.proxy.http"] == "127.0.0.1"
    assert prefs["network.proxy.http_port"] == _TUNNEL_PORT
    assert prefs["network.proxy.ssl"] == "127.0.0.1"
    assert prefs["network.proxy.ssl_port"] == _TUNNEL_PORT
    assert prefs["network.proxy.no_proxies_on"] == ""
    assert prefs["network.proxy.allow_hijacking_localhost"] is True
    assert prefs["network.proxy.failover_direct"] is False
    assert prefs["media.peerconnection.ice.proxy_only"] is True
    assert prefs["network.http.http3.enable"] is False


def test_document_router_and_curl_tier_use_the_one_shared_fetch_policy() -> None:
    # given
    from src.reader import document_router
    from src.reader.strategies import curl_cffi_fetcher

    # when / then
    assert getattr(document_router, "web_hunter_fetch_policy", None) is web_hunter_fetch_policy
    assert getattr(curl_cffi_fetcher, "web_hunter_fetch_policy", None) is web_hunter_fetch_policy
    assert not hasattr(document_router, "_fetch_policy")
    assert not hasattr(curl_cffi_fetcher, "_fetch_policy")


async def test_guarded_goto_navigates_and_marks_the_read_page_main_frame() -> None:
    # given
    answer = MagicMock()
    page = MagicMock()
    page.goto = AsyncMock(return_value=answer)

    # when
    result = await guarded_goto(page, "https://example.com/", wait_until="commit", timeout=1000)

    # then
    assert result is answer
    page.goto.assert_awaited_once_with("https://example.com/", wait_until="commit", timeout=1000)
    assert page.main_frame in browser_guard._read_frames


def test_guard_page_goto_marks_the_page_of_a_crawler_that_navigates_itself() -> None:
    # given
    page = MagicMock()

    # when
    guard_page_goto(page)

    # then
    assert page.main_frame in browser_guard._read_frames

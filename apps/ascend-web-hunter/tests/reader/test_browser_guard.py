"""Tests for the guarded browser route handler (task 2.5)."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from ascend_python_common.uri_guard import FetchTarget, UnsafeUriError

from src.reader.browser_guard import (
    handle_guarded_route,
    handle_guarded_web_socket,
    install_browser_guard,
    web_hunter_fetch_policy,
)


def _make_validator(blocked: bool = False) -> MagicMock:
    validator = MagicMock()
    validator.should_block = MagicMock(return_value=blocked)

    return validator


def _make_route(url: str, *, navigation: bool = False) -> MagicMock:
    request = MagicMock()
    request.url = url
    request.is_navigation_request = MagicMock(return_value=navigation)
    route = MagicMock()
    route.request = request
    route.abort = AsyncMock()
    route.continue_ = AsyncMock()
    route.fetch = AsyncMock()
    route.fulfill = AsyncMock()

    return route


def _make_websocket(url: str) -> MagicMock:
    websocket = MagicMock()
    websocket.url = url
    websocket.close = AsyncMock()
    websocket.connect_to_server = MagicMock()

    return websocket


@pytest.mark.asyncio
async def test_private_url_is_aborted_and_never_fetched() -> None:
    # given
    route = _make_route("http://169.254.169.254/")

    # when
    await handle_guarded_route(route, _make_validator())

    # then
    route.abort.assert_awaited_once_with("blockedbyclient")
    route.fetch.assert_not_awaited()
    route.fulfill.assert_not_awaited()


@pytest.mark.asyncio
async def test_public_url_is_fetched_without_redirects_and_fulfilled() -> None:
    # given
    route = _make_route("https://example.com/")
    response = MagicMock(status=200)
    response.headers = {}
    route.fetch = AsyncMock(return_value=response)

    # when
    with patch(
        "src.reader.browser_guard.check_fetch_uri",
        new=AsyncMock(return_value=FetchTarget(url="https://example.com/", host="example.com", port=443)),
    ):
        await handle_guarded_route(route, _make_validator())

    # then
    route.fetch.assert_awaited_once_with(url="https://example.com/", max_redirects=0)
    route.fulfill.assert_awaited_once_with(response=response)
    route.abort.assert_not_awaited()


@pytest.mark.asyncio
async def test_blocklisted_url_is_aborted() -> None:
    # given
    route = _make_route("https://example.com/ads/banner.js")

    # when
    await handle_guarded_route(route, _make_validator(blocked=True))

    # then
    route.abort.assert_awaited_once_with()
    route.fetch.assert_not_awaited()


@pytest.mark.asyncio
async def test_blocklisted_navigation_raises() -> None:
    # given
    route = _make_route("https://example.com/ads/page", navigation=True)

    # when / then
    with pytest.raises(UnsafeUriError):
        await handle_guarded_route(route, _make_validator(blocked=True))

    route.abort.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_data_url_passes() -> None:
    # given
    route = _make_route("data:text/html,hello")

    # when
    await handle_guarded_route(route, _make_validator())

    # then
    route.continue_.assert_awaited_once_with()
    route.abort.assert_not_awaited()
    route.fetch.assert_not_awaited()


@pytest.mark.asyncio
async def test_blob_url_passes() -> None:
    # given
    route = _make_route("blob:https://example.com/550e8400-e29b-41d4-a716-446655440000")

    # when
    await handle_guarded_route(route, _make_validator())

    # then
    route.continue_.assert_awaited_once_with()
    route.abort.assert_not_awaited()
    route.fetch.assert_not_awaited()


@pytest.mark.asyncio
async def test_ftp_url_is_refused() -> None:
    # given
    route = _make_route("ftp://example.com/file.txt")

    # when
    await handle_guarded_route(route, _make_validator())

    # then
    route.abort.assert_awaited_once_with("blockedbyclient")
    route.fetch.assert_not_awaited()


@pytest.mark.asyncio
async def test_refused_main_navigation_raises() -> None:
    # given
    route = _make_route("http://169.254.169.254/", navigation=True)

    # when / then
    with pytest.raises(UnsafeUriError):
        await handle_guarded_route(route, _make_validator())

    route.abort.assert_awaited_once_with("blockedbyclient")
    route.fetch.assert_not_awaited()


@pytest.mark.asyncio
async def test_refused_websocket_is_closed() -> None:
    # given
    websocket = _make_websocket("ws://169.254.169.254/socket")

    # when
    await handle_guarded_web_socket(websocket, _make_validator())

    # then
    websocket.close.assert_awaited_once_with()
    websocket.connect_to_server.assert_not_called()


@pytest.mark.asyncio
async def test_allowed_websocket_is_forwarded() -> None:
    # given
    websocket = _make_websocket("wss://example.com/socket")

    # when
    with patch(
        "src.reader.browser_guard.check_fetch_uri",
        new=AsyncMock(
            return_value=FetchTarget(url="https://example.com/socket", host="example.com", port=443)
        ),
    ):
        await handle_guarded_web_socket(websocket, _make_validator())

    # then
    websocket.connect_to_server.assert_called_once_with()
    websocket.close.assert_not_awaited()


@pytest.mark.asyncio
async def test_non_websocket_scheme_url_is_checked_as_is() -> None:
    # given
    websocket = _make_websocket("https://example.com/socket")

    # when
    with patch(
        "src.reader.browser_guard.check_fetch_uri",
        new=AsyncMock(
            return_value=FetchTarget(url="https://example.com/socket", host="example.com", port=443)
        ),
    ) as mock_check:
        await handle_guarded_web_socket(websocket, _make_validator())

    # then
    mock_check.assert_awaited_once()
    assert mock_check.call_args.args[0] == "https://example.com/socket"
    websocket.connect_to_server.assert_called_once_with()


@pytest.mark.asyncio
async def test_blocklisted_websocket_is_closed() -> None:    # given
    websocket = _make_websocket("wss://example.com/ads/socket")

    # when
    await handle_guarded_web_socket(websocket, _make_validator(blocked=True))

    # then
    websocket.close.assert_awaited_once_with()
    websocket.connect_to_server.assert_not_called()


@pytest.mark.asyncio
async def test_install_wires_route_and_websocket_handlers() -> None:
    # given
    context = MagicMock()
    context.route = AsyncMock()
    context.route_web_socket = AsyncMock()
    route = _make_route("data:text/html,hi")
    websocket = _make_websocket("wss://example.com/socket")

    # when
    with patch(
        "src.reader.browser_guard.check_fetch_uri",
        new=AsyncMock(
            return_value=FetchTarget(url="https://example.com/socket", host="example.com", port=443)
        ),
    ):
        await install_browser_guard(context, _make_validator())
        route_handler = context.route.call_args.args[1]
        await route_handler(route)
        websocket_handler = context.route_web_socket.call_args.args[1]
        await websocket_handler(websocket)

    # then
    context.route.assert_awaited_once()
    assert context.route.call_args.args[0] == "**/*"
    route.continue_.assert_awaited_once_with()
    websocket.connect_to_server.assert_called_once_with()


@pytest.mark.asyncio
async def test_install_without_websocket_routing_skips_it() -> None:
    # given
    context = MagicMock()
    context.route = AsyncMock()
    del context.route_web_socket

    # when
    await install_browser_guard(context, _make_validator())

    # then
    context.route.assert_awaited_once()


def test_fetch_policy_disables_file_root() -> None:
    # when
    policy = web_hunter_fetch_policy()

    # then
    assert policy.file_root is None


@pytest.mark.asyncio
async def test_refused_navigation_is_recorded_when_list_given() -> None:
    # given
    route = _make_route("http://169.254.169.254/", navigation=True)
    refused: list[str] = []

    # when
    await handle_guarded_route(route, _make_validator(), refused)

    # then
    assert refused == ["http://169.254.169.254/"]
    route.abort.assert_awaited_once_with("blockedbyclient")


@pytest.mark.asyncio
async def test_blocklisted_navigation_is_recorded_when_list_given() -> None:
    # given
    route = _make_route("https://example.com/ads/page", navigation=True)
    refused: list[str] = []

    # when
    await handle_guarded_route(route, _make_validator(blocked=True), refused)

    # then
    assert refused == ["https://example.com/ads/page"]
    route.abort.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_install_returns_the_refused_navigation_list() -> None:
    # given
    context = MagicMock()
    context.route = AsyncMock()
    context.route_web_socket = AsyncMock()
    route = _make_route("http://169.254.169.254/", navigation=True)

    # when
    refused = await install_browser_guard(context, _make_validator())
    route_handler = context.route.call_args.args[1]
    await route_handler(route)

    # then
    assert refused == ["http://169.254.169.254/"]


def _response(status: int, location: str | None) -> MagicMock:
    response = MagicMock(status=status)
    response.headers = {"location": location} if location is not None else {}

    return response


@pytest.mark.asyncio
async def test_allowed_redirect_hop_is_followed_and_final_fulfilled() -> None:
    # given
    route = _make_route("https://example.com/start", navigation=True)
    route.fetch = AsyncMock(
        side_effect=[
            _response(302, "/next"),
            _response(200, None),
        ]
    )
    refused: list[str] = []

    # when
    with patch(
        "src.reader.browser_guard.check_fetch_uri",
        new=AsyncMock(
            return_value=FetchTarget(url="https://example.com/", host="example.com", port=443)
        ),
    ):
        await handle_guarded_route(route, _make_validator(), refused)

    # then
    assert [call.kwargs["url"] for call in route.fetch.await_args_list] == [
        "https://example.com/start",
        "https://example.com/next",
    ]
    route.fulfill.assert_awaited_once()
    assert route.fulfill.call_args.kwargs["response"].status == 200
    route.abort.assert_not_awaited()
    assert refused == []


@pytest.mark.asyncio
async def test_redirect_to_private_aborts_and_records() -> None:
    # given
    route = _make_route("https://example.com/start", navigation=True)
    route.fetch = AsyncMock(side_effect=[_response(302, "http://169.254.169.254/")])
    refused: list[str] = []

    # when
    with patch(
        "src.reader.browser_guard.check_fetch_uri",
        new=AsyncMock(
            side_effect=[
                FetchTarget(url="https://example.com/start", host="example.com", port=443),
                UnsafeUriError("URI resolves to a non-public address"),
            ]
        ),
    ):
        await handle_guarded_route(route, _make_validator(), refused)

    # then
    route.abort.assert_awaited_once_with("blockedbyclient")
    assert route.fetch.await_count == 1
    route.fulfill.assert_not_awaited()
    assert refused == ["http://169.254.169.254/"]


@pytest.mark.asyncio
async def test_redirect_without_location_is_fulfilled() -> None:
    # given
    route = _make_route("https://example.com/odd")
    response = _response(302, None)
    route.fetch = AsyncMock(return_value=response)

    # when
    with patch(
        "src.reader.browser_guard.check_fetch_uri",
        new=AsyncMock(
            return_value=FetchTarget(url="https://example.com/odd", host="example.com", port=443)
        ),
    ):
        await handle_guarded_route(route, _make_validator())

    # then
    route.fetch.assert_awaited_once()
    route.fulfill.assert_awaited_once_with(response=response)


@pytest.mark.asyncio
async def test_too_many_redirects_aborts() -> None:
    # given
    route = _make_route("https://example.com/loop", navigation=True)
    route.fetch = AsyncMock(side_effect=[_response(302, "/loop")])
    refused: list[str] = []

    # when
    with (
        patch(
            "src.reader.browser_guard.check_fetch_uri",
            new=AsyncMock(
                return_value=FetchTarget(
                    url="https://example.com/loop", host="example.com", port=443
                )
            ),
        ),
        patch("src.reader.browser_guard.settings.FETCH_MAX_REDIRECT_HOPS", 0),
    ):
        await handle_guarded_route(route, _make_validator(), refused)

    # then
    route.abort.assert_awaited_once_with("blockedbyclient")
    route.fulfill.assert_not_awaited()
    assert refused == ["https://example.com/loop"]

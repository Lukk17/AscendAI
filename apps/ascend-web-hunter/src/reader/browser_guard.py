"""Guarded browser route handler.

Every browser tier installs this on its context before the first navigation,
with ``service_workers="block"`` on the context, because Playwright routing
does not see requests a service worker makes. The handler:

1. applies the ad blocklist, as ``URLValidator.route_handler`` does;
2. runs ``check_fetch_uri`` on the request URL with the web-hunter policy, so
   every page load, frame, popup navigation and subresource is checked before
   the browser connects. ``data:`` and ``blob:`` URLs make no network request
   and pass. Any other scheme is refused;
3. on a refusal, aborts with ``route.abort("blockedbyclient")``. A refused
   navigation of the main frame of the page being read is recorded in the
   ``refused_navigations`` list the caller passed to ``install_browser_guard``,
   so the strategy can end it with ``UnsafeUriError`` after the navigation
   fails. A refused navigation of a sub-frame or of a popup the page opened is
   only aborted, and the page goes on without that document. Raising inside the handler
   itself is not an option: the exception escapes the routing dispatch and
   poisons the shared browser connection, while the awaiting ``page.goto``
   only ever sees ``net::ERR_BLOCKED_BY_CLIENT``;
4. on a pass, continues the request with ``route.continue_()``, a Chromium
   navigation with explicit headers, which changes the header order on the
   wire. Any route makes the driver turn the cache off, so Chromium still
   sends ``pragma`` and ``cache-control`` below the level a route can change.
   The browser makes its own connection through the pinned tunnel of ``pinned_tunnel``,
   the only way out a browser has: ``chromium_guard_args`` and
   ``firefox_guard_prefs`` point every launch at it.

Playwright does not route the hops of a redirect, in any engine, so a redirect
is checked by the tunnel when the browser asks to connect to it. A refusal
there fails the navigation (a CONNECT answers 403, and a plain http request 403
with an empty body), and ``install_browser_guard`` reads the ``requestfailed``
and ``response`` events of the read's own main frame against
``browser_tunnel.was_refused``, so the read still ends with ``UnsafeUriError``.

Page WebSockets are closed before the browser connects. Chromium closes them in
``route_web_socket``, Camoufox has no such route and no constructor that
``route_web_socket`` reaches, so a main-world init script makes its page
``WebSocket`` constructor throw. Every other connection the route does not see
goes to the tunnel, which checks its address.
"""

import logging
from collections.abc import Mapping
from enum import StrEnum
from typing import Any
from urllib.parse import urlsplit
from weakref import WeakSet

from ascend_python_common.uri_guard import FetchPolicy, UnsafeUriError, check_fetch_uri
from patchright.async_api import Error as PatchrightError
from playwright.async_api import BrowserContext, Frame, Page, Request, Response, Route, WebSocketRoute
from playwright.async_api import Error as PlaywrightError

from src.config.config import settings
from src.observability.safe_address import address_without_query, exception_text_without_queries
from src.reader.pinned_tunnel import TUNNEL_HOST, TUNNEL_REFUSAL_STATUS, PinnedTunnel
from src.validator.url_validator import URLValidator

logger = logging.getLogger(__name__)


class BrowserFamily(StrEnum):
    CHROMIUM = "chromium"
    FIREFOX = "firefox"


_WEBSOCKET_CLOSING_SCRIPT = (
    "mw:window.WebSocket = class WebSocket "
    "{ constructor() { throw new DOMException('WebSocket is closed', 'SecurityError'); } };"
)


def chromium_guard_args() -> tuple[str, ...]:
    """The launch arguments that leave a Chromium no way out except the tunnel, QUIC off."""
    return (
        f"--proxy-server=http://{TUNNEL_HOST}:{browser_tunnel.port}",
        "--proxy-bypass-list=<-loopback>",
        "--force-webrtc-ip-handling-policy=disable_non_proxied_udp",
        "--disable-quic",
    )


def firefox_guard_prefs() -> Mapping[str, str | int | bool]:
    """The Firefox preferences that leave Camoufox no way out except the tunnel, HTTP/3 off."""
    port = browser_tunnel.port

    return {
        "network.proxy.type": 1,
        "network.proxy.http": TUNNEL_HOST,
        "network.proxy.http_port": port,
        "network.proxy.ssl": TUNNEL_HOST,
        "network.proxy.ssl_port": port,
        "network.proxy.no_proxies_on": "",
        "network.proxy.allow_hijacking_localhost": True,
        "network.proxy.failover_direct": False,
        "media.peerconnection.ice.proxy_only": True,
        "network.http.http3.enable": False,
    }


_BLOCKED_BY_CLIENT = "blockedbyclient"
_CACHE_HEADERS = frozenset({"pragma", "cache-control"})
_FAILED = "failed"
_BROWSER_ERRORS = (PlaywrightError, PatchrightError)
_BROWSER_GONE_MARKERS = (
    "target closed",
    "target crashed",
    "context closed",
    "browser closed",
    "browser has been closed",
    "connection closed",
    "page crashed",
)

_PASS_THROUGH_SCHEMES = frozenset({"data", "blob"})
_FETCHABLE_SCHEMES = frozenset({"http", "https"})


def looks_like_browser_gone(exc: BaseException) -> bool:
    """True when the error text says the page, context or browser it was sent to no longer exists."""
    message = str(exc).lower()

    return any(marker in message for marker in _BROWSER_GONE_MARKERS)


def web_hunter_fetch_policy() -> FetchPolicy:
    """The URI guard policy every browser request passes: the hosts of
    ``ALLOWED_PRIVATE_HOSTS`` (empty by default, set only during an e2e
    sweep), no file root, and the configured redirect hop budget. A browser
    follows redirects itself, so ``FETCH_MAX_REDIRECT_HOPS`` does not limit
    them and the browser's own limit applies. Each hop still passes the check."""
    return FetchPolicy(
        allowed_hosts=tuple(settings.ALLOWED_PRIVATE_HOSTS),
        file_root=None,
        max_redirect_hops=settings.FETCH_MAX_REDIRECT_HOPS,
    )


browser_tunnel = PinnedTunnel(web_hunter_fetch_policy)

_read_frames: WeakSet[Frame] = WeakSet()


async def handle_guarded_route(
    route: Route,
    url_validator: URLValidator,
    refused_navigations: list[str] | None = None,
    *,
    family: BrowserFamily,
) -> None:
    """Route one browser request through the ad blocklist and the URI guard, or continue it.

    A refused navigation of the read page's main frame is appended to
    *refused_navigations* when a list is given, so the strategy that installed
    the handler can end the failed navigation with `UnsafeUriError`. Without a list it raises at once, which
    is only useful with a faked route: raising inside a live handler poisons
    the shared browser connection instead of reaching `page.goto`.
    """
    request_url: str = route.request.url
    if url_validator.should_block(request_url):
        await route.abort()
        _record_or_raise(route, refused_navigations, f"blocked by the ad blocklist: {request_url}")

        return

    scheme = urlsplit(request_url).scheme.lower()
    if scheme in _PASS_THROUGH_SCHEMES:
        await route.continue_()

        return

    if scheme not in _FETCHABLE_SCHEMES:
        await route.abort(_BLOCKED_BY_CLIENT)
        _record_or_raise(route, refused_navigations, f"unsupported URI scheme: {scheme or 'none'}")

        return

    try:
        await check_fetch_uri(request_url, web_hunter_fetch_policy())
    except UnsafeUriError as exc:
        logger.warning("browser_guard: refusing %s: %s", address_without_query(request_url), exc)
        await route.abort(_BLOCKED_BY_CLIENT)
        _record_or_raise(route, refused_navigations, str(exc))

        return

    await _continue_allowed(route, family)


def headers_without_cache_directives(headers: Mapping[str, str]) -> dict[str, str]:
    """A copy of *headers* without the ``pragma`` and ``cache-control`` entries."""
    return {name: value for name, value in headers.items() if name.lower() not in _CACHE_HEADERS}


async def _continue_allowed(route: Route, family: BrowserFamily) -> None:
    request = route.request
    if family is BrowserFamily.CHROMIUM and request.is_navigation_request():
        await route.continue_(headers=headers_without_cache_directives(request.headers))

        return

    await route.continue_()


def _known_frame(request: Request) -> Frame | None:
    """The request's frame, or None while the browser has not reported the page of a new popup."""
    try:
        return request.frame
    except _BROWSER_ERRORS:
        return None


async def guarded_goto(page: Page, url: str, **goto_options: Any) -> Response | None:
    """Navigate *page* to *url* like ``page.goto``, as the frame whose refusal fails the read."""
    _read_frames.add(page.main_frame)

    return await page.goto(url, **goto_options)


def guard_page_goto(page: Page) -> None:
    """Mark *page*'s main frame as the read's own, for a crawler that calls ``page.goto`` itself."""
    _read_frames.add(page.main_frame)


def _log_route_failure(message: str, url: str, exc: BaseException, detail: str) -> None:
    if isinstance(exc, _BROWSER_ERRORS) and looks_like_browser_gone(exc):
        logger.debug("browser_guard: page of %s went away first: %s", address_without_query(url), detail)

        return

    logger.warning(message, address_without_query(url), detail)


async def _abort_quietly(route: Route, code: str) -> None:
    """Abort *route*, or hand it back when its page is already gone, so its dispatch still ends."""
    try:
        await route.abort(code)
    except _BROWSER_ERRORS as exc:
        logger.debug("browser_guard: abort of %s skipped: %s", address_without_query(route.request.url), exc)
        if looks_like_browser_gone(exc):
            await route.fallback()


def _navigates_the_read_page(request: Request) -> bool:
    if not request.is_navigation_request():
        return False
    frame = _known_frame(request)

    return frame is not None and frame in _read_frames


def _record_or_raise(route: Route, refused_navigations: list[str] | None, reason: str) -> None:
    """End a refused navigation of the read page: record it for the installing
    strategy, or raise when nobody records (a faked route in a unit test). A
    refused subresource, sub-frame or popup navigation is only blocked, and the
    page goes on without it."""
    if not _navigates_the_read_page(route.request):
        return

    if refused_navigations is None:
        raise UnsafeUriError(reason)

    refused_navigations.append(route.request.url)


async def handle_guarded_web_socket(websocket: WebSocketRoute, url_validator: URLValidator) -> None:
    """Close a page-opened WebSocket before the browser connects. A blocklisted
    one is closed silently, every other one with one warning."""
    url: str = websocket.url
    if not url_validator.should_block(url):
        logger.warning(
            "browser_guard: closing websocket %s: browser WebSockets are not pinned",
            address_without_query(url),
        )
    await websocket.close()


def _record_tunnel_refusal(request: Request, refused_navigations: list[str]) -> None:
    if _navigates_the_read_page(request) and browser_tunnel.was_refused(request.url):
        refused_navigations.append(request.url)


def _record_tunnel_refusal_answer(response: Response, refused_navigations: list[str]) -> None:
    if response.status == TUNNEL_REFUSAL_STATUS:
        _record_tunnel_refusal(response.request, refused_navigations)


async def install_browser_guard(
    context: BrowserContext, url_validator: URLValidator, *, family: BrowserFamily
) -> list[str]:
    """Install the guarded handler on *context* before its first navigation,
    plus the WebSocket handler for *family*. Returns the refused-navigation
    URLs the handler records and the tunnel refusals of the read's main frame,
    so the strategy can end a failed navigation with `UnsafeUriError`."""
    refused: list[str] = []

    async def _guarded(route: Route) -> None:
        try:
            await handle_guarded_route(route, url_validator, refused, family=family)
        except Exception as exc:
            _log_route_failure(
                "browser_guard: handling %s failed: %s",
                route.request.url,
                exc,
                exception_text_without_queries(exc),
            )
            await _abort_quietly(route, _FAILED)

    context.on("requestfailed", lambda request: _record_tunnel_refusal(request, refused))
    context.on("response", lambda response: _record_tunnel_refusal_answer(response, refused))
    await context.route("**/*", _guarded)

    if family is BrowserFamily.FIREFOX:
        await context.add_init_script(_WEBSOCKET_CLOSING_SCRIPT)

        return refused

    route_web_socket = getattr(context, "route_web_socket", None)
    if route_web_socket is None:
        logger.warning("browser_guard: context.route_web_socket is unavailable; skipping it")

        return refused

    async def _guarded_socket(websocket: WebSocketRoute) -> None:
        await handle_guarded_web_socket(websocket, url_validator)

    await route_web_socket("**/*", _guarded_socket)

    return refused

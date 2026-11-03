"""Guarded browser route handler (design D6).

Every browser tier installs this on its context before the first navigation,
with ``service_workers="block"`` on the context, because Playwright routing
does not see requests a service worker makes. The handler:

1. applies the ad blocklist, as ``URLValidator.route_handler`` does;
2. runs ``check_fetch_uri`` on the request URL with the web-hunter policy, so
   every page load, frame, popup navigation and subresource is checked before
   the browser connects. ``data:`` and ``blob:`` URLs make no network request
   and pass. Any other scheme is refused;
3. on a refusal, aborts with ``route.abort("blockedbyclient")`` so the browser
   opens no connection. A refused main navigation is recorded in the
   ``refused_navigations`` list the caller passed to ``install_browser_guard``,
   so the strategy can end it with ``UnsafeUriError`` after the navigation
   fails. Raising inside the handler itself is not an option: the exception
   escapes the routing dispatch and poisons the shared browser connection,
   while the awaiting ``page.goto`` only ever sees ``net::ERR_BLOCKED_BY_CLIENT``;
4. on a pass, fetches through ``route.fetch(max_redirects=0)`` and hands the
   answer to the browser with ``route.fulfill(response=...)``. Redirect hops
   are followed inside the handler with a guard check before each one, because
   a fulfilled 3xx is followed by the browser itself without re-entering
   routing. Only the final non-redirect answer reaches the browser; a chain
   past the hop budget is aborted. ``route.continue_()`` is never used.

Owner decision 66 of 2026-10-04.
"""

import logging
from urllib.parse import urljoin, urlsplit

from ascend_python_common.uri_guard import FetchPolicy, UnsafeUriError, check_fetch_uri
from playwright.async_api import BrowserContext, Route, WebSocketRoute

from src.config.config import settings
from src.validator.url_validator import URLValidator

logger = logging.getLogger(__name__)

_BLOCKED_BY_CLIENT = "blockedbyclient"

_PASS_THROUGH_SCHEMES = frozenset({"data", "blob"})
_FETCHABLE_SCHEMES = frozenset({"http", "https"})
_WEBSOCKET_SCHEME_MAP = {"ws": "http", "wss": "https"}
_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})


def web_hunter_fetch_policy() -> FetchPolicy:
    """The URI guard policy every browser request passes: the hosts of
    ``ALLOWED_PRIVATE_HOSTS`` (empty by default, set only during an e2e
    sweep), no file root, and the configured redirect hop budget."""
    return FetchPolicy(
        allowed_hosts=tuple(settings.ALLOWED_PRIVATE_HOSTS),
        file_root=None,
        max_redirect_hops=settings.FETCH_MAX_REDIRECT_HOPS,
    )


async def handle_guarded_route(
    route: Route, url_validator: URLValidator, refused_navigations: list[str] | None = None
) -> None:
    """Route one browser request through the ad blocklist and the URI guard.

    A refused main navigation is appended to *refused_navigations* when a list
    is given, so the strategy that installed the handler can end the failed
    navigation with `UnsafeUriError`. Without a list it raises at once, which
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
        logger.warning("browser_guard: refusing %s: %s", request_url, exc)
        await route.abort(_BLOCKED_BY_CLIENT)
        _record_or_raise(route, refused_navigations, str(exc))

        return

    await _fetch_following_redirects(route, request_url, refused_navigations)


async def _fetch_following_redirects(
    route: Route, request_url: str, refused_navigations: list[str] | None
) -> None:
    """Fetch the request and hand the answer to the browser, following redirect
    hops in-process with a guard check before each one.

    A fulfilled 3xx is followed by the browser itself, and that follow-up does
    not re-enter routing, so handing the browser a raw redirect would let every
    later hop connect unchecked. Only the final non-redirect answer reaches the
    browser, after every hop was checked. A chain past the hop budget is
    aborted instead of handed over.
    """
    policy = web_hunter_fetch_policy()
    fetch_url = request_url
    for _ in range(policy.max_redirect_hops + 1):
        response = await route.fetch(url=fetch_url, max_redirects=0)
        location = response.headers.get("location")
        if response.status not in _REDIRECT_STATUSES or not location:
            await route.fulfill(response=response)

            return

        fetch_url = urljoin(fetch_url, location)
        try:
            await check_fetch_uri(fetch_url, policy)
        except UnsafeUriError as exc:
            logger.warning("browser_guard: refusing redirect %s: %s", fetch_url, exc)
            await route.abort(_BLOCKED_BY_CLIENT)
            _record_or_raise(route, refused_navigations, str(exc), fetch_url)

            return

    logger.warning("browser_guard: too many redirects starting at %s", request_url)
    await route.abort(_BLOCKED_BY_CLIENT)
    _record_or_raise(route, refused_navigations, f"too many redirects starting at {request_url}")


def _record_or_raise(
    route: Route, refused_navigations: list[str] | None, reason: str, url: str | None = None
) -> None:
    """End a refused main navigation: record it for the installing strategy,
    or raise when nobody records (a faked route in a unit test). A refused
    subresource is only blocked, and the page goes on without it."""
    if not route.request.is_navigation_request():
        return

    if refused_navigations is None:
        raise UnsafeUriError(reason)

    refused_navigations.append(url or route.request.url)


async def handle_guarded_web_socket(websocket: WebSocketRoute, url_validator: URLValidator) -> None:
    """Check a page-opened WebSocket the same way: blocklisted or refused URLs
    are closed before the browser connects, the rest are forwarded."""
    url: str = websocket.url
    if url_validator.should_block(url):
        await websocket.close()

        return

    scheme = urlsplit(url).scheme.lower()
    check_url = url
    mapped = _WEBSOCKET_SCHEME_MAP.get(scheme)
    if mapped is not None:
        check_url = f"{mapped}:{url.split(':', 1)[1]}"

    try:
        await check_fetch_uri(check_url, web_hunter_fetch_policy())
    except UnsafeUriError as exc:
        logger.warning("browser_guard: refusing websocket %s: %s", url, exc)
        await websocket.close()

        return

    websocket.connect_to_server()


async def install_browser_guard(context: BrowserContext, url_validator: URLValidator) -> list[str]:
    """Install the guarded handler on *context* before its first navigation,
    plus the WebSocket check when the pinned Playwright version offers it.
    Returns the refused-navigation URLs the handler records, so the strategy
    can end a failed navigation with `UnsafeUriError`."""
    refused: list[str] = []

    async def _guarded(route: Route) -> None:
        await handle_guarded_route(route, url_validator, refused)

    await context.route("**/*", _guarded)

    route_web_socket = getattr(context, "route_web_socket", None)
    if route_web_socket is None:
        logger.warning("browser_guard: context.route_web_socket is unavailable; skipping it")

        return refused

    async def _guarded_socket(websocket: WebSocketRoute) -> None:
        await handle_guarded_web_socket(websocket, url_validator)

    await route_web_socket("**/*", _guarded_socket)

    return refused

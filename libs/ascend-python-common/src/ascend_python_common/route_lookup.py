from collections.abc import Callable, Iterator, Sequence
from typing import Any

from starlette.routing import BaseRoute, Match
from starlette.types import Scope

Handler = Callable[..., Any]


def resolve_route(routes: Sequence[BaseRoute], scope: Scope) -> tuple[Handler | None, str | None]:
    """Resolve the matched route handler and its template for a request scope.

    Uses Starlette's own matching, so routes from an included router (which
    FastAPI 0.137 and later nests inside an intermediate router object without
    an ``endpoint``) resolve the same way as directly added routes. A match
    inside a mounted sub-app is resolved by descending into the mount with the
    child scope, and the mount path is prepended to the template. Returns
    ``(None, None)`` when no route matches.
    """
    return _resolve(routes, scope, "")


def _resolve(routes: Sequence[BaseRoute], scope: Scope, prefix: str) -> tuple[Handler | None, str | None]:
    for route in _effective_routes(routes):
        match, child_scope = route.matches(scope)
        if match == Match.NONE:
            continue
        sub_routes = _sub_routes(route)
        if sub_routes:
            mount_path = (getattr(route, "path", "") or "").rstrip("/")
            endpoint, template = _resolve(sub_routes, {**scope, **child_scope}, prefix + mount_path)
            if endpoint is not None or template is not None:
                return endpoint, template
            continue
        if match == Match.FULL:
            template = _template_of(route)
            if template is not None and prefix:
                template = prefix + template
            return getattr(route, "endpoint", None), template
    return None, None


def resolve_route_handler(routes: Sequence[BaseRoute], scope: Scope) -> Handler | None:
    """Resolve only the matched route handler for a request scope."""
    endpoint, _ = resolve_route(routes, scope)
    return endpoint


def _effective_routes(routes: Sequence[BaseRoute]) -> Iterator[BaseRoute]:
    for route in routes:
        contexts = getattr(route, "effective_route_contexts", None)
        if callable(contexts):
            yield from contexts()
        else:
            yield route


def _sub_routes(route: BaseRoute) -> list[BaseRoute]:
    sub_routes = getattr(route, "routes", None)
    if sub_routes:
        return list(sub_routes)
    inner = getattr(route, "starlette_route", None)
    sub_routes = getattr(inner, "routes", None) if inner is not None else None
    return list(sub_routes) if sub_routes else []


def _template_of(route: BaseRoute) -> str | None:
    return getattr(route, "path", None) or getattr(route, "path_format", None)

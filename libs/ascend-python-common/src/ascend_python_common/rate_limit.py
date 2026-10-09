import logging
from collections.abc import Callable
from typing import Any, Final

import mcp.types as mt
from fastapi import FastAPI
from fastmcp.exceptions import ToolError
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
from limits import parse
from limits.limits import RateLimitItem
from slowapi import Limiter
from slowapi.middleware import SlowAPIASGIMiddleware
from slowapi.util import get_remote_address
from starlette.requests import Request
from starlette.types import ASGIApp, Receive, Scope, Send

logger = logging.getLogger(__name__)

EXEMPT_PATHS: Final[tuple[str, str, str]] = ("/health", "/ready", "/metrics")
FALLBACK_KEY: Final[str] = "127.0.0.1"
DEFAULT_STORAGE_URI: Final[str] = "memory://"


def _parse_limit(value: str) -> RateLimitItem:
    try:
        return parse(value)
    except ValueError as exc:
        raise ValueError(f"invalid rate limit {value!r}") from exc


def build_limiter(
    default_limit: str,
    storage_uri: str = DEFAULT_STORAGE_URI,
    key_prefix: str = "",
    key_func: Callable[[Request], str] = get_remote_address,
) -> Limiter:
    _parse_limit(default_limit)
    return Limiter(
        key_func=key_func,
        default_limits=[default_limit],
        headers_enabled=True,
        storage_uri=storage_uri,
        key_prefix=key_prefix,
        in_memory_fallback=[default_limit],
    )


class RateLimitMiddleware(SlowAPIASGIMiddleware):
    def __init__(self, app: ASGIApp, mcp_path: str = "/mcp") -> None:
        super().__init__(app)
        self._mcp_path = mcp_path

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        path = scope.get("path") or ""
        if path in EXEMPT_PATHS or path == self._mcp_path or path.startswith(self._mcp_path + "/"):
            await self.app(scope, receive, send)

            return
        sent_start = False

        async def guarded_send(message: Any) -> None:
            nonlocal sent_start
            if message["type"] == "http.response.start":
                if sent_start:
                    return
                sent_start = True
            await send(message)

        await super().__call__(scope, receive, guarded_send)


def install_rate_limiting(app: FastAPI, limiter: Limiter, mcp_path: str = "/mcp") -> None:
    app.state.limiter = limiter
    app.add_middleware(RateLimitMiddleware, mcp_path=mcp_path)


class McpRateLimitMiddleware(Middleware):
    def __init__(
        self,
        limiter: Limiter,
        default_limit: str,
        tool_limits: dict[str, str] | None = None,
        key_func: Callable[[Any], str] = get_remote_address,
        key_prefix: str = "",
    ) -> None:
        self._limiter = limiter
        self._default_item = _parse_limit(default_limit)
        self._key_func = key_func
        self._key_prefix = key_prefix
        self._items: dict[str, RateLimitItem] = {}
        for name, value in (tool_limits or {}).items():
            self._items[name] = _parse_limit(value)

    async def on_call_tool(
        self,
        context: MiddlewareContext[mt.CallToolRequestParams],
        call_next: CallNext[mt.CallToolRequestParams, Any],
    ) -> Any:
        message = getattr(context, "message", None)
        tool_name = str(getattr(message, "name", "unknown"))
        request = getattr(
            getattr(getattr(context, "fastmcp_context", None), "request_context", None),
            "request",
            None,
        )
        key = FALLBACK_KEY if request is None else self._key_func(request)
        item = self._items.get(tool_name, self._default_item)
        identifiers = [key, tool_name]
        if self._key_prefix:
            identifiers = [self._key_prefix, *identifiers]
        try:
            allowed = self._limiter.limiter.hit(item, *identifiers)
        except Exception:
            logger.warning("Rate limit storage unreachable, letting the MCP call through")
            return await call_next(context)
        if not allowed:
            raise ToolError(f"rate_limited: Rate limit exceeded: {item}")
        return await call_next(context)

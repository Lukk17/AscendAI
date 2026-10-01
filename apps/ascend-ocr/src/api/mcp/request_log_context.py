from typing import Any

import mcp.types as mt
from fastmcp import Context
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext

from src.api.middleware.correlation_id import (
    bound_correlation_id,
    correlation_id_of,
    digest_of_mcp_session_id,
    mcp_request_log_context,
    new_correlation_id,
)


class McpRequestLogContextMiddleware(Middleware):
    async def on_request(
        self,
        context: MiddlewareContext[mt.Request[Any, Any]],
        call_next: CallNext[mt.Request[Any, Any], Any],
    ) -> Any:
        correlation_id, mcp_session_digest = _log_ids_of(context.fastmcp_context)

        with mcp_request_log_context(correlation_id, mcp_session_digest):
            return await call_next(context)


def _log_ids_of(fastmcp_context: Context | None) -> tuple[str, str | None]:
    if fastmcp_context is None or fastmcp_context.request_context is None:
        return bound_correlation_id() or new_correlation_id(), None

    carrying_request = fastmcp_context.request_context.request
    carried_id = correlation_id_of(carrying_request.scope) if carrying_request is not None else None

    return carried_id or new_correlation_id(), digest_of_mcp_session_id(fastmcp_context.session_id)

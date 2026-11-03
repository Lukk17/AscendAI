import logging
from typing import Any

import mcp.types as mt
from fastmcp.exceptions import ToolError
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext

from ascend_python_common.errors.codes import INTERNAL_FIXED_DETAIL
from ascend_python_common.errors.refusals import report
from ascend_python_common.errors.registry import ErrorEntry, ErrorRegistry, resolve_detail

logger = logging.getLogger(__name__)


class McpRefusalMiddleware(Middleware):
    def __init__(self, registry: ErrorRegistry) -> None:
        self._registry = registry

    async def on_call_tool(
        self,
        context: MiddlewareContext[mt.CallToolRequestParams],
        call_next: CallNext[mt.CallToolRequestParams, Any],
    ) -> Any:
        message = getattr(context, "message", None)
        tool_name = str(getattr(message, "name", "unknown"))
        try:
            return await call_next(context)
        except Exception as exc:
            mapped = _registered_error(exc, self._registry)
            if mapped is not None:
                original, entry = mapped
                detail = resolve_detail(entry, original)
                report(
                    entry.code.code,
                    detail,
                    entry.code.status,
                    "mcp",
                    tool_name,
                    original,
                    entry.expected,
                )
                raise ToolError(f"{entry.code.code}: {detail}", log_level=logging.DEBUG) from exc
            internal = self._registry.internal_code
            report(internal.code, INTERNAL_FIXED_DETAIL, internal.status, "mcp", tool_name, exc, False)
            raise ToolError(f"{internal.code}: {INTERNAL_FIXED_DETAIL}", log_level=logging.DEBUG) from exc


def _registered_error(
    exc: BaseException,
    registry: ErrorRegistry,
) -> tuple[BaseException, ErrorEntry] | None:
    current: BaseException | None = exc
    while current is not None:
        entry = registry.lookup(current)
        if entry is not None:
            return current, entry
        cause = current.__cause__
        current = cause if cause is not None else current.__context__
    return None


__all__ = ["McpRefusalMiddleware"]

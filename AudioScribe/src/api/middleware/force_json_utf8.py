from starlette.types import ASGIApp, Scope, Receive, Send, Message


class ForceJSONUTF8Middleware:
    """
    Middleware to ensure Content-Type headers for JSON and SSE responses include 'charset=utf-8'.
    FastMCP's underlying Starlette app might miss this for some responses.
    """

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_wrapper(message: Message):
            if message["type"] == "http.response.start":
                # Normalize/ensure UTF-8 charset for JSON and SSE responses.
                # ASGI headers are a list of (key: bytes, value: bytes) tuples.
                raw_headers = list(message.get("headers", []))

                ct_index = None
                current_value = None
                for i, (k, v) in enumerate(raw_headers):
                    # Compare header name case-insensitively in bytes
                    if k.lower() == b"content-type":
                        ct_index = i
                        current_value = v
                        break

                def main_type_and_params(val: bytes) -> tuple[bytes, bytes]:
                    """Split content-type into main type and raw params (bytes)."""
                    if not val:
                        return b"", b""
                    parts = val.split(b";", 1)
                    if len(parts) == 1:
                        return parts[0].strip().lower(), b""
                    return parts[0].strip().lower(), parts[1].strip()

                def has_charset(params: bytes) -> bool:
                    return b"charset=" in params.lower()

                # Default behavior when the header is entirely missing: set JSON with UTF-8
                if ct_index is None:
                    raw_headers.append((b"content-type", b"application/json; charset=utf-8"))
                else:
                    main, params = main_type_and_params(current_value or b"")
                    # For application/json, enforce the exact value with charset to avoid client mis-decoding
                    if main == b"application/json":
                        raw_headers[ct_index] = (b"content-type", b"application/json; charset=utf-8")
                    # For SSE, ensure charset is present while preserving other parameters
                    elif main == b"text/event-stream" and not has_charset(params):
                        # Preserve any existing params order, just append charset at the end
                        new_val = b"text/event-stream; " + (params + b"; " if params else b"") + b"charset=utf-8"
                        raw_headers[ct_index] = (b"content-type", new_val)

                message["headers"] = raw_headers
            await send(message)

        await self.app(scope, receive, send_wrapper)

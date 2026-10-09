from collections.abc import MutableMapping
from typing import Any

from starlette.types import ASGIApp, Receive, Scope, Send

_FIXED_HEADERS: tuple[tuple[bytes, bytes], ...] = (
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"referrer-policy", b"strict-origin-when-cross-origin"),
    (b"permissions-policy", b"camera=(), microphone=(), geolocation=()"),
    (
        b"content-security-policy",
        b"default-src 'none'; frame-ancestors 'none'; base-uri 'none'",
    ),
)


class SecurityHeadersMiddleware:
    def __init__(self, app: ASGIApp, hsts_max_age_seconds: int) -> None:
        self.app = app
        self._headers = (
            *_FIXED_HEADERS,
            (
                b"strict-transport-security",
                f"max-age={hsts_max_age_seconds}; includeSubDomains; preload".encode("ascii"),
            ),
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)

            return

        async def send_with_headers(message: MutableMapping[str, Any]) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.setdefault("headers", []))
                existing_names = {name for name, _ in headers}
                for name, value in self._headers:
                    if name not in existing_names:
                        headers.append((name, value))
                message["headers"] = headers

            await send(message)

        await self.app(scope, receive, send_with_headers)


__all__ = ["SecurityHeadersMiddleware"]

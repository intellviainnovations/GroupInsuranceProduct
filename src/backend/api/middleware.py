"""ASGI middleware: request context, security headers, generic 500s, access log, throttling.

Written as plain ASGI (not BaseHTTPMiddleware) so context variables and exceptions behave
predictably. ``RequestContextMiddleware`` must be the outermost user middleware so that every
response, including throttled and failed ones, carries the correlation id and the headers.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable

from starlette.datastructures import Headers, MutableHeaders
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from backend.platform.errors import MSG_INTERNAL, MSG_TOO_MANY_REQUESTS, error_body
from backend.platform.request_context import (
    CORRELATION_HEADER,
    accept_or_generate,
    set_correlation_id,
)

logger = logging.getLogger("backend.access")

# Strict policy for a JSON API: nothing may load, nothing may frame it.
API_CSP = "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
# Interactive docs (dev mode only) load Swagger UI / ReDoc from a CDN.
DOCS_CSP = (
    "default-src 'none'; script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; img-src 'self' data: "
    "https://fastapi.tiangolo.com https://cdn.redoc.ly; connect-src 'self'; "
    "worker-src blob:; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
)
DOCS_PATHS = frozenset({"/docs", "/redoc", "/docs/oauth2-redirect"})
_FINGERPRINT_HEADERS = ("server", "x-powered-by")


def apply_security_headers(headers: MutableHeaders, path: str, *, dev_docs_allowed: bool) -> None:
    headers["X-Content-Type-Options"] = "nosniff"
    headers["Referrer-Policy"] = "no-referrer"
    headers["Cache-Control"] = "no-store"
    headers["X-Frame-Options"] = "DENY"
    csp = DOCS_CSP if dev_docs_allowed and path in DOCS_PATHS else API_CSP
    headers["Content-Security-Policy"] = csp
    for name in _FINGERPRINT_HEADERS:
        if name in headers:
            del headers[name]


class RequestContextMiddleware:
    def __init__(self, app: ASGIApp, *, production: bool) -> None:
        self.app = app
        self.production = production

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        correlation_id = accept_or_generate(Headers(scope=scope).get(CORRELATION_HEADER))
        set_correlation_id(correlation_id)
        path: str = scope["path"]
        started = False
        status = 0
        begin = time.perf_counter()

        async def send_wrapper(message: Message) -> None:
            nonlocal started, status
            if message["type"] == "http.response.start":
                started = True
                status = message["status"]
                message.setdefault("headers", [])
                headers = MutableHeaders(scope=message)
                headers[CORRELATION_HEADER] = correlation_id
                apply_security_headers(headers, path, dev_docs_allowed=not self.production)
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception as exc:
            # Details (type and stack locations only) go to the protected log, never the client.
            logger.error(
                "unhandled exception",
                exc_info=(type(exc), exc, exc.__traceback__),
                extra={"method": scope["method"], "path": path},
            )
            if started:
                raise
            status = 500
            await JSONResponse(error_body(MSG_INTERNAL), status_code=500)(
                scope, receive, send_wrapper
            )
        finally:
            logger.info(
                "request",
                extra={
                    "method": scope["method"],
                    "path": path,
                    "status": status,
                    "duration_ms": round((time.perf_counter() - begin) * 1000, 1),
                },
            )


class ThrottleMiddleware:
    """Fixed-window request limit per client address, held in process memory.

    Limits are per process and keyed on the socket peer address. Behind the bank's reverse
    proxy that address is the proxy, so the proxy/WAF remains the primary control (C-28).
    """

    _MAX_TRACKED = 10_000

    def __init__(
        self,
        app: ASGIApp,
        *,
        max_requests: int,
        window_seconds: int,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.app = app
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.clock = clock
        self._windows: dict[str, tuple[float, int]] = {}

    def _retry_after(self, key: str) -> int | None:
        """Count this request; return seconds to wait if the client is over the limit."""
        now = self.clock()
        start, count = self._windows.get(key, (now, 0))
        if now - start >= self.window_seconds:
            start, count = now, 0
        count += 1
        self._windows[key] = (start, count)
        if len(self._windows) > self._MAX_TRACKED:
            self._prune(now)
        if count > self.max_requests:
            return max(1, int(start + self.window_seconds - now) + 1)
        return None

    def _prune(self, now: float) -> None:
        self._windows = {k: v for k, v in self._windows.items() if now - v[0] < self.window_seconds}

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        client = scope.get("client")
        retry_after = self._retry_after(client[0] if client else "unknown")
        if retry_after is None:
            await self.app(scope, receive, send)
            return
        response = JSONResponse(
            error_body(MSG_TOO_MANY_REQUESTS),
            status_code=429,
            headers={"Retry-After": str(retry_after)},
        )
        await response(scope, receive, send)

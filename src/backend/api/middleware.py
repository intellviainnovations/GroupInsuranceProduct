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
        # None means no outcome is known (cancelled before any response was sent).
        status: int | None = None
        aborted = False
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
            # Whatever status was already sent, the request failed: never log it as a success.
            status = 500
            if started:
                aborted = True
                raise
            await JSONResponse(error_body(MSG_INTERNAL), status_code=500)(
                scope, receive, send_wrapper
            )
        except BaseException:
            # Cancellation (e.g. client disconnect) or interpreter exit: not a success, and any
            # status already sent says nothing about the outcome.
            aborted = True
            status = None
            raise
        finally:
            logger.info(
                "request",
                extra={
                    "method": scope["method"],
                    "path": path,
                    "status": status,
                    "aborted": aborted,
                    "duration_ms": round((time.perf_counter() - begin) * 1000, 1),
                },
            )


class ThrottleMiddleware:
    """Fixed-window request limit per client key, held in process memory.

    The key is ``scope["client"][0]``, the peer address as ASGI reports it. Under uvicorn that
    value may have been rewritten from proxy headers by uvicorn (its proxy-header handling applies
    to peers listed in ``--forwarded-allow-ips``) and is the proxy's address when it has not, so
    the proxy/WAF remains the primary control (C-28). Limits are per process.

    The key table is bounded: at most ``max_tracked`` keys are held. Entries are kept in the order
    their window started, so expired entries sit at the front and are dropped from there (at most
    once per window); when the table is still full, the oldest entry is evicted to admit a new key.
    """

    _MAX_TRACKED = 10_000

    def __init__(
        self,
        app: ASGIApp,
        *,
        max_requests: int,
        window_seconds: int,
        clock: Callable[[], float] = time.monotonic,
        max_tracked: int = _MAX_TRACKED,
    ) -> None:
        if max_tracked < 1:
            raise ValueError("max_tracked must be at least 1")
        self.app = app
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.clock = clock
        self.max_tracked = max_tracked
        # key -> (window start, count). Insertion order == window-start order (oldest first).
        self._windows: dict[str, tuple[float, int]] = {}
        self._last_prune = clock()

    def _retry_after(self, key: str) -> int | None:
        """Count this request; return seconds to wait if the client is over the limit."""
        now = self.clock()
        if now - self._last_prune >= self.window_seconds:
            self._prune(now)
        entry = self._windows.get(key)
        if entry is None or now - entry[0] >= self.window_seconds:
            # New window for this key: (re)insert at the end to keep window-start order.
            self._windows.pop(key, None)
            while len(self._windows) >= self.max_tracked:
                del self._windows[next(iter(self._windows))]
            start, count = now, 0
        else:
            start, count = entry
        count += 1
        self._windows[key] = (start, count)
        if count > self.max_requests:
            return max(1, int(start + self.window_seconds - now) + 1)
        return None

    def _prune(self, now: float) -> None:
        """Drop expired entries from the front (oldest first); stops at the first live one."""
        self._last_prune = now
        windows = self._windows
        while windows:
            oldest = next(iter(windows))
            if now - windows[oldest][0] < self.window_seconds:
                break
            del windows[oldest]

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

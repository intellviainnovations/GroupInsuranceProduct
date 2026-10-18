"""Generic client-facing error bodies. Details go to the protected logs, never to the client.

Outside ``/api`` the body is the scaffold's ``{error, correlation_id}``. The staff API adds a
stable ``code`` and optional ``fields`` (``docs/contracts/staff-api.md``), additively.
"""

from __future__ import annotations

from typing import Any

from backend.platform.request_context import get_correlation_id

API_PREFIX = "/api/"

MSG_INTERNAL = "An internal error occurred."
MSG_INVALID_REQUEST = "The request is invalid."
MSG_NOT_FOUND = "Not found."
MSG_METHOD_NOT_ALLOWED = "Method not allowed."
MSG_TOO_MANY_REQUESTS = "Too many requests."
MSG_GENERIC_HTTP = "The request could not be processed."

_HTTP_MESSAGES = {
    400: MSG_INVALID_REQUEST,
    404: MSG_NOT_FOUND,
    405: MSG_METHOD_NOT_ALLOWED,
    422: MSG_INVALID_REQUEST,
    429: MSG_TOO_MANY_REQUESTS,
    500: MSG_INTERNAL,
}

# Default API error code for a bare HTTP status.
_HTTP_CODES = {
    400: "VALIDATION_FAILED",
    401: "UNAUTHENTICATED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    405: "VALIDATION_FAILED",
    409: "INVALID_STATE",
    422: "VALIDATION_FAILED",
    429: "RATE_LIMITED",
    503: "SERVICE_UNAVAILABLE",
}


def message_for_status(status_code: int) -> str:
    return _HTTP_MESSAGES.get(status_code, MSG_GENERIC_HTTP)


def code_for_status(status_code: int) -> str:
    return _HTTP_CODES.get(status_code, "INTERNAL")


def is_api_path(path: str) -> bool:
    return path.startswith(API_PREFIX)


def error_body(
    message: str, code: str | None = None, fields: list[dict[str, str]] | None = None
) -> dict[str, Any]:
    body: dict[str, Any] = {"error": message, "correlation_id": get_correlation_id()}
    if code is not None:
        body["code"] = code
    if fields:
        body["fields"] = fields
    return body

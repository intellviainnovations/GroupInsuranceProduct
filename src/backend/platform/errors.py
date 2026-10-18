"""Generic client-facing error bodies. Details go to the protected logs, never to the client."""

from __future__ import annotations

from backend.platform.request_context import get_correlation_id

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


def message_for_status(status_code: int) -> str:
    return _HTTP_MESSAGES.get(status_code, MSG_GENERIC_HTTP)


def error_body(message: str) -> dict[str, str | None]:
    return {"error": message, "correlation_id": get_correlation_id()}

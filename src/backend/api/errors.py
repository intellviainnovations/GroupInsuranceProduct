"""Exception handlers that map framework errors to generic bodies with a correlation id.

Outside ``/api`` bodies stay ``{error, correlation_id}``. Under ``/api`` they add the contract's
stable ``code`` and, for validation, ``fields`` (JSON paths and codes, never submitted values).
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import JSONResponse

from backend.domain.repositories import BackendUnavailable, VersionConflict
from backend.platform.errors import (
    MSG_INVALID_REQUEST,
    code_for_status,
    error_body,
    is_api_path,
    message_for_status,
)
from backend.services.common import ServiceError

logger = logging.getLogger("backend.api")

# Generic, safe text per code; the UI maps codes to its own wording.
_CODE_MESSAGES = {
    "VALIDATION_FAILED": "The request is invalid.",
    "UNAUTHENTICATED": "Sign-in required.",
    "LOGIN_FAILED": "Sign-in failed.",
    "CSRF_FAILED": "The request could not be verified.",
    "FORBIDDEN": "Not allowed.",
    "MAKER_CANNOT_CHECK": "You cannot decide your own request.",
    "NOT_FOUND": "Not found.",
    "CUSTOMER_NOT_FOUND": "No customer found for this number.",
    "INVALID_STATE": "This action is not allowed in the current state.",
    "VERSION_CONFLICT": "The record changed; reload and try again.",
    "IDEMPOTENCY_KEY_REUSED": "The request key was already used for a different request.",
    "IDEMPOTENCY_IN_PROGRESS": "The same request is still being processed.",
    "PREMIUM_MISMATCH": "The insurer's premium differs from the plan rate.",
    "CONSENT_REQUIRED": "Customer consent is required.",
    "ACCOUNT_NOT_ELIGIBLE": "The debit account cannot be used.",
    "POSTING_UNRESOLVED": "An earlier payment is not resolved yet.",
    "CBS_UNAVAILABLE": "CBS data not available, try again.",
    "AUTH_UNAVAILABLE": "Sign-in is not available, try again.",
    "SERVICE_UNAVAILABLE": "The service is not available, try again.",
    "RATE_LIMITED": "Too many requests.",
    "INTERNAL": "An internal error occurred.",
}

_PYDANTIC_CODES = {
    "missing": "REQUIRED",
    "string_too_long": "TOO_LONG",
    "too_long": "TOO_LONG",
    "string_pattern_mismatch": "INVALID_FORMAT",
    "extra_forbidden": "NOT_ALLOWED",
    "literal_error": "INVALID_CODE",
    "enum": "INVALID_CODE",
    "greater_than": "OUT_OF_RANGE",
    "greater_than_equal": "OUT_OF_RANGE",
    "less_than": "OUT_OF_RANGE",
    "less_than_equal": "OUT_OF_RANGE",
    "too_short": "REQUIRED",
    "string_too_short": "REQUIRED",
}


def api_error(
    status: int,
    code: str,
    fields: list[dict[str, str]] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    return JSONResponse(
        error_body(_CODE_MESSAGES.get(code, MSG_INVALID_REQUEST), code, fields),
        status_code=status,
        headers=headers,
    )


def _path(loc: tuple[Any, ...]) -> str:
    parts = list(loc)
    if parts and parts[0] in ("body", "query", "path", "header"):
        source = parts.pop(0)
        if source != "body":
            parts.insert(0, source)
    text = ""
    for part in parts:
        if isinstance(part, int):
            text += f"[{part}]"
        elif str(part).startswith(("function-", "constrained-", "union[")):
            continue
        else:
            text += ("." if text else "") + str(part)
    return (text or "body")[:100]


async def _http_exception(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StarletteHTTPException)  # noqa: S101 - narrows type for mypy
    if is_api_path(request.url.path):
        code = code_for_status(exc.status_code)
        return api_error(exc.status_code, code, headers=dict(exc.headers) if exc.headers else None)
    return JSONResponse(
        error_body(message_for_status(exc.status_code)),
        status_code=exc.status_code,
        headers=exc.headers,
    )


async def _validation_error(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)  # noqa: S101 - narrows type for mypy
    errors = exc.errors()
    # Log field locations only: submitted values may be personal data.
    locations = [".".join(str(part) for part in err["loc"]) for err in errors]
    logger.info("request validation failed", extra={"fields": locations})
    if not is_api_path(request.url.path):
        return JSONResponse(error_body(MSG_INVALID_REQUEST), status_code=422)
    for err in errors:
        loc = err["loc"]
        if len(loc) >= 2 and loc[0] == "header" and str(loc[1]).lower() == "x-csrf-token":
            return api_error(403, "CSRF_FAILED")
    fields = [
        {
            "field": _path(tuple(err["loc"])),
            "code": _PYDANTIC_CODES.get(err["type"], "INVALID_FORMAT"),
        }
        for err in errors[:100]
    ]
    return api_error(422, "VALIDATION_FAILED", fields)


async def _service_error(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, ServiceError)  # noqa: S101
    return api_error(exc.status, exc.code, exc.fields, exc.headers)


async def _version_conflict(_: Request, exc: Exception) -> JSONResponse:
    return api_error(409, "VERSION_CONFLICT")


async def _backend_unavailable(_: Request, exc: Exception) -> JSONResponse:
    logger.warning("data backend unavailable")
    return api_error(503, "SERVICE_UNAVAILABLE")


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(StarletteHTTPException, _http_exception)
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.add_exception_handler(ServiceError, _service_error)
    app.add_exception_handler(VersionConflict, _version_conflict)
    app.add_exception_handler(BackendUnavailable, _backend_unavailable)

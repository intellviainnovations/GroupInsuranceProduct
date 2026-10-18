"""Exception handlers that map framework errors to generic bodies with a correlation id."""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import JSONResponse

from backend.platform.errors import MSG_INVALID_REQUEST, error_body, message_for_status

logger = logging.getLogger("backend.api")


async def _http_exception(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StarletteHTTPException)  # noqa: S101 - narrows type for mypy
    return JSONResponse(
        error_body(message_for_status(exc.status_code)),
        status_code=exc.status_code,
        headers=exc.headers,
    )


async def _validation_error(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)  # noqa: S101 - narrows type for mypy
    # Log field locations only: submitted values may be personal data.
    locations = [".".join(str(part) for part in err["loc"]) for err in exc.errors()]
    logger.info("request validation failed", extra={"fields": locations})
    return JSONResponse(error_body(MSG_INVALID_REQUEST), status_code=422)


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(StarletteHTTPException, _http_exception)
    app.add_exception_handler(RequestValidationError, _validation_error)

"""Request dependencies: container, Origin check, session, CSRF and role gates (deny by default)."""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Annotated, Any

from fastapi import Depends, Header, Request

from backend.bootstrap import Container
from backend.domain.model import Role
from backend.platform.request_context import get_correlation_id
from backend.services.auth import SessionContext
from backend.services.common import Actor, ServiceError

SESSION_COOKIE = "gip_session"
_SESSION_ID = re.compile(r"^[A-Za-z0-9_-]{20,100}$")
UNSAFE = frozenset({"POST", "PUT", "PATCH", "DELETE"})
ALL_ROLES = tuple(Role)


def container(request: Request) -> Container:
    found: Container = request.app.state.container
    return found


def client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def origin_check(request: Request) -> None:
    """Unsafe methods: an Origin header, when present, must be an allowed origin."""
    if request.method not in UNSAFE:
        return
    origin = request.headers.get("origin")
    if origin is not None and origin not in container(request).settings.allowed_origin_set:
        raise ServiceError(403, "CSRF_FAILED")


def json_body(request: Request) -> None:
    """Login and OTP: JSON only (forces a CORS preflight; no CORS is enabled)."""
    media = request.headers.get("content-type", "").split(";")[0].strip().lower()
    if media != "application/json":
        raise ServiceError(422, "VALIDATION_FAILED")


def cookie_session_id(request: Request) -> str | None:
    value = request.cookies.get(SESSION_COOKIE)
    return value if value is not None and _SESSION_ID.fullmatch(value) else None


def session_context(request: Request) -> SessionContext:
    session_id = cookie_session_id(request)
    if session_id is None:
        raise ServiceError(401, "UNAUTHENTICATED")
    ctx = container(request).auth.resolve(
        session_id, client_ip=client_ip(request), correlation_id=get_correlation_id()
    )
    if ctx is None:
        raise ServiceError(401, "UNAUTHENTICATED")
    return ctx


CsrfHeader = Annotated[
    str,
    Header(alias="X-CSRF-Token", min_length=43, max_length=64, pattern=r"^[A-Za-z0-9_-]+$"),
]


def csrf_session_context(
    request: Request,
    ctx: Annotated[SessionContext, Depends(session_context)],
    x_csrf_token: CsrfHeader,
) -> SessionContext:
    if not container(request).deps.keys.check_csrf(ctx.session_id, x_csrf_token):
        raise ServiceError(403, "CSRF_FAILED")
    return ctx


def _gate(request: Request, ctx: SessionContext, allowed: tuple[Role, ...]) -> Actor:
    actor = ctx.actor
    if not actor.has(*allowed):
        container(request).auth.audit_denied(actor, f"{request.method} {request.url.path}")
        raise ServiceError(403, "FORBIDDEN")
    return actor


def roles(*allowed: Role) -> Callable[..., Actor]:
    """Safe method gate: signed in with one of the roles (ANY_ROLE when none are given)."""
    wanted = allowed or ALL_ROLES

    def dependency(
        request: Request, ctx: Annotated[SessionContext, Depends(session_context)]
    ) -> Actor:
        return _gate(request, ctx, wanted)

    return dependency


def roles_csrf(*allowed: Role) -> Callable[..., Actor]:
    """Unsafe method gate: session, CSRF token, then role."""
    wanted = allowed or ALL_ROLES

    def dependency(
        request: Request, ctx: Annotated[SessionContext, Depends(csrf_session_context)]
    ) -> Actor:
        return _gate(request, ctx, wanted)

    return dependency


def error_responses(*codes: int) -> dict[int | str, dict[str, Any]]:
    from backend.api.v1.schemas import Error

    return {code: {"model": Error} for code in codes}

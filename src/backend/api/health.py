"""Liveness and readiness endpoints (unauthenticated by design: probes carry no credentials)."""

from __future__ import annotations

import logging
from collections.abc import Callable

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

logger = logging.getLogger("backend.api.health")

router = APIRouter(tags=["health"])

# Later tasks register checks (database, workers, ...) here by name.
ReadinessCheck = Callable[[], bool]


class HealthResponse(BaseModel):
    status: str


class ReadyResponse(BaseModel):
    ready: bool
    checks: dict[str, str]


@router.get("/health")
async def health() -> HealthResponse:
    """Liveness: the process is up and serving requests."""
    return HealthResponse(status="ok")


@router.get("/ready", response_model=ReadyResponse)
def ready(request: Request) -> ReadyResponse | JSONResponse:
    """Readiness: every registered check passes. No checks exist yet, so it is ready."""
    checks: dict[str, ReadinessCheck] = request.app.state.readiness_checks
    results: dict[str, str] = {}
    for name, check in checks.items():
        try:
            passed = check()
        except Exception:
            logger.warning("readiness check raised", extra={"check": name})
            passed = False
        results[name] = "ok" if passed else "fail"
    body = ReadyResponse(ready=all(v == "ok" for v in results.values()), checks=results)
    if body.ready:
        return body
    return JSONResponse(body.model_dump(), status_code=503)

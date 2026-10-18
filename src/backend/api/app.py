"""Application factory.

Run (production mode is the default; the server header is switched off on the command line)::

    uvicorn --factory backend.api.app:create_app --no-server-header --app-dir src \\
        --host 127.0.0.1 --port 8000

Local development::

    ENV=dev uvicorn --factory backend.api.app:create_app --no-server-header --app-dir src --reload
"""

from __future__ import annotations

from fastapi import FastAPI

from backend.api import health
from backend.api.errors import register_exception_handlers
from backend.api.middleware import RequestContextMiddleware, ThrottleMiddleware
from backend.platform.config import Settings, load_settings
from backend.platform.logging import configure_logging


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the app. With no argument, settings come from the environment and fail fast."""
    cfg = settings if settings is not None else load_settings()
    configure_logging(cfg.log_level)

    # Production: no interactive docs and no schema endpoint.
    docs_url = None if cfg.production else "/docs"
    redoc_url = None if cfg.production else "/redoc"
    openapi_url = None if cfg.production else "/openapi.json"
    app = FastAPI(
        title="GroupInsuranceProduct",
        debug=False,
        docs_url=docs_url,
        redoc_url=redoc_url,
        openapi_url=openapi_url,
    )
    app.state.settings = cfg
    app.state.readiness_checks = {}

    register_exception_handlers(app)
    app.include_router(health.router)

    # add_middleware puts the last one added outermost: context first, throttle inside it.
    if cfg.throttle_enabled:
        app.add_middleware(
            ThrottleMiddleware,
            max_requests=cfg.throttle_max_requests,
            window_seconds=cfg.throttle_window_seconds,
        )
    app.add_middleware(RequestContextMiddleware, production=cfg.production)
    return app

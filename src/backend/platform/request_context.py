"""Per-request context: the correlation id carried through logs and responses."""

from __future__ import annotations

import re
import uuid
from contextvars import ContextVar

CORRELATION_HEADER = "X-Correlation-ID"

# Strict whitelist: 8 to 40 characters (the audit and history columns hold 40).
_CORRELATION_PATTERN = re.compile(r"[A-Za-z0-9_-]{8,40}")

_correlation_id: ContextVar[str | None] = ContextVar("correlation_id", default=None)


def new_correlation_id() -> str:
    return str(uuid.uuid4())


def accept_or_generate(inbound: str | None) -> str:
    """Return the inbound id only if it matches the strict pattern, else a fresh UUID4."""
    if inbound is not None and _CORRELATION_PATTERN.fullmatch(inbound):
        return inbound
    return new_correlation_id()


def set_correlation_id(value: str) -> None:
    _correlation_id.set(value)


def get_correlation_id() -> str | None:
    return _correlation_id.get()

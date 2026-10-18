"""Structured single-line JSON logging with redaction of secret-like fields.

Rules: no personal data in log events (callers log identifiers, not values), and any field
whose name looks secret-like is replaced before it reaches a handler. Message text is not
scanned, so never interpolate secrets or personal data into messages.
"""

from __future__ import annotations

import json
import logging
import re
import sys
import traceback
from datetime import UTC, datetime
from typing import Any

from backend.platform.request_context import get_correlation_id

REDACTED = "[REDACTED]"
_SECRET_NAME = re.compile(
    r"pass(word|wd|phrase)?|token|secret|authorization|api[_-]?key|cookie|credential"
    r"|private[_-]?key",
    re.IGNORECASE,
)
# Attributes every LogRecord has; anything else was passed through ``extra=``.
_STANDARD_ATTRS = frozenset(logging.LogRecord("", 0, "", 0, "", None, None).__dict__) | {
    "message",
    "asctime",
    "taskName",
}


def redact(value: Any, key: str | None = None) -> Any:
    """Return value with secret-named mapping entries replaced; recurse into containers."""
    if key is not None and _SECRET_NAME.search(key):
        return REDACTED
    if isinstance(value, dict):
        return {str(k): redact(v, str(k)) for k, v in value.items()}
    if isinstance(value, list | tuple | set | frozenset):
        return [redact(v) for v in value]
    return value


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        event: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(
                timespec="milliseconds"
            ),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "correlation_id": get_correlation_id(),
        }
        for key, value in record.__dict__.items():
            if key not in _STANDARD_ATTRS and key not in event:
                event[key] = redact(value, key)
        if record.exc_info and record.exc_info[1] is not None:
            # Exception type and stack locations only: exception text may hold personal data.
            exc_type, _, exc_tb = record.exc_info
            event["exc_type"] = exc_type.__name__ if exc_type else None
            event["stack"] = [
                f"{frame.filename}:{frame.lineno}:{frame.name}"
                for frame in traceback.extract_tb(exc_tb)
            ]
        return json.dumps(event, default=str, ensure_ascii=True, separators=(",", ":"))


def configure_logging(level: str = "INFO", stream: Any = None) -> None:
    """Route all logging (including uvicorn error logs) through one JSON handler on stderr."""
    handler = logging.StreamHandler(stream if stream is not None else sys.stderr)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
    for name in ("uvicorn", "uvicorn.error"):
        named = logging.getLogger(name)
        named.handlers.clear()
        named.propagate = True
    # The request log comes from backend.api.middleware (no client address, no query string);
    # uvicorn's own access log is silenced to avoid duplicates.
    access = logging.getLogger("uvicorn.access")
    access.handlers.clear()
    access.propagate = False

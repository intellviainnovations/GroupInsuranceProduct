"""Structured single-line JSON logging with redaction of secret-like fields.

Rules: no personal data in log events (callers log identifiers, not values). Before anything
reaches a handler:

* a field whose name looks secret-like (see ``is_secret_name``) is replaced wholesale;
* string values (and the message) have credentials embedded in URLs (the part before the host)
  and ``Bearer <token>`` strings scrubbed;
* values that are not JSON-native (str, int, float, bool, None, and lists/dicts of those) are
  logged as their type name only, so an object's ``repr`` can never reach the log.

Callers must still not interpolate secrets or personal data into message text: the scrubber is a
safety net for the common URL and bearer shapes, not a guarantee. ``DEBUG`` is for local
development only and must not be used in production: third-party libraries log request details
at that level. HTTP client libraries (httpx, httpcore, hpack) are held at WARNING or above
regardless of the configured level so outbound URLs and query strings never reach the log.
"""

from __future__ import annotations

import json
import logging
import math
import re
import sys
import traceback
from datetime import UTC, datetime
from typing import Any

from backend.platform.request_context import get_correlation_id

REDACTED = "[REDACTED]"
_MAX_DEPTH = 8
_TRUNCATED = "[TRUNCATED]"

# Long, unambiguous names: matched as substrings of the raw name ...
_SECRET_NAME = re.compile(
    r"pass(word|wd|phrase)?|token|secret|authorization|api[_-]?key|cookie|credential"
    r"|private[_-]?key",
    re.IGNORECASE,
)
# ... and as substrings of the name with separators removed (database_url, signing-key, ...).
_SECRET_COMPACT = re.compile(r"databaseurl|signingkey|accesskey|privatekey|apikey|sessionid")
# Short names: matched only as a whole word, so "shipping" or "author" are not redacted.
_SECRET_WORDS = frozenset(
    {"dsn", "otp", "pin", "pwd", "session", "sid", "auth", "jwt", "bearer", "cvv", "key"}
)
_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_NON_ALNUM = re.compile(r"[^A-Za-z0-9]+")

# scheme://userinfo@host. The userinfo may itself contain an unencoded "@", so match up to the
# last "@" of the authority part (everything before the first "/", "?" or "#").
_URL_USERINFO = re.compile(r"(?P<scheme>[A-Za-z][A-Za-z0-9+.\-]*://)[^\s/?#]*@")
_BEARER = re.compile(r"\b(?P<word>Bearer)\s+[A-Za-z0-9._~+/=\-]+", re.IGNORECASE)

# Attributes every LogRecord has; anything else was passed through ``extra=``.
_STANDARD_ATTRS = frozenset(logging.LogRecord("", 0, "", 0, "", None, None).__dict__) | {
    "message",
    "asctime",
    "taskName",
}
# Libraries that log request URLs, query strings or headers at INFO/DEBUG.
_QUIET_LOGGERS = ("httpx", "httpcore", "hpack")


def is_secret_name(name: str) -> bool:
    """True if a field name looks secret-like (substring, compacted, or whole-word match)."""
    if _SECRET_NAME.search(name):
        return True
    words = [w.lower() for w in _NON_ALNUM.split(_CAMEL_BOUNDARY.sub("_", name)) if w]
    return bool(_SECRET_COMPACT.search("".join(words))) or any(w in _SECRET_WORDS for w in words)


def scrub_text(text: str) -> str:
    """Remove URL userinfo and bearer tokens from a string."""
    text = _URL_USERINFO.sub(lambda m: f"{m.group('scheme')}{REDACTED}@", text)
    return _BEARER.sub(lambda m: f"{m.group('word')} {REDACTED}", text)


def _key_text(key: object) -> str:
    if isinstance(key, str):
        return key
    return str(key) if isinstance(key, int) else type(key).__name__


def redact(value: Any, key: str | None = None, _depth: int = 0) -> Any:
    """Return a JSON-safe copy of value: secret-named entries and secret-shaped strings removed.

    Containers are walked; any other non-JSON-native object becomes its type name only.
    """
    if key is not None and is_secret_name(key):
        return REDACTED
    if isinstance(value, str):
        return scrub_text(value)
    if value is None or isinstance(value, bool | int):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else "float"
    if isinstance(value, dict | list | tuple | set | frozenset):
        if _depth >= _MAX_DEPTH:
            return _TRUNCATED
        if isinstance(value, dict):
            return {
                _key_text(k): redact(v, k if isinstance(k, str) else None, _depth + 1)
                for k, v in value.items()
            }
        return [redact(v, None, _depth + 1) for v in value]
    return type(value).__name__


def _type_name(value: object) -> str:
    return type(value).__name__


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        event: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(
                timespec="milliseconds"
            ),
            "level": record.levelname,
            "logger": record.name,
            "message": scrub_text(record.getMessage()),
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
        return json.dumps(event, default=_type_name, ensure_ascii=True, separators=(",", ":"))


def configure_logging(level: str = "INFO", stream: Any = None) -> None:
    """Route all logging (including uvicorn error logs) through one JSON handler on stderr.

    ``DEBUG`` is for local development only; never run production at DEBUG.
    """
    handler = logging.StreamHandler(stream if stream is not None else sys.stderr)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
    # Never below WARNING, whatever the configured level: these log outbound URLs and queries.
    quiet = max(root.level, logging.WARNING)
    for name in _QUIET_LOGGERS:
        logging.getLogger(name).setLevel(quiet)
    for name in ("uvicorn", "uvicorn.error"):
        named = logging.getLogger(name)
        named.handlers.clear()
        named.propagate = True
    # The request log comes from backend.api.middleware (no client address, no query string);
    # uvicorn's own access log is silenced to avoid duplicates.
    access = logging.getLogger("uvicorn.access")
    access.handlers.clear()
    access.propagate = False

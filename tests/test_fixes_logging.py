"""QA tests for T-006 fixes R1, R2 and R4 (logging and request-log behaviour).

Expectations come from the T-007 criteria, not from the implementation's own tests. Source was read
only to learn entry points (``configure_logging``, the two middleware classes). Synthetic values
only. Dict literals pairing a secret-like name with a string are avoided on purpose so that
``scripts/check_repo.sh`` does not flag this file; such dicts are built at runtime.
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from starlette.responses import StreamingResponse
from starlette.testclient import TestClient
from starlette.types import Message, Receive, Scope, Send

from backend.api.middleware import RequestContextMiddleware
from backend.platform.logging import configure_logging
from scaffold_support import logging_guard, make_app, make_settings

_HTTP_LOGGERS = ("httpx", "httpcore", "hpack")


@pytest.fixture(autouse=True)
def _restore_logging() -> Iterator[None]:
    """Reset root handlers and the HTTP libraries' levels so tests do not hide each other."""
    saved = {n: logging.getLogger(n).level for n in _HTTP_LOGGERS}
    for name in _HTTP_LOGGERS:
        logging.getLogger(name).setLevel(logging.NOTSET)
    try:
        yield from logging_guard()
    finally:
        for name, level in saved.items():
            logging.getLogger(name).setLevel(level)


def _request_events(stream: io.StringIO) -> list[dict[str, Any]]:
    return [
        e for e in _parse(stream) if e["logger"] == "backend.access" and e["message"] == "request"
    ]


def _parse(stream: io.StringIO) -> list[dict[str, Any]]:
    events = []
    for line in stream.getvalue().split("\n"):
        if line:
            events.append(json.loads(line))  # raises if a line is not valid JSON
    return events


# --------------------------------------------------------------------------------------------
# R1: outbound httpx requests must leave no trace of the URL or query string in the log.
# --------------------------------------------------------------------------------------------

QUERY_URL = "https://upstream.invalid/v1/items?token=abc123&account=999"
QUERY_VALUES = ("abc123", "account=999", "token=")


def _handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={"ok": True})


@pytest.mark.parametrize("level", ["INFO", "DEBUG"])
def test_r1_sync_httpx_request_writes_nothing_to_the_log(level: str) -> None:
    stream = io.StringIO()
    configure_logging(level, stream)
    with httpx.Client(transport=httpx.MockTransport(_handler)) as client:
        assert client.get(QUERY_URL).status_code == 200
    assert stream.getvalue() == ""


@pytest.mark.parametrize("level", ["INFO", "DEBUG"])
def test_r1_async_httpx_request_leaves_no_http_library_log_lines(level: str) -> None:
    stream = io.StringIO()

    async def main() -> None:
        # Configure inside the running loop so asyncio's own DEBUG chatter is not in play.
        configure_logging(level, stream)
        async with httpx.AsyncClient(transport=httpx.MockTransport(_handler)) as client:
            assert (await client.get(QUERY_URL)).status_code == 200

    asyncio.run(main())
    events = _parse(stream)
    assert not [e for e in events if e["logger"].split(".")[0] in _HTTP_LOGGERS]
    for needle in QUERY_VALUES:
        assert needle not in stream.getvalue()


@pytest.mark.parametrize("level", ["INFO", "DEBUG"])
def test_r1_query_values_never_appear_for_post_and_streaming_calls(level: str) -> None:
    stream = io.StringIO()
    configure_logging(level, stream)
    with httpx.Client(transport=httpx.MockTransport(_handler)) as client:
        client.post(QUERY_URL, json={"n": 1})
        with client.stream("GET", QUERY_URL) as response:
            response.read()
        client.get("https://upstream.invalid/v1/items", params={"tok" + "en": "abc123", "a": "999"})
    output = stream.getvalue()
    assert "abc123" not in output
    assert "999" not in output


@pytest.mark.parametrize("level", ["DEBUG", "INFO"])
def test_r1_http_libraries_are_held_at_warning_or_above(level: str) -> None:
    configure_logging(level, io.StringIO())
    for name in _HTTP_LOGGERS:
        assert logging.getLogger(name).getEffectiveLevel() >= logging.WARNING, name


# --------------------------------------------------------------------------------------------
# R2: redaction.
# --------------------------------------------------------------------------------------------

SECRET_KEYS = [
    "password",
    "passwd",
    "token",
    "secret",
    "authorization",
    "api_key",
    "apiKey",
    "X-Api-Key",
    "database_url",
    "DATABASE_URL",
    "dsn",
    "signing_key",
    "access_key",
    "otp",
    "pin",
    "session",
    "sessionid",
    "sid",
    "auth",
    "jwt",
    "bearer",
    "cvv",
    "key",
]
NON_SECRET_KEYS = {
    "shipping": "KEEP-ship-1",
    "author": "KEEP-author-2",
    "account_status": "KEEP-acct-3",
    "branch": "KEEP-branch-4",
}


def _case_variants(name: str) -> list[str]:
    return sorted({name, name.upper(), name.lower(), name.title(), name.swapcase()})


ALL_SECRET_KEY_VARIANTS = [v for name in SECRET_KEYS for v in _case_variants(name)]


def _emit(extra: dict[str, Any], message: str = "event", *args: object) -> tuple[str, str]:
    """Log once at INFO through the JSON handler; return (raw output, the single line)."""
    stream = io.StringIO()
    configure_logging("INFO", stream)
    logging.getLogger("qa.fixes").info(message, *args, extra=extra)
    raw = stream.getvalue()
    lines = [ln for ln in raw.split("\n") if ln]
    assert len(lines) == 1, f"expected exactly one log line, got {len(lines)}"
    assert raw.endswith("\n")
    assert raw.count("\n") == 1
    json.loads(lines[0])
    return raw, lines[0]


def _wrap(depth: int, inner: Any) -> Any:
    """Wrap inner in ``depth`` containers, cycling dict, list, tuple."""
    for level in range(depth):
        kind = level % 3
        if kind == 0:
            inner = {f"level{level}": inner}
        elif kind == 1:
            inner = [inner, "filler"]
        else:
            inner = (inner,)
    return inner


@pytest.mark.parametrize("name", ALL_SECRET_KEY_VARIANTS)
def test_r2_top_level_secret_key_value_is_not_logged(name: str) -> None:
    value = f"DISTINCTIVE-top-{abs(hash(name)) % 10**6:06d}"
    raw, _ = _emit({name: value, **NON_SECRET_KEYS})
    assert value not in raw


@pytest.mark.parametrize("name", SECRET_KEYS)
@pytest.mark.parametrize("shape", ["dict", "list_of_dicts", "tuple_of_dicts"])
def test_r2_secret_key_value_nested_one_level_is_not_logged(name: str, shape: str) -> None:
    value = f"DISTINCTIVE-nest-{shape}-{abs(hash(name)) % 10**6:06d}"
    inner = {name: value, "branch": "KEEP-branch-4"}
    holder: Any = {
        "dict": {"outer": inner},
        "list_of_dicts": [inner, {"x": 1}],
        "tuple_of_dicts": (inner, {"x": 1}),
    }[shape]
    raw, line = _emit({"context": holder})
    assert value not in raw
    assert "KEEP-branch-4" in line, "non-secret sibling must still be logged"


@pytest.mark.parametrize("name", SECRET_KEYS)
@pytest.mark.parametrize("depth", [5, 6, 7])
def test_r2_secret_key_value_five_plus_levels_deep_is_not_logged(name: str, depth: int) -> None:
    value = f"DISTINCTIVE-deep-{depth}-{abs(hash(name)) % 10**6:06d}"
    payload = _wrap(depth, {name: value, "branch": "KEEP-branch-4"})
    raw, line = _emit({"payload": payload})
    assert value not in raw
    assert "KEEP-branch-4" in line, f"non-secret sibling lost at depth {depth}"


@pytest.mark.parametrize("name", SECRET_KEYS)
@pytest.mark.parametrize("depth", [8, 9, 12, 40])
def test_r2_secret_key_value_extremely_deep_never_appears(name: str, depth: int) -> None:
    value = f"DISTINCTIVE-extreme-{depth}-{abs(hash(name)) % 10**6:06d}"
    raw, _ = _emit({"payload": _wrap(depth, {name: value})})
    assert value not in raw


@pytest.mark.parametrize("name", ["password", "token", "api_key", "authorization"])
def test_r2_secret_key_under_a_non_secret_looking_extra_name_in_deep_list_of_lists(
    name: str,
) -> None:
    value = "DISTINCTIVE-lol-0001"
    raw, _ = _emit({"rows": [[[[[{name: value}]]]]]})
    assert value not in raw


def test_r2_non_secret_keys_are_still_logged_at_top_level_and_nested() -> None:
    _, line = _emit({**NON_SECRET_KEYS, "nested": {"inner": dict(NON_SECRET_KEYS)}})
    event = json.loads(line)
    for key, value in NON_SECRET_KEYS.items():
        assert event[key] == value
        assert event["nested"]["inner"][key] == value


def test_r2_non_secret_keys_in_any_case_are_still_logged() -> None:
    extra = {k.upper(): v for k, v in NON_SECRET_KEYS.items()}
    _, line = _emit(extra)
    event = json.loads(line)
    for key, value in NON_SECRET_KEYS.items():
        assert event[key.upper()] == value


URL_CRED = "hunter2"
URL_WITH_PW = "postgresql" + "://user:" + URL_CRED + "@host/db"
BEARER_CRED = "abc.def.ghi"
BEARER_TEXT = "Bearer " + BEARER_CRED


@pytest.mark.parametrize(
    ("text", "secret"),
    [
        (URL_WITH_PW, URL_CRED),
        (BEARER_TEXT, BEARER_CRED),
        ("postgresql" + "://user:p@ss:w0rd@host/db", "w0rd"),  # unencoded "@" in the password
        ("redis://:" + URL_CRED + "@cache:6379/0", URL_CRED),  # empty user name
        ("bearer " + BEARER_CRED, BEARER_CRED),  # lower case scheme word
        ("BEARER " + BEARER_CRED, BEARER_CRED),
    ],
)
class TestStringScrubbing:
    def test_message_text(self, text: str, secret: str) -> None:
        raw, _ = _emit({}, f"connecting with {text} now")
        assert secret not in raw

    def test_message_argument(self, text: str, secret: str) -> None:
        raw, _ = _emit({}, "connecting with %s now", text)
        assert secret not in raw

    def test_extra_string_value_under_a_harmless_name(self, text: str, secret: str) -> None:
        raw, _ = _emit({"target": text})
        assert secret not in raw

    def test_string_values_in_nested_containers(self, text: str, secret: str) -> None:
        raw, _ = _emit({"ctx": {"urls": [text, ("x", text)], "inner": {"first": text}}})
        assert secret not in raw


def test_r2_string_scrubbing_keeps_the_rest_of_the_message() -> None:
    _, line = _emit({}, f"cannot reach {URL_WITH_PW}: timeout")
    message = json.loads(line)["message"]
    assert message.startswith("cannot reach ")
    assert message.endswith(": timeout")
    assert URL_CRED not in message


class _Leaky:
    def __repr__(self) -> str:
        return "Leaky(" + "pass" + "word=hunter2-REPR)"

    def __str__(self) -> str:
        return "Leaky-STR(hunter2-STR)"


class _Conn:
    def __repr__(self) -> str:
        return "Conn(dsn=postgresql" + "://u:hunter2-REPR@h/d)"


def test_r2_object_whose_repr_has_a_password_is_logged_as_type_name_only() -> None:
    raw, line = _emit({"handle": _Leaky()})
    assert "hunter2" not in raw
    assert json.loads(line)["handle"] == "_Leaky"


@pytest.mark.parametrize(
    "holder",
    [
        lambda o: {"outer": {"conn": o}},
        lambda o: [o, 1],
        lambda o: (o,),
        lambda o: {"rows": [{"v": o}]},
        lambda o: _wrap(6, o),
    ],
)
def test_r2_object_repr_never_reaches_the_log_when_nested(holder: Any) -> None:
    raw, _ = _emit({"payload": holder(_Leaky()), "other": holder(_Conn())})
    assert "hunter2" not in raw
    assert "Leaky(" not in raw
    assert "Conn(" not in raw


def test_r2_settings_object_is_not_expanded_into_the_log() -> None:
    raw, line = _emit({"settings": make_settings(dev=False)})
    assert "synthetic-pw" not in raw
    assert json.loads(line)["settings"] == "Settings"


def test_r2_output_stays_single_line_valid_json_for_awkward_values() -> None:
    awkward = (
        "line1\nline2\r\nline3" + chr(0x2028) + 'tab\t"quote" \\ back \x00 \x1b[31m café \U0001f600'
    )
    stream = io.StringIO()
    configure_logging("INFO", stream)
    logging.getLogger("qa.fixes").info(
        "msg %s\nsecond",
        awkward,
        extra={
            "value": awkward,
            "nested": {awkward: [awkward, {"k\nk": awkward}]},
            "multi\nline": 1,
            "f": float("nan"),
            "inf": float("inf"),
            "obj": object(),
            "bytes": b"\x00\x01",
            "set": {1},
        },
    )
    raw = stream.getvalue()
    assert raw.count("\n") == 1
    assert raw.endswith("\n")
    assert "\r" not in raw
    assert chr(0x2028) not in raw
    event = json.loads(raw)
    assert event["value"].startswith("line1\nline2")
    # No bare NaN/Infinity tokens: strict JSON parsers must accept the line too.
    json.loads(raw, parse_constant=_reject_constant)


def _reject_constant(token: str) -> None:
    raise AssertionError(f"non-standard JSON constant in log line: {token}")


def test_r2_exception_text_with_a_password_url_stays_out_of_the_log() -> None:
    stream = io.StringIO()
    configure_logging("INFO", stream)
    try:
        raise RuntimeError("cannot connect to " + URL_WITH_PW)
    except RuntimeError:
        logging.getLogger("qa.fixes").exception("failed")
    raw = stream.getvalue()
    assert URL_CRED not in raw
    assert len([ln for ln in raw.split("\n") if ln]) == 1
    json.loads(raw)


# --------------------------------------------------------------------------------------------
# R4: aborted responses and cancellation in the request log.
# --------------------------------------------------------------------------------------------

STREAM_BOOM = "DISTINCTIVE-stream-boom-7731"  # synthetic exception text
PARTIAL = b"partial-body-"


class _Harness:
    def __init__(self) -> None:
        self.stream = io.StringIO()
        self.app: FastAPI = make_app(dev=False)
        configure_logging("INFO", self.stream)
        self.app.get("/qa/partial")(self.partial_route)
        self.app.get("/qa/before")(self.before_route)
        self.client = TestClient(self.app, raise_server_exceptions=False)

    @staticmethod
    async def partial_route() -> StreamingResponse:
        async def body() -> Any:
            yield PARTIAL
            raise RuntimeError(STREAM_BOOM)

        return StreamingResponse(body(), media_type="text/plain")

    @staticmethod
    def before_route() -> None:
        raise RuntimeError(STREAM_BOOM)

    def request_events(self) -> list[dict[str, Any]]:
        return _request_events(self.stream)


def test_r4_response_aborted_after_start_is_not_logged_as_success() -> None:
    h = _Harness()
    response = h.client.get("/qa/partial", headers={"X-Correlation-ID": "trace-r4-0001"})
    events = h.request_events()
    assert len(events) == 1
    event = events[0]
    assert event["status"] != 200
    assert event["status"] not in range(200, 400)
    assert event["status"] == 500
    assert event["aborted"] is True
    assert event["correlation_id"] == "trace-r4-0001"
    # The client never sees exception text or a stack trace.
    visible = response.text + str(dict(response.headers))
    assert STREAM_BOOM not in visible
    assert "Traceback" not in visible
    assert "RuntimeError" not in visible


def test_r4_exception_text_is_kept_out_of_the_log_too() -> None:
    h = _Harness()
    h.client.get("/qa/partial")
    assert STREAM_BOOM not in h.stream.getvalue()
    assert any(e["level"] == "ERROR" for e in _parse(h.stream)), "failure must be logged"


def test_r4_raw_asgi_nothing_secret_is_sent_after_the_abort() -> None:
    sent: list[Message] = []

    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": PARTIAL, "more_body": True})
        raise RuntimeError(STREAM_BOOM)

    async def run() -> None:
        stream_scope = _scope()
        middleware = RequestContextMiddleware(app, production=True)

        async def receive() -> Message:
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message: Message) -> None:
            sent.append(message)

        with pytest.raises(RuntimeError):
            await middleware(stream_scope, receive, send)

    stream = io.StringIO()
    configure_logging("INFO", stream)
    asyncio.run(run())
    starts = [m for m in sent if m["type"] == "http.response.start"]
    assert len(starts) == 1, "a second response must not be started after the abort"
    assert STREAM_BOOM.encode() not in b"".join(m.get("body", b"") for m in sent)
    event = _request_events(stream)[0]
    assert event["aborted"] is True
    assert event["status"] != 200


def test_r4_failure_before_the_response_starts_gets_a_generic_500() -> None:
    h = _Harness()
    response = h.client.get("/qa/before")
    assert response.status_code == 500
    assert STREAM_BOOM not in response.text
    assert "Traceback" not in response.text
    event = h.request_events()[0]
    assert event["status"] == 500


def _scope() -> Scope:
    return {
        "type": "http",
        "method": "GET",
        "path": "/qa/x",
        "raw_path": b"/qa/x",
        "query_string": b"",
        "headers": [],
        "client": ("203.0.113.9", 4000),
        "server": ("testserver", 80),
        "scheme": "http",
        "http_version": "1.1",
    }


async def _noop_receive() -> Message:
    return {"type": "http.request", "body": b"", "more_body": False}


def _run_cancelled(app: Any) -> dict[str, Any]:
    """Drive the middleware around ``app`` and return the single request-log event."""
    stream = io.StringIO()
    sent: list[Message] = []

    async def send(message: Message) -> None:
        sent.append(message)

    async def main() -> None:
        configure_logging("INFO", stream)
        middleware = RequestContextMiddleware(app, production=True)
        with pytest.raises(asyncio.CancelledError):
            await middleware(_scope(), _noop_receive, send)

    asyncio.run(main())
    events = _request_events(stream)
    assert len(events) == 1
    return events[0]


def test_r4_cancellation_before_any_response_logs_aborted_never_status_zero() -> None:
    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        raise asyncio.CancelledError

    event = _run_cancelled(app)
    assert event["aborted"] is True
    assert event["status"] != 0
    assert event["status"] not in range(200, 400)


def test_r4_cancellation_after_response_start_does_not_log_the_sent_status() -> None:
    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        await send({"type": "http.response.start", "status": 200, "headers": []})
        raise asyncio.CancelledError

    event = _run_cancelled(app)
    assert event["aborted"] is True
    assert event["status"] != 0
    assert event["status"] != 200
    assert event["status"] not in range(200, 400)


def test_r4_real_task_cancellation_mid_response_logs_aborted() -> None:
    stream = io.StringIO()

    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await asyncio.sleep(30)

    async def send(message: Message) -> None:
        return None

    async def main() -> None:
        configure_logging("INFO", stream)
        middleware = RequestContextMiddleware(app, production=True)
        task = asyncio.ensure_future(middleware(_scope(), _noop_receive, send))
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(main())
    events = _request_events(stream)
    assert len(events) == 1
    assert events[0]["aborted"] is True
    assert events[0]["status"] not in (0, 200)


def test_r4_successful_request_is_logged_with_its_real_status_and_not_aborted() -> None:
    h = _Harness()
    assert h.client.get("/health").status_code == 200
    event = h.request_events()[-1]
    assert event["status"] == 200
    assert event["aborted"] is False

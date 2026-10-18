"""QA tests for T-001 acceptance criterion A7: single-line JSON logs, correlation id, redaction."""

from __future__ import annotations

import io
import json
import logging
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from backend.platform.logging import configure_logging
from scaffold_support import logging_guard, make_app

BOOM = "DISTINCTIVE-boom-8842"
D = {
    "password": "DISTINCTIVE-pw-0001",
    "token": "DISTINCTIVE-tok-0002",
    "secret": "DISTINCTIVE-sec-0003",
    "authorization": "DISTINCTIVE-auth-0004",
    "nested_a": "DISTINCTIVE-nested-0005",
    "nested_b": "DISTINCTIVE-nested-0006",
    "listed": "DISTINCTIVE-list-0007",
    "deep": "DISTINCTIVE-deep-0008",
}
CUSTOM_LOGGER = logging.getLogger("qa.scaffold")


@pytest.fixture(autouse=True)
def _restore_logging() -> Iterator[None]:
    yield from logging_guard()


class Harness:
    def __init__(self) -> None:
        self.stream = io.StringIO()
        self.app: FastAPI = make_app(dev=False)
        # create_app configured logging; point the same JSON handler setup at our buffer.
        configure_logging("INFO", self.stream)
        self.app.get("/qa/log")(self.log_route)
        self.app.get("/qa/boom")(self.boom_route)
        self.client = TestClient(self.app, raise_server_exceptions=False)

    @staticmethod
    def log_route() -> dict[str, str]:
        CUSTOM_LOGGER.info(
            'custom event\nwith a second line and "quotes"',
            extra={
                "invoice_ref": "KEEP-INV-123",
                "password": D["password"],
                "Token": D["token"],
                "SECRET": D["secret"],
                "Authorization": D["authorization"],
                "context": {
                    "user": "synthetic",
                    "inner": {"PASSWORD": D["nested_a"], "Authorization": D["nested_b"]},
                },
                "items": [{"token": D["listed"]}, {"ok": 1}],
                "headers": {"x": {"y": {"z": {"secret": D["deep"]}}}},
            },
        )
        return {"status": "logged"}

    @staticmethod
    def boom_route() -> None:
        raise RuntimeError(BOOM)

    def lines(self) -> list[str]:
        """Application log lines; the test client's own httpx request log is not ours."""
        kept = []
        for line in self.stream.getvalue().split("\n"):
            if line and json.loads(line)["logger"] not in {"httpx", "httpcore"}:
                kept.append(line)
        return kept

    def output(self) -> str:
        return "\n".join(self.lines())

    def events(self) -> list[dict[str, Any]]:
        return [json.loads(line) for line in self.lines()]


def test_a7_every_log_line_is_a_single_line_json_object_with_correlation_id() -> None:
    h = Harness()
    response = h.client.get("/qa/log", headers={"X-Correlation-ID": "trace-0000001"})
    assert response.status_code == 200
    assert h.lines(), "nothing was logged"
    for line in h.lines():
        assert "\r" not in line
        event = json.loads(line)  # raises if not valid JSON
        assert isinstance(event, dict)
        assert event["correlation_id"] == "trace-0000001"
        assert event["level"]
        assert event["message"]
        assert event["timestamp"]


def test_a7_multiline_message_stays_on_one_physical_line() -> None:
    h = Harness()
    h.client.get("/qa/log")
    custom = [e for e in h.events() if e["logger"] == "qa.scaffold"]
    assert len(custom) == 1
    assert "second line" in custom[0]["message"]
    assert len([ln for ln in h.output().split("\n") if "custom event" in ln]) == 1


def test_a7_log_correlation_id_matches_the_response_header_when_generated() -> None:
    h = Harness()
    response = h.client.get("/qa/log")
    header = response.headers["x-correlation-id"]
    assert {e["correlation_id"] for e in h.events()} == {header}


def test_a7_different_requests_log_different_correlation_ids() -> None:
    h = Harness()
    first = h.client.get("/qa/log").headers["x-correlation-id"]
    second = h.client.get("/qa/log").headers["x-correlation-id"]
    seen = {e["correlation_id"] for e in h.events()}
    assert seen == {first, second}
    assert first != second


def test_a7_secret_named_fields_are_redacted_everywhere() -> None:
    h = Harness()
    h.client.get("/qa/log")
    output = h.output()
    for name, value in D.items():
        assert value not in output, f"{name} value leaked into logs"
    assert "KEEP-INV-123" in output, "non-secret fields must still be logged"


def test_a7_redaction_holds_when_logging_directly_outside_a_request() -> None:
    stream = io.StringIO()
    configure_logging("INFO", stream)
    logging.getLogger("qa.direct").warning(
        "direct",
        extra={"api_key": D["token"], "Password": D["password"], "meta": {"TOKEN": D["secret"]}},
    )
    output = stream.getvalue()
    assert len(output.strip().split("\n")) == 1
    assert json.loads(output)["message"] == "direct"
    for value in (D["token"], D["password"], D["secret"]):
        assert value not in output


def test_a7_unhandled_exception_is_logged_as_one_json_line_with_correlation_id() -> None:
    h = Harness()
    response = h.client.get("/qa/boom", headers={"X-Correlation-ID": "trace-0000002"})
    assert response.status_code == 500
    for line in h.lines():
        json.loads(line)
    errors = [e for e in h.events() if e["level"] in {"ERROR", "CRITICAL"}]
    assert errors, "the unhandled exception was not logged at error level"
    assert all(e["correlation_id"] == "trace-0000002" for e in errors)


def test_a7_exception_message_text_is_kept_out_of_logs() -> None:
    """logging.py documents that exception text may hold personal data; type and frames only."""
    h = Harness()
    h.client.get("/qa/boom")
    assert BOOM not in h.output()


def test_a7_request_credentials_and_query_strings_are_not_logged() -> None:
    h = Harness()
    h.client.get(
        "/qa/log?token=DISTINCTIVE-query-0009",
        headers={
            "Authorization": "Bearer DISTINCTIVE-bearer-0010",
            "Cookie": "session=DISTINCTIVE-cookie-0011",
        },
    )
    output = h.output()
    for leaked in ("DISTINCTIVE-query-0009", "DISTINCTIVE-bearer-0010", "DISTINCTIVE-cookie-0011"):
        assert leaked not in output

"""QA tests for T-001 acceptance criteria A2-A5 and A8 (HTTP behaviour of the scaffold)."""

from __future__ import annotations

import re
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi import FastAPI, HTTPException
from starlette.testclient import TestClient

from scaffold_support import logging_guard, make_app

BOOM = "DISTINCTIVE-boom-4711"
HTTP_DETAIL = "DISTINCTIVE-detail-9020"
SAFE_ID = re.compile(r"[A-Za-z0-9_-]{8,40}")
MODES = [pytest.param(True, id="dev"), pytest.param(False, id="prod")]


@pytest.fixture(autouse=True)
def _restore_logging() -> Iterator[None]:
    yield from logging_guard()


def add_throwaway_routes(app: FastAPI) -> None:
    @app.get("/qa/boom")
    def boom() -> None:
        raise RuntimeError(BOOM)

    @app.get("/qa/forbidden")
    def forbidden() -> None:
        raise HTTPException(status_code=403, detail=HTTP_DETAIL)

    @app.get("/qa/items/{item_id}")
    def item(item_id: int) -> dict[str, int]:
        return {"item_id": item_id}


def client_for(*, dev: bool, **overrides: Any) -> TestClient:
    app = make_app(dev=dev, **overrides)
    add_throwaway_routes(app)
    return TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------- A2 health and readiness


@pytest.mark.parametrize("dev", MODES)
def test_a2_health_returns_200_json(dev: bool) -> None:
    response = client_for(dev=dev).get("/health")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert isinstance(response.json(), dict)


@pytest.mark.parametrize("dev", MODES)
def test_a2_ready_returns_200_with_checks_dict(dev: bool) -> None:
    response = client_for(dev=dev).get("/ready")
    assert response.status_code == 200
    assert isinstance(response.json()["checks"], dict)


def test_a2_ready_with_passing_check_is_200() -> None:
    client = client_for(dev=True)
    client.app.state.readiness_checks["db"] = lambda: True  # type: ignore[attr-defined]
    response = client.get("/ready")
    assert response.status_code == 200
    assert "db" in response.json()["checks"]


def test_a2_ready_with_failing_check_is_503() -> None:
    client = client_for(dev=True)
    client.app.state.readiness_checks["db"] = lambda: False  # type: ignore[attr-defined]
    response = client.get("/ready")
    assert response.status_code == 503
    assert "db" in response.json()["checks"]


def test_a2_ready_with_raising_check_is_503_and_hides_exception_text() -> None:
    def broken() -> bool:
        raise RuntimeError(BOOM)

    client = client_for(dev=False)
    client.app.state.readiness_checks["db"] = broken  # type: ignore[attr-defined]
    response = client.get("/ready")
    assert response.status_code == 503
    assert BOOM not in response.text


def test_a2_one_failing_check_among_passing_ones_is_503() -> None:
    client = client_for(dev=True)
    checks = client.app.state.readiness_checks  # type: ignore[attr-defined]
    checks["a"] = lambda: True
    checks["b"] = lambda: False
    assert client.get("/ready").status_code == 503


def test_a2_503_response_still_has_security_headers_and_correlation_id() -> None:
    client = client_for(dev=False)
    client.app.state.readiness_checks["db"] = lambda: False  # type: ignore[attr-defined]
    response = client.get("/ready")
    assert_security_headers(response.headers)
    assert SAFE_ID.fullmatch(response.headers["x-correlation-id"])


# ---------------------------------------------------------------- A3 docs only in dev

DOC_PATHS = ["/docs", "/redoc", "/openapi.json"]


@pytest.mark.parametrize("path", DOC_PATHS)
def test_a3_production_hides_docs(path: str) -> None:
    assert client_for(dev=False).get(path).status_code == 404


@pytest.mark.parametrize("path", DOC_PATHS)
def test_a3_dev_serves_docs(path: str) -> None:
    assert client_for(dev=True).get(path).status_code == 200


@pytest.mark.parametrize("env_value", ["prod", "production", "DEV", "Dev", "staging", ""])
def test_a3_any_env_other_than_exact_dev_is_production(env_value: str) -> None:
    from pydantic import SecretStr

    from backend.api.app import create_app
    from backend.platform.config import Settings

    settings = Settings(env=env_value, database_url=SecretStr("postgresql://synthetic.invalid/x"))
    client = TestClient(create_app(settings), raise_server_exceptions=False)
    for path in DOC_PATHS:
        assert client.get(path).status_code == 404, f"{path} exposed for ENV={env_value!r}"


# ---------------------------------------------------------------- A4 security headers


def assert_security_headers(headers: Any) -> None:
    assert headers["x-content-type-options"].lower() == "nosniff"
    assert headers.get("referrer-policy"), "Referrer-Policy missing"
    assert "no-store" in headers["cache-control"].lower()
    csp = headers.get("content-security-policy")
    assert csp, "Content-Security-Policy missing"
    xfo = headers.get("x-frame-options", "").upper()
    assert xfo in {"DENY", "SAMEORIGIN"} or "frame-ancestors" in csp, "no frame protection"
    assert "server" not in headers or not re.search(
        r"uvicorn|starlette|fastapi|python|\d", headers["server"], re.IGNORECASE
    )
    assert "x-powered-by" not in headers


def collect_responses(dev: bool) -> dict[str, Any]:
    client = client_for(dev=dev)
    responses = {
        "200 health": client.get("/health"),
        "200 ready": client.get("/ready"),
        "200 item": client.get("/qa/items/5"),
        "403 forbidden": client.get("/qa/forbidden"),
        "404": client.get("/qa/does-not-exist"),
        "405": client.post("/health"),
        "422": client.get("/qa/items/not-a-number"),
        "500": client.get("/qa/boom"),
    }
    limited = client_for(dev=dev, throttle_max_requests=1)
    limited.get("/health")
    responses["429"] = limited.get("/health")
    expected = {
        "200 health": 200,
        "200 ready": 200,
        "200 item": 200,
        "403 forbidden": 403,
        "404": 404,
        "405": 405,
        "422": 422,
        "500": 500,
        "429": 429,
    }
    for name, status in expected.items():
        assert responses[name].status_code == status, name
    return responses


@pytest.mark.parametrize("dev", MODES)
def test_a4_a5_every_response_has_security_headers_and_correlation_id(dev: bool) -> None:
    for name, response in collect_responses(dev).items():
        try:
            assert_security_headers(response.headers)
            assert SAFE_ID.fullmatch(response.headers["x-correlation-id"])
        except (AssertionError, KeyError) as exc:
            raise AssertionError(f"{name}: {exc!r}") from exc


def test_a4_dev_docs_pages_carry_security_headers() -> None:
    client = client_for(dev=True)
    for path in DOC_PATHS:
        response = client.get(path)
        assert_security_headers(response.headers)
        assert SAFE_ID.fullmatch(response.headers["x-correlation-id"])


def test_a4_api_csp_forbids_framing_and_loading() -> None:
    response = client_for(dev=False).get("/health")
    csp = response.headers["content-security-policy"]
    assert "frame-ancestors 'none'" in csp
    assert "default-src 'none'" in csp
    assert response.headers["x-frame-options"].upper() == "DENY"


# ---------------------------------------------------------------- A5 correlation id


@pytest.mark.parametrize("dev", MODES)
def test_a5_missing_inbound_id_gets_generated_and_ids_differ(dev: bool) -> None:
    client = client_for(dev=dev)
    first = client.get("/health").headers["x-correlation-id"]
    second = client.get("/health").headers["x-correlation-id"]
    assert SAFE_ID.fullmatch(first)
    assert first != second


@pytest.mark.parametrize(
    "valid",
    [
        "abcd1234",
        "a" * 40,
        "123e4567-e89b-12d3-a456-426614174000",
        "req_ID-0001",
    ],
)
def test_a5_valid_inbound_id_is_echoed(valid: str) -> None:
    response = client_for(dev=True).get("/health", headers={"X-Correlation-ID": valid})
    assert response.headers["x-correlation-id"] == valid


@pytest.mark.parametrize(
    "bad",
    [
        "short",
        "a" * 7,
        "a" * 41,
        "a" * 500,
        "has space in it",
        "bad!chars#here",
        "semi;colon;1234",
        "dots.are.not.ok",
        "<script>alert(1)</script>",
        "abc\r\nX-Injected: yes",
        "abcdefgh\nX-Injected: yes",
        "abcdefgh\r\n\r\n<html>",
    ],
)
def test_a5_malformed_inbound_id_is_replaced(bad: str) -> None:
    client = client_for(dev=True)
    try:
        response = client.get("/health", headers={"X-Correlation-ID": bad})
    except Exception as exc:
        pytest.skip(f"test client refused to send this header value: {exc!r}")
    echoed = response.headers["x-correlation-id"]
    assert echoed != bad
    assert SAFE_ID.fullmatch(echoed)
    assert "x-injected" not in response.headers
    assert "\r" not in echoed
    assert "\n" not in echoed


def test_a5_header_injection_via_raw_asgi_does_not_split_response() -> None:
    """Send raw header bytes (bypassing the client library) with CR/LF inside the value."""
    import asyncio

    app = make_app(dev=True)
    sent: list[dict[str, Any]] = []
    evil = b"abcdefgh\r\nX-Injected: yes"

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/health",
        "raw_path": b"/health",
        "query_string": b"",
        "root_path": "",
        "headers": [(b"x-correlation-id", evil), (b"host", b"testserver")],
        "client": ("127.0.0.1", 5000),
        "server": ("testserver", 80),
    }
    asyncio.run(app(scope, receive, send))
    start = next(m for m in sent if m["type"] == "http.response.start")
    headers = {k.lower(): v for k, v in start["headers"]}
    assert start["status"] == 200
    assert b"x-injected" not in headers
    assert evil not in headers[b"x-correlation-id"]
    assert b"\r" not in headers[b"x-correlation-id"]
    assert b"\n" not in headers[b"x-correlation-id"]


@pytest.mark.parametrize("dev", MODES)
def test_a5_unhandled_exception_returns_generic_500(dev: bool) -> None:
    client = client_for(dev=dev)
    response = client.get("/qa/boom")
    assert response.status_code == 500
    body = response.json()
    assert set(body) == {"error", "correlation_id"}
    assert body["correlation_id"] == response.headers["x-correlation-id"]
    lowered = response.text.lower()
    for leaked in (BOOM.lower(), "traceback", "runtimeerror", "boom", ".py", 'file "'):
        assert leaked not in lowered, leaked
    assert_security_headers(response.headers)


def test_a5_500_body_uses_the_valid_inbound_correlation_id() -> None:
    response = client_for(dev=False).get("/qa/boom", headers={"X-Correlation-ID": "inbound-0001"})
    assert response.status_code == 500
    assert response.headers["x-correlation-id"] == "inbound-0001"
    assert response.json()["correlation_id"] == "inbound-0001"


def test_a5_errors_other_than_500_also_carry_matching_correlation_id_in_body() -> None:
    client = client_for(dev=False)
    for path, method in (("/nope", "GET"), ("/health", "POST"), ("/qa/items/x", "GET")):
        response = client.request(method, path, headers={"X-Correlation-ID": "inbound-0002"})
        assert response.json()["correlation_id"] == "inbound-0002", (method, path)


# ---------------------------------------------------------------- generic error bodies


@pytest.mark.parametrize("dev", MODES)
def test_unknown_paths_and_wrong_methods_return_generic_bodies(dev: bool) -> None:
    client = client_for(dev=dev)
    cases = [
        client.get("/qa/secret-path-xyz"),
        client.post("/health", json={"probe": "REFLECT-ME-123"}),
        client.delete("/ready"),
        client.get("/qa/items/REFLECT-ME-456"),
        client.post("/qa/items/1", json={"probe": "REFLECT-ME-789"}),
        client.get("/qa/forbidden"),
    ]
    for response in cases:
        assert 400 <= response.status_code < 500
        body = response.json()
        assert set(body) == {"error", "correlation_id"}, response.url
        assert "detail" not in body
        assert isinstance(body["error"], str)
        assert len(body["error"]) < 80
        text = response.text
        for leaked in (
            "secret-path-xyz",
            "REFLECT-ME",
            HTTP_DETAIL,
            "loc",
            "msg",
            "input",
            "Traceback",
            "starlette",
            "fastapi",
            "pydantic",
        ):
            assert leaked not in text, (response.url, leaked)


def test_unknown_path_404_and_wrong_method_405_use_correct_status_codes() -> None:
    client = client_for(dev=False)
    assert client.get("/no/such/path").status_code == 404
    assert client.post("/health").status_code == 405
    assert client.put("/ready").status_code == 405


# ---------------------------------------------------------------- A8 throttling


def test_a8_exceeding_throttle_returns_429_with_retry_after() -> None:
    limit = 5
    client = client_for(dev=False, throttle_max_requests=limit, throttle_window_seconds=60)
    statuses = [client.get("/health").status_code for _ in range(limit)]
    assert statuses == [200] * limit
    response = client.get("/health")
    assert response.status_code == 429
    retry_after = response.headers["retry-after"]
    assert retry_after.isdigit()
    assert 1 <= int(retry_after) <= 61
    body = response.json()
    assert set(body) == {"error", "correlation_id"}
    assert body["correlation_id"] == response.headers["x-correlation-id"]
    assert "detail" not in body
    assert_security_headers(response.headers)


def test_a8_throttle_keeps_rejecting_while_over_the_limit() -> None:
    client = client_for(dev=True, throttle_max_requests=2)
    codes = [client.get("/health").status_code for _ in range(6)]
    assert codes[:2] == [200, 200]
    assert set(codes[2:]) == {429}


def test_a8_throttle_applies_to_unknown_paths_too() -> None:
    client = client_for(dev=True, throttle_max_requests=2)
    codes = [client.get("/qa/no-such-path").status_code for _ in range(4)]
    assert codes == [404, 404, 429, 429]


def test_a8_throttle_disabled_by_config_never_returns_429() -> None:
    limit = 5
    client = client_for(dev=False, throttle_enabled=False, throttle_max_requests=limit)
    codes = [client.get("/health").status_code for _ in range(limit * 4)]
    assert codes == [200] * (limit * 4)


def test_a8_throttle_window_resets_with_an_injected_clock() -> None:
    from starlette.applications import Starlette
    from starlette.requests import Request
    from starlette.responses import PlainTextResponse
    from starlette.routing import Route

    from backend.api.middleware import ThrottleMiddleware

    now = [1000.0]

    async def hello(_: Request) -> PlainTextResponse:
        return PlainTextResponse("ok")

    inner = Starlette(routes=[Route("/", hello)])
    wrapped = ThrottleMiddleware(inner, max_requests=2, window_seconds=10, clock=lambda: now[0])
    client = TestClient(wrapped)
    assert [client.get("/").status_code for _ in range(3)] == [200, 200, 429]
    now[0] += 11
    assert client.get("/").status_code == 200

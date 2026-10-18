"""QA tests for T-006 fix R3: the throttle's key table is bounded and stays fast.

Expectations come from the T-007 criteria. The middleware is driven as plain ASGI so that the
client address (``scope["client"]``) can be chosen per call. The cap is the constructor keyword
``max_tracked`` (there is no settings field for it). The key table is private state
(``_windows``); it is read only to check the bound, since there is no public accessor.
Synthetic addresses only (RFC 5737 / documentation ranges and generated strings).
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any

import pytest
from starlette.types import Message, Receive, Scope, Send

from backend.api.middleware import ThrottleMiddleware

WINDOW = 60
LIMIT = 3


class Clock:
    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now


async def _ok_app(scope: Scope, receive: Receive, send: Send) -> None:
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": b"ok"})


class Result:
    def __init__(self, status: int, headers: dict[str, str], body: bytes) -> None:
        self.status = status
        self.headers = headers
        self.body = body


def _make(
    *, max_tracked: int | None = None, clock: Clock | None = None, limit: int = LIMIT
) -> tuple[ThrottleMiddleware, Clock]:
    clock = clock or Clock()
    kwargs: dict[str, Any] = {}
    if max_tracked is not None:
        kwargs["max_tracked"] = max_tracked
    middleware = ThrottleMiddleware(
        _ok_app, max_requests=limit, window_seconds=WINDOW, clock=clock, **kwargs
    )
    return middleware, clock


def _scope(client: tuple[str, int] | None) -> Scope:
    scope: Scope = {
        "type": "http",
        "method": "GET",
        "path": "/health",
        "query_string": b"",
        "headers": [],
        "server": ("testserver", 80),
        "scheme": "http",
    }
    if client is not None:
        scope["client"] = client
    return scope


async def _receive() -> Message:
    return {"type": "http.request", "body": b"", "more_body": False}


async def _call(middleware: ThrottleMiddleware, address: str | None) -> Result:
    status = 0
    headers: dict[str, str] = {}
    body = b""

    async def send(message: Message) -> None:
        nonlocal status, headers, body
        if message["type"] == "http.response.start":
            status = message["status"]
            headers = {k.decode().lower(): v.decode() for k, v in message["headers"]}
        else:
            body += message.get("body", b"")

    scope = _scope((address, 40000) if address is not None else None)
    await middleware(scope, _receive, send)
    return Result(status, headers, body)


def _table_size(middleware: ThrottleMiddleware) -> int:
    table = middleware._windows  # private: no public accessor for the bound under test
    return len(table)


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


# ---- the bound ------------------------------------------------------------------------------


@pytest.mark.parametrize("cap", [1, 2, 50])
def test_r3_key_table_never_exceeds_the_cap_with_many_distinct_clients(cap: int) -> None:
    middleware, _ = _make(max_tracked=cap)

    async def go() -> int:
        largest = 0
        for i in range(2000):
            await _call(middleware, f"10.{i // 65536}.{(i // 256) % 256}.{i % 256}")
            largest = max(largest, _table_size(middleware))
        return largest

    assert _run(go()) <= cap


def test_r3_bound_holds_while_time_passes_and_clients_repeat() -> None:
    middleware, clock = _make(max_tracked=25)

    async def go() -> int:
        largest = 0
        for i in range(3000):
            clock.now += 0.05  # many windows elapse across the run
            await _call(middleware, f"192.0.2.{i % 200}")
            await _call(middleware, f"198.51.{i % 100}.{i % 250}")
            largest = max(largest, _table_size(middleware))
        return largest

    assert _run(go()) <= 25


def test_r3_bound_holds_when_every_entry_is_still_live() -> None:
    """No entry is expired, so the table can only stay bounded by evicting live ones."""
    middleware, _ = _make(max_tracked=10)

    async def go() -> int:
        for i in range(500):
            await _call(middleware, f"live-{i}")
        return _table_size(middleware)

    assert _run(go()) <= 10


def test_r3_clients_without_an_address_share_one_key_and_do_not_grow_the_table() -> None:
    middleware, _ = _make(max_tracked=5)

    async def go() -> list[int]:
        return [(await _call(middleware, None)).status for _ in range(LIMIT + 2)]

    statuses = _run(go())
    assert statuses == [200] * LIMIT + [429, 429]
    assert _table_size(middleware) <= 5


def test_r3_cap_must_be_a_positive_integer() -> None:
    with pytest.raises(ValueError, match="max_tracked"):
        ThrottleMiddleware(_ok_app, max_requests=1, window_seconds=1, max_tracked=0)


def test_r3_default_cap_bounds_the_table_for_20000_distinct_clients_quickly() -> None:
    middleware = ThrottleMiddleware(_ok_app, max_requests=LIMIT, window_seconds=WINDOW)

    async def go() -> tuple[float, int]:
        begin = time.perf_counter()
        for i in range(20_000):
            await _call(middleware, f"client-{i}")
        return time.perf_counter() - begin, _table_size(middleware)

    elapsed, size = _run(go())
    assert size <= 10_000, "default cap in the source is 10,000 keys"
    assert elapsed < 5.0, f"20,000 distinct clients took {elapsed:.2f}s"


def test_r3_small_cap_with_20000_distinct_clients_is_not_quadratic() -> None:
    middleware, _ = _make(max_tracked=1000)

    async def go() -> float:
        begin = time.perf_counter()
        for i in range(20_000):
            await _call(middleware, f"c{i}")
        return time.perf_counter() - begin

    elapsed = _run(go())
    assert elapsed < 5.0, f"took {elapsed:.2f}s"
    assert _table_size(middleware) <= 1000


def test_r3_20000_distinct_clients_with_advancing_clock_is_fast_and_bounded() -> None:
    middleware, clock = _make(max_tracked=5000)

    async def go() -> tuple[float, int]:
        begin = time.perf_counter()
        for i in range(20_000):
            clock.now += 0.01
            await _call(middleware, f"t{i}")
        return time.perf_counter() - begin, _table_size(middleware)

    elapsed, size = _run(go())
    assert size <= 5000
    assert elapsed < 5.0, f"took {elapsed:.2f}s"


# ---- unchanged behaviour for a single client ----------------------------------------------


def test_r3_one_client_gets_429_with_retry_after_after_the_limit() -> None:
    middleware, _ = _make()

    async def go() -> list[Result]:
        return [await _call(middleware, "203.0.113.7") for _ in range(LIMIT + 2)]

    results = _run(go())
    assert [r.status for r in results] == [200] * LIMIT + [429, 429]
    limited = results[LIMIT]
    retry_after = int(limited.headers["retry-after"])
    assert 1 <= retry_after <= WINDOW + 1
    assert limited.headers["content-type"].startswith("application/json")
    body = json.loads(limited.body)
    assert isinstance(body, dict)
    assert "Traceback" not in limited.body.decode()


def test_r3_waiting_the_advertised_retry_after_frees_the_client() -> None:
    middleware, clock = _make()

    async def go() -> tuple[int, int, int]:
        for _ in range(LIMIT):
            await _call(middleware, "203.0.113.8")
        blocked = await _call(middleware, "203.0.113.8")
        wait = int(blocked.headers["retry-after"])
        clock.now += wait - 1 if wait > 1 else 0
        still = (await _call(middleware, "203.0.113.8")).status
        clock.now += 1
        after = (await _call(middleware, "203.0.113.8")).status
        return blocked.status, still, after

    blocked, _, after = _run(go())
    assert blocked == 429
    assert after == 200


def test_r3_retry_after_does_not_grow_as_the_window_runs_down() -> None:
    middleware, clock = _make()

    async def go() -> tuple[int, int]:
        for _ in range(LIMIT):
            await _call(middleware, "203.0.113.9")
        early = int((await _call(middleware, "203.0.113.9")).headers["retry-after"])
        clock.now += 40
        late = int((await _call(middleware, "203.0.113.9")).headers["retry-after"])
        return early, late

    early, late = _run(go())
    assert late < early
    assert late <= WINDOW - 40 + 1


def test_r3_limit_is_per_client_and_a_throttled_client_stays_throttled_among_others() -> None:
    middleware, _ = _make(max_tracked=100)

    async def go() -> tuple[list[int], list[int]]:
        noisy = [(await _call(middleware, "203.0.113.10")).status for _ in range(LIMIT + 1)]
        others = []
        for i in range(50):  # fewer than the cap: the noisy client's entry must survive
            others.append((await _call(middleware, f"198.51.100.{i}")).status)
        noisy_again = [(await _call(middleware, "203.0.113.10")).status for _ in range(2)]
        return noisy + noisy_again, others

    noisy, others = _run(go())
    assert noisy == [200] * LIMIT + [429, 429, 429]
    assert set(others) == {200}


def test_r3_window_expiry_restores_service_for_all_clients() -> None:
    middleware, clock = _make(max_tracked=10)

    async def go() -> list[int]:
        for i in range(30):
            for _ in range(LIMIT + 1):
                await _call(middleware, f"k{i}")
        clock.now += WINDOW + 1
        return [(await _call(middleware, f"k{i}")).status for i in range(30)]

    assert set(_run(go())) == {200}


def test_r3_non_http_scopes_pass_through_without_counting() -> None:
    middleware, _ = _make(max_tracked=5)
    seen: list[str] = []

    async def lifespan_app(scope: Scope, receive: Receive, send: Send) -> None:
        seen.append(scope["type"])

    wrapped = ThrottleMiddleware(
        lifespan_app, max_requests=1, window_seconds=WINDOW, max_tracked=5, clock=Clock()
    )

    async def go() -> None:
        for _ in range(5):
            await wrapped({"type": "lifespan", "client": ("203.0.113.11", 1)}, _receive, _noop_send)

    _run(go())
    assert seen == ["lifespan"] * 5
    assert _table_size(wrapped) == 0
    assert _table_size(middleware) == 0


async def _noop_send(message: Message) -> None:
    return None

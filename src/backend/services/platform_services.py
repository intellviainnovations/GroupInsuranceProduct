"""Idempotency keys, the in-process job runner and the dashboard."""

from __future__ import annotations

import hashlib
import json
import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from backend.domain.model import Enrolment, IdempotencyRecord, Job, Role, User
from backend.domain.repositories import ApprovalQuery, Page
from backend.domain.states import IN_PROCESS
from backend.domain.states import EnrolmentStatus as S
from backend.services.approvals import approval_visibility
from backend.services.common import ActionOutcome, ActionResult, Actor, Deps, ServiceError
from backend.services.views import ApprovalBundle, approval_bundle, can_decide

logger = logging.getLogger("backend.services.jobs")
IST = timezone(timedelta(hours=5, minutes=30))
IDEMPOTENCY_TTL = timedelta(hours=24)


class IdempotencyService:
    """Scope = user + operation + target id; same key + same body replays the first result."""

    def __init__(self, deps: Deps) -> None:
        self.d = deps

    def run(
        self,
        actor: Actor,
        operation: str,
        target_id: UUID | None,
        key: UUID | None,
        body: dict[str, Any],
        action: Callable[[], ActionResult],
    ) -> ActionResult:
        if key is None:
            return action()
        scope_text = f"{actor.user_id}:{operation}:{target_id}"
        scope = hashlib.sha256(scope_text.encode()).hexdigest()[:40]
        request_hash = hashlib.sha256(
            json.dumps(body, sort_keys=True, default=str).encode()
        ).hexdigest()
        now = self.d.clock.now()
        record = IdempotencyRecord(scope, str(key), request_hash, now + IDEMPOTENCY_TTL)
        with self.d.uow() as uow:
            uow.idempotency.purge_expired(now)
            existing = uow.idempotency.reserve(record, now)
            uow.commit()
        if existing is not None:
            if existing.request_hash != request_hash:
                raise ServiceError(422, "IDEMPOTENCY_KEY_REUSED")
            if not existing.completed or existing.resource_id is None:
                raise ServiceError(409, "IDEMPOTENCY_IN_PROGRESS")
            stored = existing.outcome or {}
            outcome = ActionOutcome(
                result=str(stored.get("result", "DONE")),
                category=_opt(stored.get("category")),
                message=_opt(stored.get("message")),
                replayed=True,
            )
            return ActionResult(existing.resource_id, outcome, existing.response_status or 200)
        try:
            result = action()
        except BaseException:
            with self.d.uow() as uow:
                uow.idempotency.release(scope, str(key))
                uow.commit()
            raise
        with self.d.uow() as uow:
            uow.idempotency.complete(
                scope, str(key), result.enrolment_id, result.status_code, result.outcome.as_dict()
            )
            uow.commit()
        return result


def _opt(value: object) -> str | None:
    return None if value is None else str(value)


class JobRunner:
    """Drains due jobs. Called by the background worker, or directly (tests, request path)."""

    def __init__(self, deps: Deps, handlers: dict[str, Callable[[Job], bool]]) -> None:
        self.d = deps
        self.handlers = handlers
        self._run_lock = threading.Lock()

    def run_due(self, limit: int = 20) -> int:
        if not self._run_lock.acquire(blocking=False):
            return 0
        try:
            now = self.d.clock.now()
            with self.d.uow() as uow:
                jobs = uow.jobs.claim_due(now, limit)
                uow.commit()
            for job in jobs:
                self._run(job)
            return len(jobs)
        finally:
            self._run_lock.release()

    def _run(self, job: Job) -> None:
        handler = self.handlers.get(job.job_type)
        done = False
        error = "no handler"
        if handler is not None:
            try:
                done = handler(job)
                error = "not done"
            except Exception as exc:  # a failing job must not stop the worker
                error = type(exc).__name__
                logger.warning("job failed", extra={"job_type": job.job_type, "error": error})
        with self.d.uow() as uow:
            if done:
                uow.jobs.complete(job.job_id)
            elif job.attempts >= job.max_attempts:
                uow.jobs.mark_dead(job.job_id, error)
            else:
                delay = timedelta(seconds=self.d.config.retry_delay_seconds)
                uow.jobs.fail(job.job_id, error, self.d.clock.now() + delay)
            uow.commit()


@dataclass
class JobWorker:
    runner: JobRunner
    poll_seconds: float
    _stop: threading.Event = field(default_factory=threading.Event)
    _wake: threading.Event = field(default_factory=threading.Event)
    _thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="gip-job-worker", daemon=True)
        self._thread.start()

    def wake(self) -> None:
        self._wake.set()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread is not None:
            self._thread.join(timeout=10)
            self._thread = None

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.runner.run_due()
            except Exception:
                logger.exception("job worker iteration failed")
            self._wake.wait(self.poll_seconds)
            self._wake.clear()


@dataclass
class DashboardData:
    as_of: datetime
    all_branches: bool
    branch_code: str | None
    kpis: dict[str, Any]
    queues: dict[str, list[Any]]
    makers: dict[UUID, User | None]


class DashboardService:
    def __init__(self, deps: Deps) -> None:
        self.d = deps

    def build(self, actor: Actor) -> DashboardData:
        now = self.d.clock.now()
        today = now.astimezone(IST).date()
        scope = actor.scope()
        with self.d.uow() as uow:
            enrolments = uow.enrolments.list_in_scope(scope)
            visibility = approval_visibility(actor)
            cache: dict[UUID, User] = {}
            pending: list[ApprovalBundle] = []
            if visibility:
                page: Page[Any] = uow.approvals.search(
                    ApprovalQuery(visibility, "PENDING", page_size=1000)
                )
                pending = [
                    approval_bundle(uow, actor, a, cache)
                    for a in page.items
                    if can_decide(actor, a, uow.enrolments.get(a.enrolment_id))
                ]
            makers = {e.created_by: uow.users.get(e.created_by) for e in enrolments}

        def issued_on(e: Enrolment) -> bool:
            return e.issued_at is not None and e.status in (S.ISSUED, S.CANCELLATION_PENDING)

        issued = [e for e in enrolments if issued_on(e)]
        issued_today = [
            e for e in issued if e.issued_at and e.issued_at.astimezone(IST).date() == today
        ]
        issued_month = [
            e
            for e in issued
            if e.issued_at
            and (d := e.issued_at.astimezone(IST).date()).year == today.year
            and d.month == today.month
        ]

        def total(items: list[Enrolment]) -> str:
            amount = sum((e.gross_premium or Decimal("0") for e in items), Decimal("0"))
            return f"{amount:.2f}"

        kpis = {
            "issued_today": len(issued_today),
            "issued_month": len(issued_month),
            "gross_premium_today": total(issued_today),
            "gross_premium_month": total(issued_month),
            "in_process": sum(1 for e in enrolments if e.status in IN_PROCESS),
            "drafts": sum(1 for e in enrolments if e.status == S.DRAFT),
            "pending_approvals": len(pending),
            "needs_attention": sum(1 for e in enrolments if e.status == S.NEEDS_ATTENTION),
        }

        def newest(items: list[Enrolment], key: Callable[[Enrolment], datetime]) -> list[Enrolment]:
            return sorted(items, key=key, reverse=True)[:5]

        queues: dict[str, list[Any]] = {}
        if actor.has(Role.BRANCH_USER):
            mine = [e for e in enrolments if e.status == S.DRAFT and e.created_by == actor.user_id]
            queues["my_drafts"] = newest(mine, lambda e: e.updated_at)
            queues["in_process"] = newest(
                [e for e in enrolments if e.status in IN_PROCESS], lambda e: e.status_changed_at
            )
            queues["recently_issued"] = newest(issued, lambda e: e.issued_at or e.updated_at)
        if actor.has(Role.CHECKER, Role.OPERATIONS):
            queues["awaiting_my_approval"] = pending[:5]
        if actor.has(Role.OPERATIONS, Role.AUDITOR):
            attention = [e for e in enrolments if e.status == S.NEEDS_ATTENTION]
            queues["needs_attention"] = sorted(
                attention, key=lambda e: e.attention_since or e.status_changed_at
            )[:5]
        return DashboardData(
            now,
            scope is None,
            actor.branch_code if scope is not None else None,
            kpis,
            queues,
            makers,
        )

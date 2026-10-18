"""In-memory backend: one process-wide store and a unit of work with SQL-like semantics.

A unit of work takes the store's single re-entrant lock, works on deep copies, and writes them
back on ``commit``; leaving without commit discards everything (docs/design/repositories.md 3).
Single process only. Data is lost on restart by design. Never used outside ENV=dev/demo.
"""

from __future__ import annotations

import copy
import hashlib
import json
import threading
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta, timezone
from types import TracebackType
from typing import Any, Self
from uuid import UUID

from backend.domain.model import (
    Approval,
    AuditEvent,
    Branch,
    Customer,
    CustomerAccount,
    Document,
    Enrolment,
    IdempotencyRecord,
    Job,
    LoginChallenge,
    Plan,
    PlanRate,
    PoolAccount,
    RefCode,
    Role,
    Session,
    ThrottleState,
    User,
)
from backend.domain.repositories import (
    ApprovalQuery,
    BranchScope,
    DuplicateKey,
    EnrolmentQuery,
    Page,
    VersionConflict,
)

IST = timezone(timedelta(hours=5, minutes=30))
GENESIS_HASH = "0" * 64
_DELETED = object()


def ist_date(value: datetime) -> date:
    return value.astimezone(IST).date()


def audit_row_hash(event: AuditEvent) -> str:
    payload = {
        "audit_id": event.audit_id,
        "event_time": event.event_time.astimezone(UTC).isoformat(),
        "actor_user_id": str(event.actor_user_id) if event.actor_user_id else None,
        "actor_roll_no": event.actor_roll_no,
        "branch_code": event.branch_code,
        "event_type": event.event_type,
        "entity_type": event.entity_type,
        "entity_id": str(event.entity_id) if event.entity_id else None,
        "outcome": event.outcome,
        "client_ip": event.client_ip,
        "correlation_id": event.correlation_id,
        "detail": event.detail,
        "prev_hash": event.prev_hash,
    }
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass
class MemoryStore:
    """Committed state. Touch only through a MemoryUnitOfWork."""

    lock: threading.RLock = field(default_factory=threading.RLock)
    tables: dict[str, dict[Any, Any]] = field(default_factory=dict)
    audit: list[AuditEvent] = field(default_factory=list)
    user_roles: dict[UUID, frozenset[Role]] = field(default_factory=dict)
    plans: dict[tuple[str, str], Plan] = field(default_factory=dict)
    rates: dict[UUID, PlanRate] = field(default_factory=dict)
    ref_codes: list[RefCode] = field(default_factory=list)
    code_map: dict[tuple[str, str, str], str] = field(default_factory=dict)
    pool_accounts: list[PoolAccount] = field(default_factory=list)
    settings: dict[str, str] = field(default_factory=dict)
    reference_prefix: str = "GIP-SYN-"
    reference_seq: int = 0

    def table(self, name: str) -> dict[Any, Any]:
        return self.tables.setdefault(name, {})


class MemoryUnitOfWork:
    def __init__(self, store: MemoryStore) -> None:
        self._store = store
        self._staged: dict[str, dict[Any, Any]] = {}
        self._audit: list[AuditEvent] = []
        self._active = False
        self.enrolments = _Enrolments(self)
        self.approvals = _Approvals(self)
        self.customers = _Customers(self)
        self.users = _Users(self)
        self.sessions = _Sessions(self)
        self.reference = _Reference(self)
        self.audit = _Audit(self)
        self.jobs = _Jobs(self)
        self.idempotency = _Idempotency(self)
        self.documents = _Documents(self)

    # ---- context management
    def __enter__(self) -> Self:
        self._store.lock.acquire()
        self._active = True
        self._staged = {}
        self._audit = []
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self._staged = {}
        self._audit = []
        self._active = False
        self._store.lock.release()

    def commit(self) -> None:
        self._check_unique()
        for name, rows in self._staged.items():
            table = self._store.table(name)
            for key, value in rows.items():
                if value is _DELETED:
                    table.pop(key, None)
                else:
                    table[key] = value
        self._store.audit.extend(self._audit)
        self._staged = {}
        self._audit = []

    # ---- low-level access (copies in, copies out)
    @property
    def store(self) -> MemoryStore:
        return self._store

    def get(self, name: str, key: Any) -> Any:
        staged = self._staged.get(name, {})
        if key in staged:
            value = staged[key]
            return None if value is _DELETED else copy.deepcopy(value)
        value = self._store.table(name).get(key)
        return None if value is None else copy.deepcopy(value)

    def put(self, name: str, key: Any, value: Any) -> None:
        self._staged.setdefault(name, {})[key] = copy.deepcopy(value)

    def delete(self, name: str, key: Any) -> None:
        self._staged.setdefault(name, {})[key] = _DELETED

    def values(self, name: str) -> list[Any]:
        merged = dict(self._store.table(name))
        merged.update(self._staged.get(name, {}))
        return [copy.deepcopy(v) for v in merged.values() if v is not _DELETED]

    def raw_values(self, name: str) -> Iterable[Any]:
        """Read-only view without copying (for scans that copy only what they return)."""
        merged = dict(self._store.table(name))
        merged.update(self._staged.get(name, {}))
        return [v for v in merged.values() if v is not _DELETED]

    def staged_audit(self) -> list[AuditEvent]:
        return self._audit

    def _check_unique(self) -> None:
        if "enrolment" not in self._staged:
            return
        seen: dict[str, set[str]] = {"ref": set(), "proposal": set(), "cert": set()}
        for e in self.raw_values("enrolment"):
            for kind, value in (
                ("ref", e.our_reference_no),
                ("proposal", e.insurer_proposal_no),
                ("cert", e.certificate_no),
            ):
                if value is None:
                    continue
                if value in seen[kind]:
                    raise DuplicateKey(f"enrolment {kind}")
                seen[kind].add(value)


class _Repo:
    def __init__(self, uow: MemoryUnitOfWork) -> None:
        self._uow = uow


def _paginate[T](items: list[T], page: int, page_size: int) -> Page[T]:
    start = (page - 1) * page_size
    return Page(
        items=items[start : start + page_size], page=page, page_size=page_size, total=len(items)
    )


def _in_scope(branch: str, scope: BranchScope) -> bool:
    return scope is None or branch in scope


class _Enrolments(_Repo):
    T = "enrolment"

    def get(self, enrolment_id: UUID) -> Enrolment | None:
        result: Enrolment | None = self._uow.get(self.T, enrolment_id)
        return result

    def get_for_update(self, enrolment_id: UUID) -> Enrolment | None:
        return self.get(enrolment_id)  # the UoW already holds the store lock

    def get_by_reference(self, our_reference_no: str) -> Enrolment | None:
        for e in self._uow.raw_values(self.T):
            if e.our_reference_no == our_reference_no:
                found: Enrolment = copy.deepcopy(e)
                return found
        return None

    def add(self, enrolment: Enrolment) -> None:
        if self._uow.get(self.T, enrolment.enrolment_id) is not None:
            raise DuplicateKey("enrolment id")
        enrolment.version = 1
        self._uow.put(self.T, enrolment.enrolment_id, enrolment)

    def save(self, enrolment: Enrolment) -> None:
        current = self._uow.get(self.T, enrolment.enrolment_id)
        if current is None or current.version != enrolment.version:
            raise VersionConflict("enrolment")
        enrolment.version += 1
        self._uow.put(self.T, enrolment.enrolment_id, enrolment)

    def next_reference_no(self) -> str:
        store = self._uow.store
        store.reference_seq += 1  # sequence semantics: gaps are allowed
        return f"{store.reference_prefix}{store.reference_seq:06d}"

    def _matches(self, e: Enrolment, q: EnrolmentQuery) -> bool:
        if not _in_scope(e.branch_code, q.branch_codes):
            return False
        if q.statuses and e.status.value not in q.statuses:
            return False
        if q.created_by is not None and e.created_by != q.created_by:
            return False
        if q.attention_reason is not None and e.attention_reason != q.attention_reason:
            return False
        day = ist_date(e.created_at)
        if q.created_from is not None and day < q.created_from:
            return False
        if q.created_to is not None and day > q.created_to:
            return False
        if q.text_prefix:
            prefix = q.text_prefix.upper()
            values = (e.our_reference_no, e.insurer_proposal_no, e.certificate_no)
            if not any(v is not None and v.upper().startswith(prefix) for v in values):
                return False
        return True

    def search(self, query: EnrolmentQuery) -> Page[Enrolment]:
        found = [e for e in self._uow.raw_values(self.T) if self._matches(e, query)]
        key_name = query.sort.lstrip("-")
        reverse = query.sort.startswith("-")

        def sort_key(e: Enrolment) -> datetime:
            value: datetime
            if key_name == "attention_since":
                value = e.attention_since or e.status_changed_at
            else:
                value = getattr(e, key_name)
            return value

        found.sort(key=sort_key, reverse=reverse)
        page = _paginate(found, query.page, query.page_size)
        page.items = [copy.deepcopy(e) for e in page.items]
        return page

    def list_in_scope(self, branch_codes: BranchScope) -> list[Enrolment]:
        return [
            copy.deepcopy(e)
            for e in self._uow.raw_values(self.T)
            if _in_scope(e.branch_code, branch_codes)
        ]


class _Approvals(_Repo):
    T = "approval"

    def get(self, approval_id: UUID) -> Approval | None:
        result: Approval | None = self._uow.get(self.T, approval_id)
        return result

    def add(self, approval: Approval) -> None:
        self._uow.put(self.T, approval.approval_id, approval)

    def save(self, approval: Approval) -> None:
        if approval.checker_user_id is not None and approval.checker_user_id == (
            approval.maker_user_id
        ):
            raise DuplicateKey("approval checker equals maker")  # CHECK constraint
        self._uow.put(self.T, approval.approval_id, approval)

    def pending_for(
        self, entity_type: str, entity_id: UUID, action: str | None = None
    ) -> list[Approval]:
        return [
            copy.deepcopy(a)
            for a in self._uow.raw_values(self.T)
            if a.entity_type == entity_type
            and a.entity_id == entity_id
            and a.status == "PENDING"
            and (action is None or a.action == action)
        ]

    def for_enrolment(self, enrolment_id: UUID) -> list[Approval]:
        found = [
            copy.deepcopy(a) for a in self._uow.raw_values(self.T) if a.enrolment_id == enrolment_id
        ]
        found.sort(key=lambda a: a.requested_at)
        return found

    def search(self, query: ApprovalQuery) -> Page[Approval]:
        def visible(a: Approval) -> bool:
            return any(
                a.action in v.actions and _in_scope(a.branch_code, v.branch_codes)
                for v in query.visibility
            )

        found = [
            a
            for a in self._uow.raw_values(self.T)
            if visible(a)
            and (query.status is None or a.status == query.status)
            and (query.action is None or a.action == query.action)
            and (query.entity_type is None or a.entity_type == query.entity_type)
        ]
        found.sort(key=lambda a: a.requested_at)
        page = _paginate(found, query.page, query.page_size)
        page.items = [copy.deepcopy(a) for a in page.items]
        return page


class _Customers(_Repo):
    T = "customer"
    A = "customer_account"

    def get(self, customer_id: UUID) -> Customer | None:
        result: Customer | None = self._uow.get(self.T, customer_id)
        return result

    def get_by_cif(self, cif: str) -> Customer | None:
        for c in self._uow.raw_values(self.T):
            if c.bank_customer_id == cif:
                found: Customer = copy.deepcopy(c)
                return found
        return None

    def upsert_snapshot(
        self, customer: Customer, accounts: list[CustomerAccount]
    ) -> tuple[Customer, list[CustomerAccount]]:
        existing = self.get_by_cif(customer.bank_customer_id)
        if existing is not None:
            customer.customer_id = existing.customer_id
        self._uow.put(self.T, customer.customer_id, customer)
        known = {a.account_no_hash: a for a in self.accounts_for(customer.customer_id)}
        saved: list[CustomerAccount] = []
        for account in accounts:
            account.customer_id = customer.customer_id
            previous = known.get(account.account_no_hash)
            if previous is not None:
                account.customer_account_id = previous.customer_account_id
            self._uow.put(self.A, account.customer_account_id, account)
            saved.append(account)
        return customer, saved

    def get_account(self, customer_account_id: UUID) -> CustomerAccount | None:
        result: CustomerAccount | None = self._uow.get(self.A, customer_account_id)
        return result

    def accounts_for(self, customer_id: UUID) -> list[CustomerAccount]:
        return [
            copy.deepcopy(a) for a in self._uow.raw_values(self.A) if a.customer_id == customer_id
        ]


class _Users(_Repo):
    T = "app_user"
    B = "branch"

    def get(self, user_id: UUID) -> User | None:
        result: User | None = self._uow.get(self.T, user_id)
        return result

    def get_by_roll_no(self, roll_no: str) -> User | None:
        for u in self._uow.raw_values(self.T):
            if u.roll_no.upper() == roll_no.upper():
                found: User = copy.deepcopy(u)
                return found
        return None

    def save(self, user: User) -> None:
        self._uow.put(self.T, user.user_id, user)

    def roles_for(self, user_id: UUID) -> frozenset[Role]:
        return self._uow.store.user_roles.get(user_id, frozenset())

    def get_branch(self, code: str) -> Branch | None:
        result: Branch | None = self._uow.get(self.B, code)
        return result

    def upsert_branch(self, branch: Branch) -> None:
        self._uow.put(self.B, branch.code, branch)


class _Sessions(_Repo):
    T = "user_session"
    C = "login_challenge"
    TH = "login_throttle"

    def create(self, session: Session) -> None:
        self._uow.put(self.T, session.session_hash, session)

    def get_by_hash(self, session_hash: str) -> Session | None:
        result: Session | None = self._uow.get(self.T, session_hash)
        return result

    def save(self, session: Session) -> None:
        self._uow.put(self.T, session.session_hash, session)

    def add_challenge(self, challenge: LoginChallenge) -> None:
        self._uow.put(self.C, challenge.challenge_id, challenge)

    def consume_challenge(self, challenge_id: UUID, now: datetime) -> LoginChallenge | None:
        challenge: LoginChallenge | None = self._uow.get(self.C, challenge_id)
        if challenge is None or challenge.consumed:
            return None
        challenge.consumed = True  # single use, whatever the outcome
        self._uow.put(self.C, challenge_id, challenge)
        if challenge.expires_at <= now:
            return None
        return challenge

    def throttle_get(self, key: str) -> ThrottleState | None:
        result: ThrottleState | None = self._uow.get(self.TH, key)
        return result

    def throttle_save(self, state: ThrottleState) -> None:
        self._uow.put(self.TH, state.key, state)


class _Reference(_Repo):
    def list_plans(self, product_code: str) -> list[Plan]:
        plans = [
            copy.deepcopy(p)
            for (prod, _), p in self._uow.store.plans.items()
            if prod == product_code and p.active
        ]
        return sorted(plans, key=lambda p: p.plan_code)

    def get_plan(self, product_code: str, plan_code: str) -> Plan | None:
        plan = self._uow.store.plans.get((product_code, plan_code))
        return copy.deepcopy(plan) if plan is not None and plan.active else None

    def rate_in_force(self, plan_code: str, on_date: date) -> PlanRate | None:
        for rate in self._uow.store.rates.values():
            if rate.plan_code != plan_code or rate.effective_from > on_date:
                continue
            if rate.effective_to is None or rate.effective_to >= on_date:
                return copy.deepcopy(rate)
        return None

    def get_rate(self, rate_id: UUID) -> PlanRate | None:
        rate = self._uow.store.rates.get(rate_id)
        return copy.deepcopy(rate) if rate is not None else None

    def codes(self, category: str | None = None) -> list[RefCode]:
        found = [
            copy.deepcopy(c)
            for c in self._uow.store.ref_codes
            if c.active and (category is None or c.category == category)
        ]
        return sorted(found, key=lambda c: (c.category, c.sort_order, c.code))

    def map_code(self, insurer_code: str, category: str, our_code: str) -> str | None:
        return self._uow.store.code_map.get((insurer_code, category, our_code))

    def active_pool_account(self, on_date: date) -> PoolAccount | None:
        for pool in self._uow.store.pool_accounts:
            if pool.active_from <= on_date and (
                pool.active_to is None or pool.active_to >= on_date
            ):
                return copy.deepcopy(pool)
        return None

    def setting(self, key: str) -> str | None:
        return self._uow.store.settings.get(key)


class _Audit(_Repo):
    """Append-only: there is no update or delete method."""

    def append(self, event: AuditEvent) -> AuditEvent:
        chain = self._uow.store.audit + self._uow.staged_audit()
        event = copy.deepcopy(event)
        event.audit_id = len(chain) + 1
        event.prev_hash = chain[-1].row_hash if chain else GENESIS_HASH
        event.row_hash = audit_row_hash(event)
        self._uow.staged_audit().append(event)
        return copy.deepcopy(event)

    def verify_chain(self) -> bool:
        prev = GENESIS_HASH
        for event in self._uow.store.audit + self._uow.staged_audit():
            if event.prev_hash != prev or audit_row_hash(event) != event.row_hash:
                return False
            prev = event.row_hash
        return True

    def events(self) -> list[AuditEvent]:
        return copy.deepcopy(self._uow.store.audit + self._uow.staged_audit())


class _Jobs(_Repo):
    T = "job"

    def enqueue(self, job: Job) -> Job:
        for existing in self._uow.raw_values(self.T):
            if existing.dedupe_key == job.dedupe_key:
                if existing.status in ("QUEUED", "RUNNING", "FAILED"):
                    found: Job = copy.deepcopy(existing)
                    return found
                # A finished job frees its key for a new run (memory: replace the row).
                self._uow.delete(self.T, existing.job_id)
        self._uow.put(self.T, job.job_id, job)
        return copy.deepcopy(job)

    def claim_due(self, now: datetime, limit: int) -> list[Job]:
        due = sorted(
            (
                j
                for j in self._uow.raw_values(self.T)
                if j.status in ("QUEUED", "FAILED") and j.run_after <= now
            ),
            key=lambda j: j.run_after,
        )[:limit]
        claimed = []
        for job in due:
            job = copy.deepcopy(job)
            job.status = "RUNNING"
            job.attempts += 1
            self._uow.put(self.T, job.job_id, job)
            claimed.append(job)
        return claimed

    def _update(self, job_id: UUID, change: Callable[[Job], None]) -> None:
        job: Job | None = self._uow.get(self.T, job_id)
        if job is not None:
            change(job)
            self._uow.put(self.T, job_id, job)

    def complete(self, job_id: UUID) -> None:
        def done(job: Job) -> None:
            job.status = "DONE"

        self._update(job_id, done)

    def fail(self, job_id: UUID, error: str, run_after: datetime) -> None:
        def failed(job: Job) -> None:
            job.status = "FAILED"
            job.last_error = error[:500]
            job.run_after = run_after

        self._update(job_id, failed)

    def mark_dead(self, job_id: UUID, error: str) -> None:
        def dead(job: Job) -> None:
            job.status = "DEAD"
            job.last_error = error[:500]

        self._update(job_id, dead)

    def list(self, status: str | None = None, entity_id: UUID | None = None) -> list[Job]:
        return [
            copy.deepcopy(j)
            for j in self._uow.raw_values(self.T)
            if (status is None or j.status == status)
            and (entity_id is None or j.entity_id == entity_id)
        ]


class _Idempotency(_Repo):
    T = "idempotency_key"

    def reserve(self, record: IdempotencyRecord, now: datetime) -> IdempotencyRecord | None:
        existing: IdempotencyRecord | None = self._uow.get(self.T, (record.scope, record.key))
        if existing is not None and existing.expires_at > now:
            return existing
        self._uow.put(self.T, (record.scope, record.key), record)
        return None

    def complete(
        self,
        scope: str,
        key: str,
        resource_id: UUID | None,
        response_status: int,
        outcome: dict[str, object] | None,
    ) -> None:
        record: IdempotencyRecord | None = self._uow.get(self.T, (scope, key))
        if record is None:
            return
        record.completed = True
        record.resource_id = resource_id
        record.response_status = response_status
        record.outcome = outcome
        self._uow.put(self.T, (scope, key), record)

    def release(self, scope: str, key: str) -> None:
        self._uow.delete(self.T, (scope, key))

    def purge_expired(self, now: datetime) -> None:
        for record in self._uow.raw_values(self.T):
            if record.expires_at <= now:
                self._uow.delete(self.T, (record.scope, record.key))


class _Documents(_Repo):
    T = "document"

    def add(self, document: Document) -> None:
        self._uow.put(self.T, document.document_id, document)

    def get(self, document_id: UUID) -> Document | None:
        result: Document | None = self._uow.get(self.T, document_id)
        return result

    def latest(self, enrolment_id: UUID, kind: str) -> Document | None:
        found = [
            d
            for d in self._uow.raw_values(self.T)
            if d.enrolment_id == enrolment_id and d.kind == kind
        ]
        if not found:
            return None
        newest: Document = copy.deepcopy(max(found, key=lambda d: d.created_at))
        return newest

    def list_meta(self, enrolment_id: UUID) -> list[Document]:
        found = []
        for d in self._uow.raw_values(self.T):
            if d.enrolment_id == enrolment_id:
                meta = copy.copy(d)
                meta.content = b""
                found.append(meta)
        return sorted(found, key=lambda d: d.created_at)


def memory_uow_factory(store: MemoryStore) -> Callable[[], MemoryUnitOfWork]:
    def factory() -> MemoryUnitOfWork:
        return MemoryUnitOfWork(store)

    return factory

"""Shared service types: actor, errors, outcomes, clock, keys, masking, audit helper."""

from __future__ import annotations

import base64
import hashlib
import hmac
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import UUID

from backend.adapters.bank_auth.base import AuthProvider
from backend.adapters.cbs.customer_directory.base import CustomerDirectory
from backend.adapters.cbs.posting.base import PostingGateway
from backend.adapters.insurer.base import InsurerAdapter
from backend.domain.model import CROSS_BRANCH_ROLES, AuditEvent, Enrolment, Role
from backend.domain.repositories import BranchScope, UnitOfWork, UnitOfWorkFactory


@dataclass(frozen=True)
class Actor:
    user_id: UUID | None
    roll_no: str
    branch_code: str | None
    roles: frozenset[Role]
    display_name: str | None = None
    client_ip: str | None = None
    correlation_id: str | None = None

    def has(self, *roles: Role) -> bool:
        return any(r in self.roles for r in roles)

    @property
    def cross_branch(self) -> bool:
        return bool(self.roles & CROSS_BRANCH_ROLES)

    def scope(self) -> BranchScope:
        if self.cross_branch:
            return None
        return frozenset({self.branch_code}) if self.branch_code else frozenset()

    def sees_branch(self, branch_code: str) -> bool:
        scope = self.scope()
        return scope is None or branch_code in scope


SYSTEM = Actor(user_id=None, roll_no="SYSTEM", branch_code=None, roles=frozenset())


class ServiceError(Exception):
    """A refusal with an HTTP status and a stable API code. The message is generic."""

    def __init__(
        self,
        status: int,
        code: str,
        fields: list[dict[str, str]] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(code)
        self.status = status
        self.code = code
        self.fields = fields or []
        self.headers = headers


def field_error(path: str, code: str, message: str | None = None) -> dict[str, str]:
    item = {"field": path, "code": code}
    if message:
        item["message"] = message
    return item


def not_found() -> ServiceError:
    return ServiceError(404, "NOT_FOUND")


def invalid_state() -> ServiceError:
    return ServiceError(409, "INVALID_STATE")


def forbidden() -> ServiceError:
    return ServiceError(403, "FORBIDDEN")


@dataclass
class ActionOutcome:
    result: str = "DONE"  # DONE, REJECTED, QUEUED_FOR_RETRY, NEEDS_ATTENTION, PENDING_APPROVAL
    category: str | None = None
    message: str | None = None
    replayed: bool = False

    def as_dict(self) -> dict[str, object]:
        return {"result": self.result, "category": self.category, "message": self.message}


@dataclass
class ActionResult:
    enrolment_id: UUID
    outcome: ActionOutcome
    status_code: int = 200


class Clock:
    """Wall clock with an adjustable offset (tests advance it to make retry jobs due)."""

    def __init__(self) -> None:
        self.offset = timedelta(0)

    def now(self) -> datetime:
        return datetime.now(UTC) + self.offset

    def advance(self, delta: timedelta) -> None:
        self.offset += delta


class Keyring:
    """Keys derived from APP_SESSION_SECRET (HMAC-SHA256 with distinct labels)."""

    def __init__(self, secret: bytes) -> None:
        self._csrf = hmac.new(secret, b"gip-csrf-v1", hashlib.sha256).digest()
        self._account = hmac.new(secret, b"gip-account-key-v1", hashlib.sha256).digest()
        self._secret = secret

    def csrf_token(self, session_id: str) -> str:
        # Contract: base64url(HMAC-SHA256(session_secret, session_id)), unpadded: 43 chars.
        digest = hmac.new(self._secret, session_id.encode("ascii"), hashlib.sha256).digest()
        return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")

    def check_csrf(self, session_id: str, token: str) -> bool:
        return hmac.compare_digest(self.csrf_token(session_id).encode(), token.encode())

    def account_key(self, account_no: str) -> str:
        return hmac.new(self._account, account_no.encode("ascii"), hashlib.sha256).hexdigest()


def session_hash(session_id: str) -> str:
    return hashlib.sha256(session_id.encode("ascii")).hexdigest()


def mask(value: str | None, keep: int = 4) -> str | None:
    if value is None:
        return None
    clean = "".join(ch for ch in value if ch.isalnum())
    if len(clean) <= keep:
        return clean
    return "X" * (len(clean) - keep) + clean[-keep:]


@dataclass
class ServiceConfig:
    env: str
    synthetic_data: bool
    insurer_code: str = "USGIC"
    product_code: str = "GPA"
    selectable_statuses: frozenset[str] = frozenset({"ACTIVE"})
    issue_retry_limit: int = 3
    retry_delay_seconds: int = 60
    session_idle: timedelta = timedelta(minutes=15)
    session_absolute: timedelta = timedelta(minutes=480)
    login_max_failures: int = 5
    login_lock: timedelta = timedelta(minutes=15)
    otp_challenge: timedelta = timedelta(minutes=5)


@dataclass
class Deps:
    uow: UnitOfWorkFactory
    insurer: InsurerAdapter
    auth: AuthProvider
    directory: CustomerDirectory
    posting: PostingGateway
    keys: Keyring
    clock: Clock
    config: ServiceConfig
    # Called after a commit that queued a job (lets the worker wake up early).
    on_job_enqueued: Callable[[], None] = field(default=lambda: None)
    lock: threading.Lock = field(default_factory=threading.Lock)


def audit(
    uow: UnitOfWork,
    actor: Actor,
    event_type: str,
    *,
    outcome: str = "SUCCESS",
    enrolment: Enrolment | None = None,
    entity_type: str | None = None,
    entity_id: UUID | None = None,
    branch_code: str | None = None,
    detail: str | None = None,
    when: datetime | None = None,
) -> None:
    """Append an audit event. ``detail`` holds identifiers and codes only, no personal data."""
    uow.audit.append(
        AuditEvent(
            event_time=when or datetime.now(UTC),
            event_type=event_type,
            outcome=outcome,
            actor_user_id=actor.user_id,
            actor_roll_no=actor.roll_no,
            branch_code=branch_code or (enrolment.branch_code if enrolment else actor.branch_code),
            entity_type=entity_type or ("ENROLMENT" if enrolment else None),
            entity_id=entity_id or (enrolment.enrolment_id if enrolment else None),
            client_ip=actor.client_ip,
            correlation_id=actor.correlation_id,
            detail=detail[:1000] if detail else None,
        )
    )

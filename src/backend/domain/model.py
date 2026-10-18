"""Domain records (plain dataclasses). Repositories hand out copies, never shared instances."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from backend.domain.states import EnrolmentStatus, check_transition


def new_id() -> UUID:
    return uuid.uuid4()


class Role(StrEnum):
    BRANCH_USER = "BRANCH_USER"
    CHECKER = "CHECKER"
    OPERATIONS = "OPERATIONS"
    REPORT_VIEWER = "REPORT_VIEWER"
    ADMIN = "ADMIN"
    AUDITOR = "AUDITOR"


CROSS_BRANCH_ROLES = frozenset({Role.OPERATIONS, Role.AUDITOR})


@dataclass
class Branch:
    code: str
    name: str | None = None


@dataclass
class User:
    user_id: UUID
    roll_no: str
    branch_code: str
    display_name: str | None = None
    email: str | None = None
    designation: str | None = None
    status: str = "ACTIVE"
    first_login_at: datetime | None = None
    last_login_at: datetime | None = None


@dataclass
class Session:
    session_hash: str
    user_id: UUID
    branch_code: str
    created_at: datetime
    last_seen_at: datetime
    idle_expires_at: datetime
    absolute_expires_at: datetime
    revoked_at: datetime | None = None
    revoke_reason: str | None = None
    bank_session_ref: str | None = None
    designation: str | None = None
    client_ip: str | None = None


@dataclass
class LoginChallenge:
    challenge_id: UUID
    challenge_ref: str
    branch_code: str
    roll_no: str
    expires_at: datetime
    consumed: bool = False


@dataclass
class ThrottleState:
    key: str
    fail_count: int
    window_start: datetime
    locked_until: datetime | None = None


@dataclass
class Customer:
    customer_id: UUID
    bank_customer_id: str
    first_name: str
    last_name: str
    middle_name: str | None = None
    gender_code: str | None = None
    date_of_birth: date | None = None
    mobile: str | None = None
    email: str | None = None
    address1: str | None = None
    address2: str | None = None
    city: str | None = None
    state_code: str | None = None
    pincode: str | None = None
    occupation_code: str | None = None
    kyc_status: str | None = None
    customer_status: str | None = None
    home_branch_code: str | None = None
    source: str = "CBS"
    cbs_fetched_at: datetime | None = None


@dataclass
class CustomerAccount:
    customer_account_id: UUID
    customer_id: UUID
    # P1. The memory backend keeps it in process memory only; the SQL backend stores it
    # encrypted (ADR-0002, T-002). Never returned to the browser.
    account_no: str
    account_no_hash: str
    holder_name: str | None = None
    account_type: str | None = None
    account_status: str | None = None
    joint_account: bool | None = None
    cbs_branch_code: str | None = None
    cbs_fetched_at: datetime | None = None
    active: bool = True


INSURED_FIELDS = (
    "first_name",
    "middle_name",
    "last_name",
    "gender_code",
    "date_of_birth",
    "mobile",
    "email",
    "address1",
    "address2",
    "city",
    "state_code",
    "pincode",
    "occupation_code",
    "other_occupation",
    "any_disability",
    "disability_description",
    "guardian_name_address",
)

# InsuredInput x-required-on-submit (staff API contract).
INSURED_REQUIRED_ON_SUBMIT = (
    "first_name",
    "last_name",
    "gender_code",
    "date_of_birth",
    "mobile",
    "address1",
    "city",
    "state_code",
    "pincode",
    "occupation_code",
    "any_disability",
)


@dataclass
class Insured:
    first_name: str | None = None
    middle_name: str | None = None
    last_name: str | None = None
    gender_code: str | None = None
    date_of_birth: date | None = None
    mobile: str | None = None
    email: str | None = None
    address1: str | None = None
    address2: str | None = None
    city: str | None = None
    state_code: str | None = None
    pincode: str | None = None
    occupation_code: str | None = None
    other_occupation: str | None = None
    any_disability: bool | None = None
    disability_description: str | None = None
    guardian_name_address: str | None = None
    cbs_sourced_fields: list[str] = field(default_factory=list)

    @property
    def full_name(self) -> str:
        parts = [self.first_name, self.middle_name, self.last_name]
        return " ".join(p for p in parts if p)


@dataclass
class Nominee:
    seq: int
    name: str
    relation_code: str
    share_percent: Decimal
    date_of_birth: date | None = None
    age: int | None = None
    gender_code: str | None = None
    mobile: str | None = None
    email: str | None = None
    present_address: str | None = None
    permanent_address: str | None = None
    bank_account_no: str | None = None  # P1; never returned
    ifsc: str | None = None
    bank_name: str | None = None
    account_holder_name: str | None = None
    appointee_name: str | None = None
    appointee_relation_code: str | None = None
    appointee_dob: date | None = None
    appointee_age: int | None = None
    appointee_gender_code: str | None = None


@dataclass
class StatusChange:
    history_id: UUID
    from_status: EnrolmentStatus | None
    to_status: EnrolmentStatus
    changed_at: datetime
    reason: str | None = None
    actor_user_id: UUID | None = None
    correlation_id: str | None = None


@dataclass
class Posting:
    posting_id: UUID
    kind: str  # PREMIUM, REFUND, REVERSAL
    amount: Decimal
    customer_account_id: UUID
    pool_account_id: UUID
    cbs_request_ref: str
    status: str  # PENDING, SUCCESS, FAILED, UNKNOWN, REVERSED
    attempt_no: int
    requested_at: datetime
    cbs_tran_id: str | None = None
    cbs_tran_at: datetime | None = None
    error_code: str | None = None
    error_text: str | None = None
    completed_at: datetime | None = None
    created_by: UUID | None = None


@dataclass
class InsurerCall:
    call_id: UUID
    operation: str
    attempt_no: int
    status: str  # SUCCESS, REJECTED, ERROR, UNKNOWN
    started_at: datetime
    our_reference: str | None = None
    error_category: str | None = None
    insurer_status: str | None = None
    error_description: str | None = None
    correlation_id: str | None = None
    finished_at: datetime | None = None
    duration_ms: int | None = None


@dataclass
class Cancellation:
    cancellation_id: UUID
    reason_code: str
    status: str  # DRAFT, PENDING_CHECK, SUBMITTED, COMPLETED, REJECTED, FAILED
    requested_by: UUID
    requested_at: datetime
    remarks: str | None = None
    approval_id: UUID | None = None
    refund_amount: Decimal | None = None
    refund_at: datetime | None = None
    refund_posting_id: UUID | None = None
    completed_at: datetime | None = None


@dataclass
class Enrolment:
    enrolment_id: UUID
    our_reference_no: str
    status: EnrolmentStatus
    status_changed_at: datetime
    product_code: str
    customer_id: UUID
    customer_account_id: UUID | None
    branch_code: str
    created_by: UUID
    created_at: datetime
    updated_at: datetime
    version: int = 1
    plan_code: str | None = None
    rate_id: UUID | None = None
    insured: Insured = field(default_factory=Insured)
    nominees: list[Nominee] = field(default_factory=list)
    insurer_proposal_no: str | None = None
    proposal_created_at: datetime | None = None
    net_premium: Decimal | None = None
    gst_amount: Decimal | None = None
    gross_premium: Decimal | None = None
    premium_matches_rate: bool | None = None
    consent_method: str | None = None
    consent_ref: str | None = None
    consent_at: datetime | None = None
    consent_used: bool = False
    certificate_no: str | None = None
    risk_start_date: date | None = None
    risk_end_date: date | None = None
    issued_at: datetime | None = None
    insurer_message: str | None = None
    attention_reason: str | None = None
    attention_since: datetime | None = None
    cancelled_at: datetime | None = None
    cancel_reason_code: str | None = None
    postings: list[Posting] = field(default_factory=list)
    insurer_calls: list[InsurerCall] = field(default_factory=list)
    history: list[StatusChange] = field(default_factory=list)
    cancellation: Cancellation | None = None

    def transition(
        self,
        target: EnrolmentStatus,
        now: datetime,
        *,
        actor_user_id: UUID | None,
        reason: str | None = None,
        correlation_id: str | None = None,
    ) -> StatusChange:
        """Apply an allowed transition and append the history row (raises InvalidTransition)."""
        check_transition(self.status, target)
        change = StatusChange(
            history_id=new_id(),
            from_status=self.status,
            to_status=target,
            changed_at=now,
            reason=reason,
            actor_user_id=actor_user_id,
            correlation_id=correlation_id,
        )
        self.history.append(change)
        self.status = target
        self.status_changed_at = now
        self.updated_at = now
        if target != EnrolmentStatus.NEEDS_ATTENTION:
            self.attention_reason = None
            self.attention_since = None
        return change

    def next_attempt(self, operation: str) -> int:
        return 1 + sum(1 for c in self.insurer_calls if c.operation == operation)

    def open_posting(self) -> Posting | None:
        """A premium posting whose outcome is not settled (PENDING or UNKNOWN)."""
        for p in self.postings:
            if p.kind == "PREMIUM" and p.status in ("PENDING", "UNKNOWN"):
                return p
        return None

    def successful_premium_posting(self) -> Posting | None:
        for p in reversed(self.postings):
            if p.kind == "PREMIUM" and p.status == "SUCCESS":
                return p
        return None


@dataclass
class Approval:
    approval_id: UUID
    entity_type: str  # ENROLMENT, CANCELLATION
    entity_id: UUID
    enrolment_id: UUID
    branch_code: str
    action: str  # SUBMIT_SALE, CANCEL_CERTIFICATE, ATTENTION_RESOLVE
    maker_user_id: UUID
    status: str  # PENDING, APPROVED, REJECTED, WITHDRAWN
    requested_at: datetime
    maker_comment: str | None = None
    checker_user_id: UUID | None = None
    checker_comment: str | None = None
    decided_at: datetime | None = None
    proposed_status: str | None = None
    evidence_ref: str | None = None
    entity_version: int | None = None


@dataclass
class Document:
    document_id: UUID
    enrolment_id: UUID
    kind: str
    file_name: str
    content_type: str
    size_bytes: int
    sha256: str
    content: bytes
    source: str
    created_at: datetime


@dataclass
class Job:
    job_id: UUID
    job_type: str
    entity_id: UUID | None
    dedupe_key: str
    status: str  # QUEUED, RUNNING, DONE, FAILED, DEAD
    run_after: datetime
    attempts: int
    max_attempts: int
    created_at: datetime
    last_error: str | None = None


@dataclass
class IdempotencyRecord:
    scope: str
    key: str
    request_hash: str
    expires_at: datetime
    completed: bool = False
    resource_id: UUID | None = None
    response_status: int | None = None
    outcome: dict[str, object] | None = None


@dataclass
class AuditEvent:
    event_time: datetime
    event_type: str
    outcome: str
    actor_user_id: UUID | None = None
    actor_roll_no: str | None = None
    branch_code: str | None = None
    entity_type: str | None = None
    entity_id: UUID | None = None
    client_ip: str | None = None
    correlation_id: str | None = None
    detail: str | None = None
    audit_id: int = 0
    prev_hash: str = ""
    row_hash: str = ""


@dataclass
class Plan:
    plan_code: str
    name: str
    product_code: str
    active: bool = True


@dataclass
class PlanRate:
    rate_id: UUID
    plan_code: str
    effective_from: date
    sum_insured: Decimal
    net_premium: Decimal
    gst_amount: Decimal
    gross_premium: Decimal
    policy_term_days: int
    synthetic: bool
    effective_to: date | None = None
    note: str | None = None


@dataclass
class RefCode:
    category: str
    code: str
    label: str
    sort_order: int
    active: bool = True


@dataclass
class PoolAccount:
    pool_account_id: UUID
    account_no: str
    label: str
    active_from: date
    active_to: date | None = None

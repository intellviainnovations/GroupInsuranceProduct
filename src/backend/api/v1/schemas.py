"""Pydantic models for the staff API. Names follow ``components.schemas`` of
docs/contracts/staff-api.openapi.yaml (the source of truth); inline objects of the YAML get
their own class here. Input models forbid unknown fields (whitelist validation).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

# ---------------------------------------------------------------- primitives
Money = Annotated[str, Field(pattern=r"^(0|[1-9][0-9]{0,11})\.[0-9]{2}$", examples=["118.00"])]
Percent = Annotated[str, Field(pattern=r"^(100(\.0{1,4})?|[1-9]?[0-9](\.[0-9]{1,4})?)$")]
RefCodeValue = Annotated[str, Field(pattern=r"^[A-Z0-9_]{1,30}$")]
OptRefCode = Annotated[str | None, Field(pattern=r"^[A-Z0-9_]{1,30}$")]
BranchCode = Annotated[str, Field(pattern=r"^[A-Z0-9]{1,10}$")]
RollNo = Annotated[str, Field(pattern=r"^[A-Za-z0-9]{1,20}$")]
_NAME = r"^[A-Za-z][A-Za-z .'-]*$"
PersonName = Annotated[str, Field(min_length=1, max_length=60, pattern=_NAME)]
FullName = Annotated[str, Field(min_length=1, max_length=150, pattern=_NAME)]
Mobile = Annotated[str, Field(pattern=r"^[0-9]{10,15}$")]
_EMAIL = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
OptEmail = Annotated[
    str | None, Field(max_length=150, pattern=_EMAIL, json_schema_extra={"format": "email"})
]
Pincode = Annotated[str, Field(pattern=r"^[1-9][0-9]{5}$")]
AccountKey = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Masked = Annotated[str, Field(max_length=30, pattern=r"^X*[0-9A-Za-z]{0,4}$")]
PlanCode = Annotated[str, Field(pattern=r"^[A-Z0-9]{1,10}$")]
Version = Annotated[int, Field(ge=1)]

EnrolmentStatus = Literal[
    "DRAFT",
    "PENDING_CHECK",
    "REJECTED",
    "APPROVED",
    "PROPOSAL_CREATED",
    "PAYMENT_PENDING",
    "PAYMENT_FAILED",
    "PAID",
    "ISSUED",
    "PROPOSAL_REJECTED",
    "PROPOSAL_CANCELLED",
    "NEEDS_ATTENTION",
    "CANCELLATION_PENDING",
    "CANCELLED",
]
RoleName = Literal["BRANCH_USER", "CHECKER", "OPERATIONS", "REPORT_VIEWER", "ADMIN", "AUDITOR"]
AllowedAction = Literal[
    "EDIT",
    "SUBMIT",
    "CREATE_PROPOSAL",
    "RECORD_CONSENT",
    "POST_PAYMENT",
    "RETRY_ISSUE",
    "REOPEN",
    "ABANDON",
    "COPY",
    "DOWNLOAD_CERTIFICATE",
    "REQUEST_CANCELLATION",
    "APPROVE",
    "REJECT",
    "RESOLVE",
]
AttentionReason = Literal[
    "POSTING_UNKNOWN",
    "ISSUE_RETRIES_EXHAUSTED",
    "ISSUE_UNKNOWN",
    "PROPOSAL_UNKNOWN",
    "CANCEL_UNKNOWN",
]
ApprovalAction = Literal["SUBMIT_SALE", "CANCEL_CERTIFICATE", "ATTENTION_RESOLVE"]
ErrorCode = Literal[
    "VALIDATION_FAILED",
    "UNAUTHENTICATED",
    "LOGIN_FAILED",
    "CSRF_FAILED",
    "FORBIDDEN",
    "MAKER_CANNOT_CHECK",
    "NOT_FOUND",
    "CUSTOMER_NOT_FOUND",
    "INVALID_STATE",
    "VERSION_CONFLICT",
    "IDEMPOTENCY_KEY_REUSED",
    "IDEMPOTENCY_IN_PROGRESS",
    "PREMIUM_MISMATCH",
    "CONSENT_REQUIRED",
    "ACCOUNT_NOT_ELIGIBLE",
    "POSTING_UNRESOLVED",
    "CBS_UNAVAILABLE",
    "AUTH_UNAVAILABLE",
    "SERVICE_UNAVAILABLE",
    "RATE_LIMITED",
    "INTERNAL",
]
FieldErrorCode = Literal[
    "REQUIRED",
    "TOO_LONG",
    "INVALID_FORMAT",
    "INVALID_CODE",
    "OUT_OF_RANGE",
    "SHARES_NOT_100",
    "NOT_ALLOWED",
    "CBS_SOURCED_READ_ONLY",
    "ACCOUNT_NOT_OF_CUSTOMER",
    "ACCOUNT_NOT_SELECTABLE",
]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _none(value: object) -> bool:
    return value is None


# Optional but not nullable in the contract: omitted from responses when there is no value.
def Omit() -> Any:
    return Field(default=None, exclude_if=_none)


# ---------------------------------------------------------------- errors
class FieldError(Strict):
    field: str = Field(max_length=100)
    code: FieldErrorCode
    message: str | None = Field(default=None, max_length=200)


class Error(Strict):
    error: str = Field(max_length=200)
    code: ErrorCode
    correlation_id: str | None = Field(max_length=40)
    fields: list[FieldError] | None = Field(default=None, max_length=100, exclude_if=_none)


# ---------------------------------------------------------------- auth
class LoginRequest(Strict):
    branch_code: BranchCode
    roll_no: RollNo
    password: str = Field(min_length=1, max_length=128, json_schema_extra={"writeOnly": True})


class OtpRequest(Strict):
    challenge_id: UUID
    otp: str = Field(pattern=r"^[0-9]{4,8}$", json_schema_extra={"writeOnly": True})


class Branch(Strict):
    code: BranchCode
    name: str | None = Field(default=None, max_length=100)


class MeSession(BaseModel):
    idle_expires_at: datetime
    absolute_expires_at: datetime


class MeEnvironment(Strict):
    mode: Literal["dev", "demo", "uat", "prod"]
    synthetic_data: bool


class MeSettings(Strict):
    maker_checker_enrolment: bool
    maker_checker_cancellation: bool


class Me(Strict):
    user_id: UUID
    roll_no: RollNo
    display_name: str | None = Field(default=None, max_length=150)
    designation: str | None = Field(default=None, max_length=100)
    branch: Branch
    roles: list[RoleName] = Field(max_length=6)
    cross_branch: bool = False
    csrf_token: str = Field(min_length=43, max_length=64)
    session: MeSession
    environment: MeEnvironment
    settings: MeSettings


class LoginResult(Strict):
    status: Literal["SIGNED_IN", "OTP_REQUIRED"]
    challenge_id: UUID | None = Omit()
    challenge_expires_at: datetime | None = Omit()
    me: Me | None = Omit()


# ---------------------------------------------------------------- reference
class RefCodeItem(Strict):
    code: RefCodeValue
    label: str = Field(max_length=100)


class RefCodes(Strict):
    GENDER: list[RefCodeItem] = Field(max_length=200)
    RELATION: list[RefCodeItem] = Field(max_length=200)
    OCCUPATION: list[RefCodeItem] = Field(max_length=200)
    STATE: list[RefCodeItem] = Field(max_length=200)
    CONSENT_METHOD: list[RefCodeItem] = Field(max_length=200)
    CANCEL_REASON: list[RefCodeItem] = Field(max_length=200)


class PlanRate(Strict):
    rate_id: UUID
    sum_insured: Money
    net_premium: Money
    gst_amount: Money
    gross_premium: Money
    policy_term_days: int = Field(ge=1, le=3660)
    effective_from: date
    synthetic: bool
    note: str | None = Field(default=None, max_length=300)


class Plan(Strict):
    plan_code: PlanCode
    name: str = Field(max_length=100)
    rate: PlanRate | None


class PlanList(Strict):
    items: list[Plan] = Field(max_length=20)


# ---------------------------------------------------------------- customer lookup
class CustomerLookupRequest(Strict):
    """Exactly one of ``account_no`` and ``cif``."""

    account_no: str | None = Field(
        default=None, pattern=r"^[0-9]{6,30}$", json_schema_extra={"writeOnly": True}
    )
    cif: str | None = Field(
        default=None, pattern=r"^[A-Za-z0-9]{1,20}$", json_schema_extra={"writeOnly": True}
    )

    @model_validator(mode="after")
    def _exactly_one(self) -> CustomerLookupRequest:
        if (self.account_no is None) == (self.cif is None):
            raise ValueError("exactly one of account_no and cif")
        return self


class CbsCustomer(Strict):
    cif_masked: Masked
    first_name: PersonName
    middle_name: str | None = Field(default=None, max_length=60)
    last_name: PersonName
    gender_code: str | None = Field(default=None, max_length=30)
    date_of_birth: date | None = None
    mobile_masked: str | None = Field(default=None, max_length=15)
    city: str | None = Field(default=None, max_length=60)
    state_code: str | None = Field(default=None, max_length=30)
    kyc_status: str | None = Field(default=None, max_length=30)
    customer_status: str | None = Field(default=None, max_length=30)
    home_branch_code: str | None = Field(default=None, max_length=10)


class CbsAccount(Strict):
    account_key: AccountKey
    account_no_masked: Masked
    account_type: str | None = Field(default=None, max_length=30)
    account_status: str | None = Field(default=None, max_length=30)
    branch_code: str | None = Field(default=None, max_length=10)
    joint_account: bool | None = None
    holder_name: str | None = Field(default=None, max_length=150)
    selectable: bool


class CustomerLookupResult(Strict):
    customer: CbsCustomer
    accounts: list[CbsAccount] = Field(min_length=1, max_length=50)
    fetched_at: datetime


# ---------------------------------------------------------------- enrolment input
class DraftCreate(Strict):
    lookup: CustomerLookupRequest
    debit_account_key: AccountKey
    plan_code: PlanCode | None = None


class InsuredInput(Strict):
    first_name: PersonName | None = Omit()
    middle_name: str | None = Field(default=None, max_length=60, pattern=_NAME)
    last_name: PersonName | None = Omit()
    gender_code: RefCodeValue | None = Omit()
    date_of_birth: date | None = Omit()
    mobile: Mobile | None = Omit()
    email: OptEmail = None
    address1: str | None = Field(default=None, min_length=1, max_length=150, exclude_if=_none)
    address2: str | None = Field(default=None, max_length=150)
    city: str | None = Field(default=None, min_length=1, max_length=60, exclude_if=_none)
    state_code: RefCodeValue | None = Omit()
    pincode: Pincode | None = Omit()
    occupation_code: RefCodeValue | None = Omit()
    other_occupation: str | None = Field(default=None, max_length=60)
    any_disability: bool | None = Omit()
    disability_description: str | None = Field(default=None, max_length=500)
    guardian_name_address: str | None = Field(default=None, max_length=500)


class NomineeInput(Strict):
    name: FullName
    relation_code: RefCodeValue
    share_percent: Percent
    date_of_birth: date | None = None
    age: int | None = Field(default=None, ge=0, le=120)
    gender_code: OptRefCode = None
    mobile: str | None = Field(default=None, pattern=r"^[0-9]{10,15}$")
    email: OptEmail = None
    present_address: str | None = Field(default=None, max_length=300)
    permanent_address: str | None = Field(default=None, max_length=300)
    bank_account_no: str | None = Field(
        default=None, pattern=r"^[0-9]{6,30}$", json_schema_extra={"writeOnly": True}
    )
    ifsc: str | None = Field(default=None, pattern=r"^[A-Z]{4}0[A-Z0-9]{6}$")
    bank_name: str | None = Field(default=None, max_length=100)
    account_holder_name: str | None = Field(default=None, max_length=150)
    appointee_name: str | None = Field(default=None, max_length=150)
    appointee_relation_code: OptRefCode = None
    appointee_dob: date | None = None
    appointee_age: int | None = Field(default=None, ge=0, le=120)
    appointee_gender_code: OptRefCode = None


class DraftPatch(Strict):
    version: Version
    debit_account_key: AccountKey | None = None
    plan_code: PlanCode | None = None
    insured: InsuredInput | None = None
    nominees: list[NomineeInput] | None = Field(default=None, max_length=10)

    @model_validator(mode="after")
    def _min_properties(self) -> DraftPatch:
        if len(self.model_fields_set) < 2:
            raise ValueError("at least one section besides version")
        return self


class VersionOnly(Strict):
    version: Version


class SubmitRequest(Strict):
    version: Version
    comment: str | None = Field(default=None, max_length=300)


class CommentedVersion(Strict):
    version: Version
    comment: str = Field(min_length=1, max_length=300)


class ConsentRequest(Strict):
    version: Version
    method: RefCodeValue
    reference: str = Field(min_length=1, max_length=60, pattern=r"^[A-Za-z0-9/_ -]+$")
    confirmed_amount: Money | None = None


class CancellationRequest(Strict):
    version: Version
    reason_code: RefCodeValue
    remarks: str | None = Field(default=None, max_length=500)


class DecisionRequest(Strict):
    comment: str | None = Field(default=None, max_length=300)


class RejectRequest(Strict):
    comment: str = Field(min_length=1, max_length=300)


class ResolveRequest(Strict):
    version: Version
    action: Literal["RECHECK", "CONFIRM"]
    target_status: Literal["PAID", "PAYMENT_FAILED"] | None = None
    note: str | None = Field(default=None, min_length=1, max_length=300)
    evidence_ref: str | None = Field(default=None, max_length=60)


# ---------------------------------------------------------------- enrolment output
class UserRef(Strict):
    user_id: UUID
    roll_no: RollNo
    display_name: str | None = Field(default=None, max_length=150)


class Outcome(Strict):
    result: Literal["DONE", "REJECTED", "QUEUED_FOR_RETRY", "NEEDS_ATTENTION", "PENDING_APPROVAL"]
    category: (
        Literal[
            "VALIDATION",
            "AUTH",
            "NOT_FOUND",
            "BUSINESS_RULE",
            "UNAVAILABLE",
            "TIMEOUT",
            "UNKNOWN",
            "CBS_DECLINED",
        ]
        | None
    ) = None
    message: str | None = Field(default=None, max_length=300)
    replayed: bool = False


class EnrolmentSummary(Strict):
    enrolment_id: UUID
    our_reference_no: str = Field(max_length=30)
    status: EnrolmentStatus
    status_changed_at: datetime
    created_at: datetime
    branch_code: BranchCode
    insured_name: str = Field(max_length=182)
    plan_code: str | None = Field(default=None, max_length=10)
    gross_premium: Money | None = None
    insurer_proposal_no: str | None = Field(default=None, max_length=30)
    certificate_no: str | None = Field(default=None, max_length=40)
    created_by: UserRef
    attention_reason: AttentionReason | None = None


class EnrolmentPage(Strict):
    items: list[EnrolmentSummary] = Field(max_length=100)
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=100)
    total: int = Field(ge=0)


class Insured(InsuredInput):
    cbs_sourced_fields: list[str] = Field(max_length=20)


class Nominee(NomineeInput):
    seq: int = Field(ge=1)
    bank_account_masked: str | None = Field(default=None, max_length=30)


class EnrolmentCustomer(Strict):
    customer_id: UUID
    cif_masked: Masked
    cbs_fetched_at: datetime | None


class Proposal(Strict):
    insurer_proposal_no: str = Field(max_length=30)
    created_at: datetime


class Premium(Strict):
    net_premium: Money
    gst_amount: Money
    gross_premium: Money
    matches_rate: bool


class Consent(Strict):
    method: RefCodeValue
    reference: str = Field(max_length=60)
    consented_at: datetime


class CertificateInfo(Strict):
    certificate_no: str = Field(max_length=40)
    risk_start_date: date
    risk_end_date: date
    issued_at: datetime
    pdf_available: bool


class PostingItem(Strict):
    posting_id: UUID
    kind: Literal["PREMIUM", "REFUND", "REVERSAL"]
    amount: Money
    status: Literal["PENDING", "SUCCESS", "FAILED", "UNKNOWN", "REVERSED"]
    cbs_request_ref: str = Field(max_length=40)
    cbs_tran_id_masked: str | None = Field(default=None, max_length=40)
    cbs_tran_at: datetime | None = None
    attempt_no: int = Field(ge=1)
    error_code: str | None = Field(default=None, max_length=40)
    requested_at: datetime
    completed_at: datetime | None = None


class InsurerCallItem(Strict):
    operation: str = Field(max_length=40)
    attempt_no: int = Field(ge=1)
    status: Literal["SUCCESS", "REJECTED", "ERROR", "UNKNOWN"]
    error_category: str | None = Field(default=None, max_length=20)
    started_at: datetime
    duration_ms: int | None = Field(default=None, ge=0)


class StatusHistoryItem(Strict):
    from_status: EnrolmentStatus | None = None
    to_status: EnrolmentStatus
    reason: str | None = Field(default=None, max_length=300)
    actor: UserRef | None = None
    correlation_id: str | None = Field(default=None, max_length=40)
    changed_at: datetime


class DocumentItem(Strict):
    document_id: UUID
    kind: Literal["COI", "CONSENT_LETTER", "ACKNOWLEDGEMENT"]
    file_name: str = Field(max_length=150)
    size_bytes: int = Field(ge=0)
    created_at: datetime


class CancellationInfo(Strict):
    cancellation_id: UUID
    reason_code: RefCodeValue
    status: Literal["DRAFT", "PENDING_CHECK", "SUBMITTED", "COMPLETED", "REJECTED", "FAILED"]
    requested_by: UserRef
    requested_at: datetime
    refund_amount: Money | None = None
    completed_at: datetime | None = None


class AttentionInfo(Strict):
    reason: AttentionReason
    since: datetime


class Approval(Strict):
    approval_id: UUID
    entity_type: Literal["ENROLMENT", "CANCELLATION"]
    entity_id: UUID
    enrolment_id: UUID | None = Omit()
    our_reference_no: str | None = Field(default=None, max_length=30, exclude_if=_none)
    insured_name: str | None = Field(default=None, max_length=182, exclude_if=_none)
    action: ApprovalAction
    proposed_status: Literal["PAID", "PAYMENT_FAILED"] | None = None
    evidence_ref: str | None = Field(default=None, max_length=60)
    status: Literal["PENDING", "APPROVED", "REJECTED", "WITHDRAWN"]
    maker: UserRef
    checker: UserRef | None = None
    maker_comment: str | None = Field(default=None, max_length=300)
    checker_comment: str | None = Field(default=None, max_length=300)
    requested_at: datetime
    decided_at: datetime | None = None
    can_decide: bool


class ApprovalPage(Strict):
    items: list[Approval] = Field(max_length=100)
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=100)
    total: int = Field(ge=0)


class EnrolmentDetail(Strict):
    enrolment_id: UUID
    our_reference_no: str = Field(max_length=30)
    status: EnrolmentStatus
    status_changed_at: datetime
    version: int = Field(ge=1)
    branch: Branch
    created_by: UserRef
    created_at: datetime
    updated_at: datetime | None = Omit()
    customer: EnrolmentCustomer
    debit_account: CbsAccount
    insured: Insured
    nominees: list[Nominee] = Field(max_length=10)
    plan: Plan | None = None
    proposal: Proposal | None = None
    premium: Premium | None = None
    consent: Consent | None = None
    certificate: CertificateInfo | None = None
    postings: list[PostingItem] = Field(max_length=50)
    insurer_calls: list[InsurerCallItem] = Field(max_length=100)
    status_history: list[StatusHistoryItem] = Field(max_length=200)
    approvals: list[Approval] = Field(max_length=20)
    documents: list[DocumentItem] = Field(max_length=20)
    cancellation: CancellationInfo | None = None
    attention: AttentionInfo | None = None
    allowed_actions: list[AllowedAction] = Field(max_length=14)


class ActionResult(Strict):
    enrolment: EnrolmentDetail
    outcome: Outcome


# ---------------------------------------------------------------- dashboard
class DashboardScope(Strict):
    all_branches: bool
    branch_code: BranchCode | None = None


class DashboardKpis(Strict):
    issued_today: int = Field(ge=0)
    issued_month: int = Field(ge=0)
    gross_premium_today: Money
    gross_premium_month: Money
    in_process: int = Field(ge=0)
    drafts: int = Field(ge=0)
    pending_approvals: int = Field(ge=0)
    needs_attention: int = Field(ge=0)


class DashboardQueues(Strict):
    my_drafts: list[EnrolmentSummary] | None = Field(default=None, max_length=5, exclude_if=_none)
    in_process: list[EnrolmentSummary] | None = Field(default=None, max_length=5, exclude_if=_none)
    awaiting_my_approval: list[Approval] | None = Field(
        default=None, max_length=5, exclude_if=_none
    )
    needs_attention: list[EnrolmentSummary] | None = Field(
        default=None, max_length=5, exclude_if=_none
    )
    recently_issued: list[EnrolmentSummary] | None = Field(
        default=None, max_length=5, exclude_if=_none
    )


class Dashboard(Strict):
    as_of: datetime
    scope: DashboardScope
    kpis: DashboardKpis
    queues: DashboardQueues | None = Omit()

"""Insurer adapter port and outcome model (docs/contracts/insurer-adapter.md).

Services see only these types: dates are dates, money is Decimal, empty values are None.
``endorse`` and ``list_expired`` are not part of the Phase 1 staff API and are not exposed yet.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Protocol


class ErrorCategory(StrEnum):
    VALIDATION = "VALIDATION"
    AUTH = "AUTH"
    NOT_FOUND = "NOT_FOUND"
    BUSINESS_RULE = "BUSINESS_RULE"
    UNAVAILABLE = "UNAVAILABLE"
    TIMEOUT = "TIMEOUT"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class Success[T]:
    data: T


@dataclass(frozen=True)
class Rejected:
    category: ErrorCategory
    message: str | None = None


@dataclass(frozen=True)
class TransientError:
    category: ErrorCategory


@dataclass(frozen=True)
class UnknownOutcome:
    category: ErrorCategory = ErrorCategory.UNKNOWN


type Outcome[T] = Success[T] | Rejected | TransientError | UnknownOutcome


@dataclass
class ProposalNominee:
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
    bank_account_no: str | None = None
    ifsc: str | None = None
    bank_name: str | None = None
    account_holder_name: str | None = None
    appointee_name: str | None = None
    appointee_relation_code: str | None = None
    appointee_dob: date | None = None
    appointee_age: int | None = None
    appointee_gender_code: str | None = None


@dataclass
class ProposalRequest:
    our_reference_no: str
    branch_code: str
    bank_customer_id: str
    plan_code: str
    account_no: str
    first_name: str
    last_name: str
    gender_code: str
    date_of_birth: date
    mobile: str
    address1: str
    city: str
    state_code: str
    pincode: str
    occupation_code: str
    any_disability: bool
    middle_name: str | None = None
    email: str | None = None
    address2: str | None = None
    other_occupation: str | None = None
    disability_description: str | None = None
    guardian_name_address: str | None = None
    nominees: list[ProposalNominee] = field(default_factory=list)


@dataclass(frozen=True)
class ProposalCreated:
    proposal_no: str
    net_premium: Decimal
    gst_amount: Decimal
    gross_premium: Decimal
    insurer_status: str | None = None


@dataclass(frozen=True)
class IssueRequest:
    our_reference_no: str
    proposal_no: str
    bank_customer_id: str
    payment_status: str
    transaction_no: str | None
    transaction_date: date | None


@dataclass(frozen=True)
class PolicyIssued:
    certificate_no: str
    risk_start_date: date
    risk_end_date: date


@dataclass(frozen=True)
class Certificate:
    content: bytes
    content_type: str = "application/pdf"


@dataclass(frozen=True)
class ProposalRecord:
    proposal_no: str | None
    status: str | None = None
    payment_status: str | None = None
    certificate_no: str | None = None
    risk_start_date: date | None = None
    risk_end_date: date | None = None
    net_premium: Decimal | None = None
    gst_amount: Decimal | None = None
    gross_premium: Decimal | None = None
    cancelled: bool = False


@dataclass(frozen=True)
class CancellationResult:
    refund_amount: Decimal | None
    refund_date: date | None


class InsurerAdapter(Protocol):
    @property
    def insurer_code(self) -> str: ...

    def create_proposal(
        self, request: ProposalRequest, *, correlation_id: str | None
    ) -> Outcome[ProposalCreated]: ...

    def issue_policy(
        self, request: IssueRequest, *, correlation_id: str | None
    ) -> Outcome[PolicyIssued]: ...

    def fetch_certificate(
        self, certificate_no: str, proposal_no: str | None, *, correlation_id: str | None
    ) -> Outcome[Certificate]: ...

    def get_proposal(
        self, *, proposal_no: str | None, our_reference: str, correlation_id: str | None
    ) -> Outcome[ProposalRecord]: ...

    def cancel_certificate(
        self, certificate_no: str, *, our_reference: str, correlation_id: str | None
    ) -> Outcome[CancellationResult]: ...

    def cancel_proposal(
        self, proposal_no: str, *, our_reference: str, correlation_id: str | None
    ) -> Outcome[bool]: ...


class UnconfiguredInsurer:
    """Default outside dev/demo until a real adapter is selected: fails closed, sends nothing."""

    insurer_code = "USGIC"

    def create_proposal(
        self, request: ProposalRequest, *, correlation_id: str | None
    ) -> Outcome[ProposalCreated]:
        return TransientError(ErrorCategory.UNAVAILABLE)

    def issue_policy(
        self, request: IssueRequest, *, correlation_id: str | None
    ) -> Outcome[PolicyIssued]:
        return TransientError(ErrorCategory.UNAVAILABLE)

    def fetch_certificate(
        self, certificate_no: str, proposal_no: str | None, *, correlation_id: str | None
    ) -> Outcome[Certificate]:
        return TransientError(ErrorCategory.UNAVAILABLE)

    def get_proposal(
        self, *, proposal_no: str | None, our_reference: str, correlation_id: str | None
    ) -> Outcome[ProposalRecord]:
        return TransientError(ErrorCategory.UNAVAILABLE)

    def cancel_certificate(
        self, certificate_no: str, *, our_reference: str, correlation_id: str | None
    ) -> Outcome[CancellationResult]:
        return TransientError(ErrorCategory.UNAVAILABLE)

    def cancel_proposal(
        self, proposal_no: str, *, our_reference: str, correlation_id: str | None
    ) -> Outcome[bool]:
        return TransientError(ErrorCategory.UNAVAILABLE)

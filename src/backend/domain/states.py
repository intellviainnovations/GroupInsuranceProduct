"""Enrolment states and the allowed transitions, exactly as in docs/specs/usgic-gpa-sale-flow.md."""

from __future__ import annotations

from enum import StrEnum


class EnrolmentStatus(StrEnum):
    DRAFT = "DRAFT"
    PENDING_CHECK = "PENDING_CHECK"
    REJECTED = "REJECTED"
    APPROVED = "APPROVED"
    PROPOSAL_CREATED = "PROPOSAL_CREATED"
    PAYMENT_PENDING = "PAYMENT_PENDING"
    PAYMENT_FAILED = "PAYMENT_FAILED"
    PAID = "PAID"
    ISSUED = "ISSUED"
    PROPOSAL_REJECTED = "PROPOSAL_REJECTED"
    PROPOSAL_CANCELLED = "PROPOSAL_CANCELLED"
    NEEDS_ATTENTION = "NEEDS_ATTENTION"
    CANCELLATION_PENDING = "CANCELLATION_PENDING"
    CANCELLED = "CANCELLED"


S = EnrolmentStatus

# "Allowed transitions" table of the spec. Any other transition is rejected.
TRANSITIONS: dict[EnrolmentStatus, frozenset[EnrolmentStatus]] = {
    S.DRAFT: frozenset({S.PENDING_CHECK, S.APPROVED}),
    S.PENDING_CHECK: frozenset({S.APPROVED, S.REJECTED}),
    S.REJECTED: frozenset(),
    S.APPROVED: frozenset({S.PROPOSAL_CREATED, S.PROPOSAL_REJECTED}),
    S.PROPOSAL_REJECTED: frozenset({S.DRAFT}),
    S.PROPOSAL_CREATED: frozenset({S.PAYMENT_PENDING, S.PROPOSAL_CANCELLED}),
    S.PAYMENT_PENDING: frozenset({S.PAID, S.PAYMENT_FAILED, S.NEEDS_ATTENTION}),
    S.PAYMENT_FAILED: frozenset({S.PAYMENT_PENDING, S.PROPOSAL_CANCELLED}),
    S.PAID: frozenset({S.ISSUED, S.NEEDS_ATTENTION}),
    S.NEEDS_ATTENTION: frozenset({S.PAID, S.ISSUED, S.PAYMENT_FAILED}),
    S.ISSUED: frozenset({S.CANCELLATION_PENDING}),
    S.CANCELLATION_PENDING: frozenset({S.CANCELLED, S.NEEDS_ATTENTION}),
    S.PROPOSAL_CANCELLED: frozenset(),
    S.CANCELLED: frozenset(),
}

IN_PROCESS = frozenset(
    {S.APPROVED, S.PROPOSAL_CREATED, S.PAYMENT_PENDING, S.PAYMENT_FAILED, S.PAID}
)


class InvalidTransition(Exception):
    """A transition that the spec does not allow."""


def can_transition(current: EnrolmentStatus, target: EnrolmentStatus) -> bool:
    return target in TRANSITIONS[current]


def check_transition(current: EnrolmentStatus, target: EnrolmentStatus) -> None:
    if not can_transition(current, target):
        raise InvalidTransition(f"{current} -> {target}")

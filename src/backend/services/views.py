"""Read models: enrolment and approval bundles, allowed actions and decision rights."""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID

from backend.domain.model import (
    Approval,
    Branch,
    Customer,
    CustomerAccount,
    Document,
    Enrolment,
    Plan,
    PlanRate,
    Role,
    User,
)
from backend.domain.repositories import UnitOfWork
from backend.domain.states import EnrolmentStatus as S
from backend.services.common import Actor, ServiceError, not_found

_DECIDER = {
    "SUBMIT_SALE": Role.CHECKER,
    "CANCEL_CERTIFICATE": Role.CHECKER,
    "ATTENTION_RESOLVE": Role.OPERATIONS,
}


@dataclass
class ApprovalBundle:
    approval: Approval
    maker: User | None
    checker: User | None
    our_reference_no: str | None
    insured_name: str | None
    can_decide: bool


@dataclass
class EnrolmentBundle:
    enrolment: Enrolment
    branch: Branch | None
    maker: User | None
    customer: Customer | None
    account: CustomerAccount | None
    plan: Plan | None
    rate: PlanRate | None
    approvals: list[ApprovalBundle]
    documents: list[Document]
    users: dict[UUID, User] = field(default_factory=dict)
    allowed_actions: list[str] = field(default_factory=list)
    pdf_available: bool = False


def decider_role(action: str) -> Role:
    return _DECIDER[action]


def can_decide(actor: Actor, approval: Approval, enrolment: Enrolment | None) -> bool:
    if approval.status != "PENDING" or actor.user_id is None:
        return False
    if actor.user_id == approval.maker_user_id:
        return False
    is_maker = enrolment is not None and actor.user_id == enrolment.created_by
    if approval.action == "SUBMIT_SALE" and is_maker:
        return False
    role = _DECIDER.get(approval.action)
    if role is None or not actor.has(role):
        return False
    if role == Role.CHECKER:
        return actor.branch_code == approval.branch_code
    return True


def open_cancellation(e: Enrolment) -> bool:
    return e.cancellation is not None and e.cancellation.status not in ("REJECTED", "FAILED")


def allowed_actions(
    actor: Actor, e: Enrolment, approvals: list[Approval], pdf_available: bool
) -> list[str]:
    branch_user = actor.has(Role.BRANCH_USER) and actor.branch_code == e.branch_code
    ops = actor.has(Role.OPERATIONS)
    actions: list[str] = []
    st = e.status
    if branch_user and st == S.DRAFT:
        actions += ["EDIT", "SUBMIT"]
    if branch_user and st == S.REJECTED:
        actions.append("COPY")
    if branch_user and st == S.APPROVED:
        actions.append("CREATE_PROPOSAL")
    if branch_user and st in (S.PROPOSAL_CREATED, S.PAYMENT_FAILED):
        if e.premium_matches_rate is not False:
            actions.append("RECORD_CONSENT")
            if e.consent_at is not None and not e.consent_used:
                actions.append("POST_PAYMENT")
        actions.append("ABANDON")
    if (branch_user or ops) and (st == S.PAID or (st == S.ISSUED and not pdf_available)):
        actions.append("RETRY_ISSUE")
    if branch_user and st == S.PROPOSAL_REJECTED:
        actions.append("REOPEN")
    if pdf_available and st in (S.ISSUED, S.CANCELLATION_PENDING, S.CANCELLED):
        actions.append("DOWNLOAD_CERTIFICATE")
    if branch_user and st == S.ISSUED and not open_cancellation(e):
        actions.append("REQUEST_CANCELLATION")
    if ops and st == S.NEEDS_ATTENTION:
        actions.append("RESOLVE")
    if any(can_decide(actor, a, e) for a in approvals):
        actions += ["APPROVE", "REJECT"]
    return actions


def load_enrolment(uow: UnitOfWork, actor: Actor, enrolment_id: UUID) -> Enrolment:
    """Fetch an enrolment the actor may see; another branch's id is 404 (no enumeration)."""
    e = uow.enrolments.get(enrolment_id)
    if e is None or not actor.sees_branch(e.branch_code):
        raise not_found()
    return e


def check_version(e: Enrolment, version: int) -> None:
    if e.version != version:
        raise ServiceError(409, "VERSION_CONFLICT")


def _user(uow: UnitOfWork, cache: dict[UUID, User], user_id: UUID | None) -> User | None:
    if user_id is None:
        return None
    if user_id not in cache:
        found = uow.users.get(user_id)
        if found is None:
            return None
        cache[user_id] = found
    return cache[user_id]


def approval_bundle(
    uow: UnitOfWork,
    actor: Actor,
    a: Approval,
    cache: dict[UUID, User],
    enrolment: Enrolment | None = None,
) -> ApprovalBundle:
    e = enrolment or uow.enrolments.get(a.enrolment_id)
    return ApprovalBundle(
        approval=a,
        maker=_user(uow, cache, a.maker_user_id),
        checker=_user(uow, cache, a.checker_user_id),
        our_reference_no=e.our_reference_no if e else None,
        insured_name=e.insured.full_name if e else None,
        can_decide=can_decide(actor, a, e),
    )


def enrolment_bundle(uow: UnitOfWork, actor: Actor, e: Enrolment) -> EnrolmentBundle:
    cache: dict[UUID, User] = {}
    approvals = uow.approvals.for_enrolment(e.enrolment_id)
    documents = uow.documents.list_meta(e.enrolment_id)
    pdf = any(d.kind == "COI" for d in documents)
    for change in e.history:
        _user(uow, cache, change.actor_user_id)
    if e.cancellation is not None:
        _user(uow, cache, e.cancellation.requested_by)
    plan = uow.reference.get_plan(e.product_code, e.plan_code) if e.plan_code else None
    rate = None
    if e.rate_id is not None:
        rate = uow.reference.get_rate(e.rate_id)
    elif plan is not None:
        rate = uow.reference.rate_in_force(plan.plan_code, e.created_at.date())
    return EnrolmentBundle(
        enrolment=e,
        branch=uow.users.get_branch(e.branch_code),
        maker=_user(uow, cache, e.created_by),
        customer=uow.customers.get(e.customer_id),
        account=(
            uow.customers.get_account(e.customer_account_id) if e.customer_account_id else None
        ),
        plan=plan,
        rate=rate,
        approvals=[approval_bundle(uow, actor, a, cache, e) for a in approvals],
        documents=documents,
        users=cache,
        allowed_actions=allowed_actions(actor, e, approvals, pdf),
        pdf_available=pdf,
    )

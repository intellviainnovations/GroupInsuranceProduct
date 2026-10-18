"""Approval queue and decisions (maker-checker), and the operations attention queue.

Maker and checker always differ. ``ATTENTION_RESOLVE`` CONFIRM needs a second OPERATIONS user
(Decided 2026-10-18); RECHECK is single-user because the state follows the insurer/CBS read-back.
"""

from __future__ import annotations

from datetime import timedelta
from uuid import UUID

from backend.domain.model import Approval, Enrolment, Job, Role, User, new_id
from backend.domain.repositories import (
    ApprovalQuery,
    ApprovalVisibility,
    EnrolmentQuery,
    Page,
    UnitOfWork,
)
from backend.domain.states import EnrolmentStatus as S
from backend.services.common import (
    ActionOutcome,
    ActionResult,
    Actor,
    Deps,
    ServiceError,
    audit,
    field_error,
    invalid_state,
    not_found,
)
from backend.services.sale import SaleService
from backend.services.views import (
    ApprovalBundle,
    approval_bundle,
    can_decide,
    check_version,
    decider_role,
    load_enrolment,
)

CHECKER_ACTIONS = frozenset({"SUBMIT_SALE", "CANCEL_CERTIFICATE"})
ALL_ACTIONS = CHECKER_ACTIONS | {"ATTENTION_RESOLVE"}


def approval_visibility(actor: Actor) -> list[ApprovalVisibility]:
    rules = []
    if actor.has(Role.AUDITOR):
        rules.append(ApprovalVisibility(ALL_ACTIONS, None))
    if actor.has(Role.OPERATIONS):
        rules.append(ApprovalVisibility(frozenset({"ATTENTION_RESOLVE"}), None))
    if actor.has(Role.CHECKER) and actor.branch_code:
        rules.append(ApprovalVisibility(CHECKER_ACTIONS, frozenset({actor.branch_code})))
    return rules


class ApprovalService:
    def __init__(self, deps: Deps, sale: SaleService) -> None:
        self.d = deps
        self.sale = sale

    def search(
        self,
        actor: Actor,
        *,
        action: str | None,
        status: str | None,
        entity_type: str | None,
        page: int,
        page_size: int,
    ) -> Page[ApprovalBundle]:
        query = ApprovalQuery(
            approval_visibility(actor), status, action, entity_type, page, page_size
        )
        with self.d.uow() as uow:
            found = uow.approvals.search(query)
            cache: dict[UUID, User] = {}
            items = [approval_bundle(uow, actor, a, cache) for a in found.items]
        return Page(items, found.page, found.page_size, found.total)

    def _load(self, uow: UnitOfWork, actor: Actor, approval_id: UUID) -> tuple[Approval, Enrolment]:
        a = uow.approvals.get(approval_id)
        if a is None:
            raise not_found()
        visible = any(
            a.action in v.actions and (v.branch_codes is None or a.branch_code in v.branch_codes)
            for v in approval_visibility(actor)
        )
        e = uow.enrolments.get(a.enrolment_id)
        if e is None:
            raise not_found()
        if not actor.has(decider_role(a.action)):
            raise ServiceError(403, "FORBIDDEN")
        if not visible:  # right role, other branch: 404, no enumeration
            raise not_found()
        if actor.user_id == a.maker_user_id or (
            a.action == "SUBMIT_SALE" and actor.user_id == e.created_by
        ):
            raise ServiceError(403, "MAKER_CANNOT_CHECK")
        if a.status != "PENDING":
            raise invalid_state()
        if not can_decide(actor, a, e):
            raise ServiceError(403, "FORBIDDEN")
        return a, e

    def _decide(
        self, uow: UnitOfWork, actor: Actor, a: Approval, status: str, comment: str | None
    ) -> None:
        a.status, a.checker_user_id = status, actor.user_id
        a.checker_comment, a.decided_at = comment, self.d.clock.now()
        uow.approvals.save(a)
        audit(
            uow,
            actor,
            "APPROVAL_DECIDED",
            entity_type="APPROVAL",
            entity_id=a.approval_id,
            branch_code=a.branch_code,
            detail=f"action={a.action};status={status}",
        )

    def approve(self, actor: Actor, approval_id: UUID, comment: str | None) -> ActionResult:
        with self.d.uow() as uow:
            a, e = self._load(uow, actor, approval_id)
            if a.action == "SUBMIT_SALE":
                if e.status != S.PENDING_CHECK:
                    raise invalid_state()
                self.sale._transition(uow, actor, e, S.APPROVED, comment)
                uow.enrolments.save(e)
                self._decide(uow, actor, a, "APPROVED", comment)
                uow.commit()
                return ActionResult(e.enrolment_id, ActionOutcome())
            if a.action == "CANCEL_CERTIFICATE":
                if e.status != S.ISSUED or e.cancellation is None:
                    raise invalid_state()
                e.cancellation.status = "SUBMITTED"
                uow.enrolments.save(e)
                self._decide(uow, actor, a, "APPROVED", comment)
                uow.commit()
                return self.sale.execute_cancellation(actor, e.enrolment_id)
            # ATTENTION_RESOLVE: apply only if nothing moved since the request.
            if e.status != S.NEEDS_ATTENTION or e.version != a.entity_version:
                stale = True
            else:
                stale = False
                self._apply_confirm(uow, actor, e, a)
                uow.enrolments.save(e)
                self._decide(uow, actor, a, "APPROVED", comment)
                uow.commit()
        if stale:
            with self.d.uow() as uow:
                a2 = uow.approvals.get(approval_id)
                if a2 is not None:
                    a2.status = "WITHDRAWN"
                    uow.approvals.save(a2)
                    uow.commit()
            raise ServiceError(409, "VERSION_CONFLICT")
        if a.proposed_status == "PAID":
            self.d.on_job_enqueued()
        return ActionResult(e.enrolment_id, ActionOutcome())

    def _apply_confirm(self, uow: UnitOfWork, actor: Actor, e: Enrolment, a: Approval) -> None:
        target = S(a.proposed_status or "")
        posting = e.open_posting()
        if target == S.PAID:
            if posting is not None:
                posting.status, posting.error_code = "SUCCESS", "CONFIRMED_BY_OPERATIONS"
                posting.completed_at = self.d.clock.now()
            self.sale._transition(uow, actor, e, S.PAID, a.maker_comment)
            uow.jobs.enqueue(
                Job(
                    new_id(),
                    "ISSUE_POLICY",
                    e.enrolment_id,
                    f"ISSUE_POLICY:{e.enrolment_id}",
                    "QUEUED",
                    self.d.clock.now(),
                    0,
                    self.d.config.issue_retry_limit,
                    self.d.clock.now(),
                )
            )
        else:
            if posting is not None:
                posting.status, posting.error_code = "FAILED", "CONFIRMED_BY_OPERATIONS"
                posting.completed_at = self.d.clock.now()
            e.consent_used = True  # a retry needs fresh consent
            self.sale._transition(uow, actor, e, S.PAYMENT_FAILED, a.maker_comment)

    def reject(self, actor: Actor, approval_id: UUID, comment: str) -> ActionResult:
        with self.d.uow() as uow:
            a, e = self._load(uow, actor, approval_id)
            if a.action == "SUBMIT_SALE":
                if e.status != S.PENDING_CHECK:
                    raise invalid_state()
                self.sale._transition(uow, actor, e, S.REJECTED, comment)
            elif a.action == "CANCEL_CERTIFICATE" and e.cancellation is not None:
                e.cancellation.status = "REJECTED"  # the certificate stays ISSUED
                e.updated_at = self.d.clock.now()
            uow.enrolments.save(e)
            self._decide(uow, actor, a, "REJECTED", comment)
            uow.commit()
        return ActionResult(e.enrolment_id, ActionOutcome())


class OperationsService:
    def __init__(self, deps: Deps, sale: SaleService) -> None:
        self.d = deps
        self.sale = sale

    def attention(
        self, actor: Actor, reason: str | None, page: int, page_size: int
    ) -> tuple[Page[Enrolment], dict[UUID, User | None]]:
        query = EnrolmentQuery(
            branch_codes=actor.scope(),
            statuses=frozenset({"NEEDS_ATTENTION"}),
            attention_reason=reason,
            page=page,
            page_size=page_size,
            sort="attention_since",
        )
        with self.d.uow() as uow:
            found = uow.enrolments.search(query)
            makers = {e.created_by: uow.users.get(e.created_by) for e in found.items}
        return found, makers

    def resolve(
        self,
        actor: Actor,
        enrolment_id: UUID,
        version: int,
        action: str,
        target_status: str | None,
        note: str | None,
        evidence_ref: str | None,
    ) -> ActionResult:
        with self.d.uow() as uow:
            e = load_enrolment(uow, actor, enrolment_id)
            if e.status != S.NEEDS_ATTENTION:
                raise invalid_state()
            check_version(e, version)
            if action == "CONFIRM":
                errors = []
                if target_status not in ("PAID", "PAYMENT_FAILED"):
                    errors.append(field_error("target_status", "REQUIRED"))
                if not note:
                    errors.append(field_error("note", "REQUIRED"))
                if errors:
                    raise ServiceError(422, "VALIDATION_FAILED", errors)
                if e.attention_reason == "CANCEL_UNKNOWN":
                    raise invalid_state()  # PAID/PAYMENT_FAILED make no sense after a cancel
                if uow.approvals.pending_for("ENROLMENT", e.enrolment_id, "ATTENTION_RESOLVE"):
                    raise invalid_state()
                assert actor.user_id is not None  # noqa: S101
                approval = Approval(
                    new_id(),
                    "ENROLMENT",
                    e.enrolment_id,
                    e.enrolment_id,
                    e.branch_code,
                    "ATTENTION_RESOLVE",
                    actor.user_id,
                    "PENDING",
                    self.d.clock.now(),
                    maker_comment=note,
                    proposed_status=target_status,
                    evidence_ref=evidence_ref,
                    entity_version=e.version,
                )
                uow.approvals.add(approval)
                audit(
                    uow,
                    actor,
                    "ATTENTION_CONFIRM_REQUESTED",
                    enrolment=e,
                    detail=f"target={target_status}",
                )
                uow.commit()
                return ActionResult(e.enrolment_id, ActionOutcome("PENDING_APPROVAL"))
        return self._recheck(actor, e)

    def _recheck(self, actor: Actor, e: Enrolment) -> ActionResult:
        reason = e.attention_reason
        unchanged = ActionResult(e.enrolment_id, ActionOutcome("NEEDS_ATTENTION", "UNKNOWN"))
        if reason == "POSTING_UNKNOWN":
            posting = e.open_posting()
            if posting is None:
                return unchanged
            result = self.d.posting.get_posting_status(posting.cbs_request_ref)
            if result.status not in ("SUCCESS", "FAILED"):
                with self.d.uow() as uow:
                    audit(uow, actor, "ATTENTION_RECHECK", enrolment=e, outcome="UNKNOWN")
                    uow.commit()
                return unchanged
            outcome = self.sale._record_posting(
                actor, e.enrolment_id, posting.posting_id, result, settle=True
            )
            if outcome.result == "DONE":
                return self.sale.issue(actor, e.enrolment_id, readback=True)
            return ActionResult(e.enrolment_id, outcome)
        record = self.sale._read_proposal(actor, e)
        if record is None:
            return unchanged
        if reason == "CANCEL_UNKNOWN":
            if record.cancelled:
                # Cancelled at the insurer; NEEDS_ATTENTION -> CANCELLED is not in the spec (Q36).
                return ActionResult(
                    e.enrolment_id,
                    ActionOutcome(
                        "NEEDS_ATTENTION",
                        "UNKNOWN",
                        "Cancelled at the insurer; closing needs a decision",
                    ),
                )
            with self.d.uow() as uow:
                current = self.sale._reload(uow, e.enrolment_id)
                if current.cancellation is not None:
                    current.cancellation.status = "FAILED"
                self.sale._transition(
                    uow, actor, current, S.ISSUED, "Insurer shows the certificate active"
                )
                uow.enrolments.save(current)
                uow.commit()
            return ActionResult(e.enrolment_id, ActionOutcome())
        if record.certificate_no and record.risk_start_date and record.risk_end_date:
            from backend.adapters.insurer.base import PolicyIssued

            issued = PolicyIssued(
                record.certificate_no, record.risk_start_date, record.risk_end_date
            )
            return self.sale._apply_issued(actor, e.enrolment_id, issued)
        # Not issued at the insurer and the premium was collected: the true state is PAID.
        with self.d.uow() as uow:
            current = self.sale._reload(uow, e.enrolment_id)
            if current.successful_premium_posting() is None:
                return unchanged
            self.sale._transition(uow, actor, current, S.PAID, "Insurer shows no policy yet")
            uow.jobs.enqueue(
                Job(
                    new_id(),
                    "ISSUE_POLICY",
                    current.enrolment_id,
                    f"ISSUE_POLICY:{current.enrolment_id}",
                    "QUEUED",
                    self.d.clock.now() + timedelta(seconds=0),
                    0,
                    self.d.config.issue_retry_limit,
                    self.d.clock.now(),
                )
            )
            uow.enrolments.save(current)
            uow.commit()
        self.d.on_job_enqueued()
        return ActionResult(e.enrolment_id, ActionOutcome("QUEUED_FOR_RETRY"))

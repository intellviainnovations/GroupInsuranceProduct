"""Sale flow actions after approval: proposal, consent, payment, policy, abandon, cancellation.

Pattern for every external step (docs/design/repositories.md 3): UoW 1 checks the state and
persists the intent, the adapter call runs outside any UoW, UoW 2 records the result and the
transition. Unknown outcomes are read back (``get_proposal`` / ``get_posting_status``) before any
retry; a debit is never retried blindly and money is never reversed automatically.
Premium figures come from the insurer; the application only compares them with the plan rate.
"""

from __future__ import annotations

import hashlib
import logging
import time
from collections.abc import Callable
from datetime import datetime, timedelta
from decimal import Decimal
from typing import TypeVar
from uuid import UUID

from backend.adapters.cbs.customer_directory.base import CbsNotFound, CbsUnavailable
from backend.adapters.cbs.posting.base import PostingResult
from backend.adapters.insurer.base import (
    CancellationResult,
    ErrorCategory,
    IssueRequest,
    Outcome,
    PolicyIssued,
    ProposalCreated,
    ProposalNominee,
    ProposalRecord,
    ProposalRequest,
    Rejected,
    Success,
    TransientError,
    UnknownOutcome,
)
from backend.domain.model import (
    Approval,
    Cancellation,
    Document,
    Enrolment,
    InsurerCall,
    Job,
    Posting,
    Role,
    new_id,
)
from backend.domain.repositories import UnitOfWork
from backend.domain.states import EnrolmentStatus as S
from backend.services.common import (
    SYSTEM,
    ActionOutcome,
    ActionResult,
    Actor,
    Deps,
    ServiceError,
    audit,
    field_error,
    invalid_state,
)
from backend.services.views import check_version, load_enrolment, open_cancellation

logger = logging.getLogger("backend.services.sale")
T = TypeVar("T")

_CALL_STATUS = {Success: "SUCCESS", Rejected: "REJECTED", TransientError: "ERROR"}


def _call_status(outcome: object) -> str:
    for kind, status in _CALL_STATUS.items():
        if isinstance(outcome, kind):
            return status
    return "UNKNOWN"


def _category(outcome: object) -> str | None:
    if isinstance(outcome, Rejected | TransientError | UnknownOutcome):
        return outcome.category.value
    return None


class SaleService:
    def __init__(self, deps: Deps) -> None:
        self.d = deps

    # ================================================================ helpers
    def _now(self) -> datetime:
        return self.d.clock.now()

    def _require_branch_user(self, actor: Actor, e: Enrolment, *, ops: bool = False) -> None:
        if actor is SYSTEM:
            return
        if ops and actor.has(Role.OPERATIONS):
            return
        if not actor.has(Role.BRANCH_USER) or actor.branch_code != e.branch_code:
            raise ServiceError(403, "FORBIDDEN")

    def _transition(
        self, uow: UnitOfWork, actor: Actor, e: Enrolment, target: S, reason: str | None = None
    ) -> None:
        now = self._now()
        e.transition(
            target,
            now,
            actor_user_id=actor.user_id,
            reason=reason,
            correlation_id=actor.correlation_id,
        )
        audit(uow, actor, "STATUS_CHANGED", enrolment=e, when=now, detail=f"to={target.value}")

    def _attention(
        self, uow: UnitOfWork, actor: Actor, e: Enrolment, reason: str, text: str
    ) -> None:
        self._transition(uow, actor, e, S.NEEDS_ATTENTION, text)
        e.attention_reason, e.attention_since = reason, self._now()

    def _insurer(
        self, enrolment_id: UUID, operation: str, actor: Actor, call: Callable[[], Outcome[T]]
    ) -> Outcome[T]:
        """Record the call intent, run it outside any UoW, record the result."""
        started = self._now()
        with self.d.uow() as uow:
            e = uow.enrolments.get_for_update(enrolment_id)
            assert e is not None  # noqa: S101
            record = InsurerCall(
                new_id(),
                operation,
                e.next_attempt(operation),
                "UNKNOWN",
                started,
                our_reference=e.our_reference_no,
                correlation_id=actor.correlation_id,
            )
            e.insurer_calls.append(record)
            uow.enrolments.save(e)
            uow.commit()
        begin = time.perf_counter()
        outcome = call()
        duration = int((time.perf_counter() - begin) * 1000)
        with self.d.uow() as uow:
            e = uow.enrolments.get_for_update(enrolment_id)
            assert e is not None  # noqa: S101
            for c in e.insurer_calls:
                if c.call_id == record.call_id:
                    c.status = _call_status(outcome)
                    c.error_category = _category(outcome)
                    if isinstance(outcome, Rejected):
                        c.error_description = outcome.message
                    c.finished_at, c.duration_ms = self._now(), duration
            uow.enrolments.save(e)
            audit(
                uow,
                actor,
                "INSURER_CALL",
                enrolment=e,
                outcome=_call_status(outcome),
                detail=f"operation={operation}",
            )
            uow.commit()
        return outcome

    def _enqueue(self, uow: UnitOfWork, job_type: str, e: Enrolment, max_attempts: int) -> None:
        uow.jobs.enqueue(
            Job(
                new_id(),
                job_type,
                e.enrolment_id,
                f"{job_type}:{e.enrolment_id}",
                "QUEUED",
                self._now() + timedelta(seconds=self.d.config.retry_delay_seconds),
                0,
                max_attempts,
                self._now(),
            )
        )

    # ================================================================ proposal
    def _proposal_request(self, uow: UnitOfWork, e: Enrolment) -> ProposalRequest:
        customer = uow.customers.get(e.customer_id)
        account = (
            uow.customers.get_account(e.customer_account_id) if e.customer_account_id else None
        )
        i = e.insured
        if (
            customer is None
            or account is None
            or e.plan_code is None
            or i.first_name is None
            or i.last_name is None
            or i.gender_code is None
            or i.date_of_birth is None
            or i.mobile is None
            or i.address1 is None
            or i.city is None
            or i.state_code is None
            or i.pincode is None
            or i.occupation_code is None
            or i.any_disability is None
        ):
            raise invalid_state()
        return ProposalRequest(
            our_reference_no=e.our_reference_no,
            branch_code=e.branch_code,
            bank_customer_id=customer.bank_customer_id,
            plan_code=e.plan_code,
            account_no=account.account_no,
            first_name=i.first_name,
            middle_name=i.middle_name,
            last_name=i.last_name,
            gender_code=i.gender_code,
            date_of_birth=i.date_of_birth,
            mobile=i.mobile,
            email=i.email,
            address1=i.address1,
            address2=i.address2,
            city=i.city,
            state_code=i.state_code,
            pincode=i.pincode,
            occupation_code=i.occupation_code,
            other_occupation=i.other_occupation,
            any_disability=i.any_disability,
            disability_description=i.disability_description,
            guardian_name_address=i.guardian_name_address,
            nominees=[
                ProposalNominee(**{k: getattr(n, k) for k in ProposalNominee.__dataclass_fields__})
                for n in e.nominees
            ],
        )

    def create_proposal(
        self, actor: Actor, enrolment_id: UUID, version: int | None, *, last_attempt: bool = False
    ) -> ActionResult:
        with self.d.uow() as uow:
            e = (
                load_enrolment(uow, actor, enrolment_id)
                if actor is not SYSTEM
                else (uow.enrolments.get(enrolment_id))
            )
            if e is None:
                raise invalid_state()
            self._require_branch_user(actor, e)
            if e.status != S.APPROVED:
                raise invalid_state()
            if version is not None:
                check_version(e, version)
            request = self._proposal_request(uow, e)
            needs_readback = e.attention_reason == "PROPOSAL_UNKNOWN" or any(
                c.operation == "create_proposal" and c.status == "UNKNOWN" for c in e.insurer_calls
            )
        if needs_readback:
            done = self._proposal_readback(actor, e)
            if done is not None:
                return done
        outcome = self._insurer(
            enrolment_id,
            "create_proposal",
            actor,
            lambda: self.d.insurer.create_proposal(request, correlation_id=actor.correlation_id),
        )
        if isinstance(outcome, Success):
            return self._apply_proposal(actor, enrolment_id, outcome.data)
        if isinstance(outcome, Rejected):
            with self.d.uow() as uow:
                e = self._reload(uow, enrolment_id)
                e.insurer_message = outcome.message
                self._transition(uow, actor, e, S.PROPOSAL_REJECTED, outcome.message)
                uow.enrolments.save(e)
                uow.commit()
            return ActionResult(
                enrolment_id, ActionOutcome("REJECTED", outcome.category.value, outcome.message)
            )
        if isinstance(outcome, TransientError):
            if actor is not SYSTEM:
                with self.d.uow() as uow:
                    e = self._reload(uow, enrolment_id)
                    self._enqueue(uow, "CREATE_PROPOSAL", e, self.d.config.issue_retry_limit)
                    uow.commit()
                self.d.on_job_enqueued()
            return ActionResult(
                enrolment_id, ActionOutcome("QUEUED_FOR_RETRY", outcome.category.value)
            )
        # Unknown: read the insurer's state by our reference before anything else.
        done = self._proposal_readback(actor, self._snapshot(enrolment_id))
        if done is not None:
            return done
        return ActionResult(enrolment_id, ActionOutcome("NEEDS_ATTENTION", "UNKNOWN"))

    def _snapshot(self, enrolment_id: UUID) -> Enrolment:
        with self.d.uow() as uow:
            return self._reload(uow, enrolment_id)

    def _reload(self, uow: UnitOfWork, enrolment_id: UUID) -> Enrolment:
        e = uow.enrolments.get_for_update(enrolment_id)
        if e is None:
            raise invalid_state()
        return e

    def _proposal_readback(self, actor: Actor, e: Enrolment) -> ActionResult | None:
        """None = the insurer has no such proposal, so a create is safe."""
        outcome = self._insurer(
            e.enrolment_id,
            "get_proposal",
            actor,
            lambda: self.d.insurer.get_proposal(
                proposal_no=e.insurer_proposal_no,
                our_reference=e.our_reference_no,
                correlation_id=actor.correlation_id,
            ),
        )
        if isinstance(outcome, Success) and outcome.data.proposal_no and not outcome.data.cancelled:
            rec = outcome.data
            if (
                rec.net_premium is not None
                and rec.gst_amount is not None
                and rec.gross_premium is not None
            ):
                created = ProposalCreated(
                    rec.proposal_no or "",
                    rec.net_premium,
                    rec.gst_amount,
                    rec.gross_premium,
                    rec.status,
                )
                return self._apply_proposal(actor, e.enrolment_id, created)
        if isinstance(outcome, Rejected) and outcome.category == ErrorCategory.NOT_FOUND:
            with self.d.uow() as uow:
                current = self._reload(uow, e.enrolment_id)
                current.attention_reason = None
                for c in current.insurer_calls:  # settled: the earlier create did not take effect
                    if c.operation == "create_proposal" and c.status == "UNKNOWN":
                        c.status = "ERROR"
                uow.enrolments.save(current)
                uow.commit()
            return None
        with self.d.uow() as uow:
            current = self._reload(uow, e.enrolment_id)
            # No APPROVED -> NEEDS_ATTENTION transition exists: flag it and stop.
            current.attention_reason, current.attention_since = "PROPOSAL_UNKNOWN", self._now()
            uow.enrolments.save(current)
            audit(uow, actor, "PROPOSAL_UNKNOWN", enrolment=current, outcome="UNKNOWN")
            uow.commit()
        return ActionResult(e.enrolment_id, ActionOutcome("NEEDS_ATTENTION", "UNKNOWN"))

    def _apply_proposal(
        self, actor: Actor, enrolment_id: UUID, data: ProposalCreated
    ) -> ActionResult:
        with self.d.uow() as uow:
            e = self._reload(uow, enrolment_id)
            rate = uow.reference.get_rate(e.rate_id) if e.rate_id else None
            e.insurer_proposal_no = data.proposal_no
            e.proposal_created_at = self._now()
            e.net_premium, e.gst_amount = data.net_premium, data.gst_amount
            e.gross_premium = data.gross_premium
            # Comparison only, never a calculation: a mismatch stops the sale for a human (Q30).
            e.premium_matches_rate = rate is not None and (
                data.net_premium == rate.net_premium
                and data.gst_amount == rate.gst_amount
                and data.gross_premium == rate.gross_premium
            )
            e.attention_reason = None
            self._transition(uow, actor, e, S.PROPOSAL_CREATED)
            uow.enrolments.save(e)
            uow.commit()
        return ActionResult(enrolment_id, ActionOutcome())

    # ================================================================ consent
    def record_consent(
        self,
        actor: Actor,
        enrolment_id: UUID,
        version: int,
        method: str,
        reference: str,
        confirmed_amount: Decimal | None,
    ) -> ActionResult:
        now = self._now()
        with self.d.uow() as uow:
            e = load_enrolment(uow, actor, enrolment_id)
            self._require_branch_user(actor, e)
            if e.status not in (S.PROPOSAL_CREATED, S.PAYMENT_FAILED):
                raise invalid_state()
            check_version(e, version)
            errors = []
            if not any(c.code == method for c in uow.reference.codes("CONSENT_METHOD")):
                errors.append(field_error("method", "INVALID_CODE"))
            if confirmed_amount is not None and confirmed_amount != e.gross_premium:
                errors.append(
                    field_error(
                        "confirmed_amount", "OUT_OF_RANGE", "Must equal the insurer's gross premium"
                    )
                )
            if errors:
                raise ServiceError(422, "VALIDATION_FAILED", errors)
            e.consent_method, e.consent_ref, e.consent_at = method, reference, now
            e.consent_used = False
            e.updated_at = now
            uow.enrolments.save(e)
            audit(uow, actor, "CONSENT_RECORDED", enrolment=e, when=now, detail=f"method={method}")
            uow.commit()
        return ActionResult(enrolment_id, ActionOutcome())

    # ================================================================ payment
    def post_payment(self, actor: Actor, enrolment_id: UUID, version: int) -> ActionResult:
        with self.d.uow() as uow:
            e = load_enrolment(uow, actor, enrolment_id)
            self._require_branch_user(actor, e)
            if e.status not in (S.PROPOSAL_CREATED, S.PAYMENT_FAILED):
                raise invalid_state()
            check_version(e, version)
            if e.open_posting() is not None:
                raise ServiceError(409, "POSTING_UNRESOLVED")
            if e.premium_matches_rate is not True:
                raise ServiceError(409, "PREMIUM_MISMATCH")
            if e.consent_at is None or e.consent_used:
                raise ServiceError(409, "CONSENT_REQUIRED")
            account = (
                uow.customers.get_account(e.customer_account_id) if e.customer_account_id else None
            )
            pool = uow.reference.active_pool_account(self._now().date())
            if account is None or pool is None or e.gross_premium is None:
                raise invalid_state()
        # Re-read the debit account just before posting; the CBS transaction stays the authority.
        try:
            current = self.d.directory.get_account(account.account_no)
            eligible = (current.status or "").upper() in self.d.config.selectable_statuses
        except CbsNotFound:
            eligible = False
        except CbsUnavailable as exc:
            raise ServiceError(503, "CBS_UNAVAILABLE") from exc
        if not eligible:
            with self.d.uow() as uow:
                audit(
                    uow,
                    actor,
                    "POSTING_REFUSED",
                    enrolment=e,
                    outcome="DENIED",
                    detail="account not eligible at re-read",
                )
                uow.commit()
            raise ServiceError(409, "ACCOUNT_NOT_ELIGIBLE")
        now = self._now()
        with self.d.uow() as uow:
            e = self._reload(uow, enrolment_id)
            check_version(e, version)
            attempt = 1 + sum(1 for p in e.postings if p.kind == "PREMIUM")
            posting = Posting(
                new_id(),
                "PREMIUM",
                e.gross_premium or Decimal("0"),
                account.customer_account_id,
                pool.pool_account_id,
                f"{e.our_reference_no}-P{attempt}",
                "PENDING",
                attempt,
                now,
                created_by=actor.user_id,
            )
            e.postings.append(posting)
            e.consent_used = True
            self._transition(uow, actor, e, S.PAYMENT_PENDING)
            uow.enrolments.save(e)
            audit(
                uow,
                actor,
                "POSTING_STARTED",
                enrolment=e,
                when=now,
                detail=f"ref={posting.cbs_request_ref}",
            )
            uow.commit()
        result = self.d.posting.post_premium(
            posting.cbs_request_ref,
            account.account_no,
            pool.account_no,
            posting.amount,
            f"GPA premium {e.our_reference_no}",
        )
        if result.status == "UNKNOWN":
            self._record_posting(actor, enrolment_id, posting.posting_id, result, settle=False)
            result = self.d.posting.get_posting_status(posting.cbs_request_ref)
            if result.status == "NOT_FOUND":
                result = PostingResult("UNKNOWN")  # absence after a timeout is not proof
        outcome = self._record_posting(actor, enrolment_id, posting.posting_id, result, settle=True)
        if outcome.result == "DONE":
            return self.issue(actor, enrolment_id, readback=False)
        return ActionResult(enrolment_id, outcome)

    def _record_posting(
        self,
        actor: Actor,
        enrolment_id: UUID,
        posting_id: UUID,
        result: PostingResult,
        *,
        settle: bool,
    ) -> ActionOutcome:
        now = self._now()
        with self.d.uow() as uow:
            e = self._reload(uow, enrolment_id)
            p = next(x for x in e.postings if x.posting_id == posting_id)
            outcome = ActionOutcome()
            if result.status == "SUCCESS":
                p.status, p.cbs_tran_id, p.cbs_tran_at = (
                    "SUCCESS",
                    result.tran_id,
                    result.tran_at or now,
                )
                p.completed_at = now
                self._transition(uow, actor, e, S.PAID)
            elif result.status == "FAILED":
                p.status, p.completed_at = "FAILED", now
                p.error_code, p.error_text = "DECLINED", (result.reason or "")[:300] or None
                self._transition(uow, actor, e, S.PAYMENT_FAILED, "CBS declined")
                outcome = ActionOutcome("REJECTED", "CBS_DECLINED", p.error_text)
            else:
                p.status = "UNKNOWN"
                if settle:
                    self._attention(
                        uow, actor, e, "POSTING_UNKNOWN", "CBS outcome unknown and not resolvable"
                    )
                    outcome = ActionOutcome("NEEDS_ATTENTION", "UNKNOWN")
            uow.enrolments.save(e)
            audit(
                uow,
                actor,
                "POSTING_RESULT",
                enrolment=e,
                when=now,
                outcome=p.status,
                detail=f"ref={p.cbs_request_ref}",
            )
            uow.commit()
        return outcome

    # ================================================================ policy
    def retry_issue(self, actor: Actor, enrolment_id: UUID, version: int) -> ActionResult:
        with self.d.uow() as uow:
            e = load_enrolment(uow, actor, enrolment_id)
            self._require_branch_user(actor, e, ops=True)
            pdf = uow.documents.latest(e.enrolment_id, "COI") is not None
            if not (e.status == S.PAID or (e.status == S.ISSUED and not pdf)):
                raise invalid_state()
            check_version(e, version)
        return self.issue(actor, enrolment_id, readback=True)

    def issue(
        self,
        actor: Actor,
        enrolment_id: UUID,
        *,
        readback: bool,
        from_job: bool = False,
        last_attempt: bool = False,
    ) -> ActionResult:
        e = self._snapshot(enrolment_id)
        if e.status == S.ISSUED:
            self._fetch_certificate(actor, e)
            return ActionResult(enrolment_id, ActionOutcome())
        if e.status != S.PAID:
            return ActionResult(enrolment_id, ActionOutcome())
        if readback or any(
            c.operation == "issue_policy" and c.status == "UNKNOWN" for c in e.insurer_calls
        ):
            record = self._read_proposal(actor, e)
            if (
                record is not None
                and record.certificate_no
                and record.risk_start_date
                and record.risk_end_date
            ):
                issued = PolicyIssued(
                    record.certificate_no, record.risk_start_date, record.risk_end_date
                )
                return self._apply_issued(actor, enrolment_id, issued)
        customer_cif, posting = self._issue_inputs(e)
        request = IssueRequest(
            our_reference_no=e.our_reference_no,
            proposal_no=e.insurer_proposal_no or "",
            bank_customer_id=customer_cif,
            payment_status="SUCCESS",
            transaction_no=posting.cbs_tran_id if posting else None,
            transaction_date=posting.cbs_tran_at.date()
            if posting and posting.cbs_tran_at
            else None,
        )
        outcome = self._insurer(
            enrolment_id,
            "issue_policy",
            actor,
            lambda: self.d.insurer.issue_policy(request, correlation_id=actor.correlation_id),
        )
        if isinstance(outcome, Success):
            return self._apply_issued(actor, enrolment_id, outcome.data)
        if isinstance(outcome, UnknownOutcome):
            record = self._read_proposal(actor, self._snapshot(enrolment_id))
            if (
                record is not None
                and record.certificate_no
                and record.risk_start_date
                and record.risk_end_date
            ):
                issued = PolicyIssued(
                    record.certificate_no, record.risk_start_date, record.risk_end_date
                )
                return self._apply_issued(actor, enrolment_id, issued)
            if record is None:
                with self.d.uow() as uow:
                    e = self._reload(uow, enrolment_id)
                    self._attention(uow, actor, e, "ISSUE_UNKNOWN", "Policy issue outcome unknown")
                    uow.enrolments.save(e)
                    uow.commit()
                return ActionResult(enrolment_id, ActionOutcome("NEEDS_ATTENTION", "UNKNOWN"))
        # Not issued (rejected, transient, or read back as not issued): keep PAID and retry.
        category = _category(outcome)
        message = outcome.message if isinstance(outcome, Rejected) else None
        with self.d.uow() as uow:
            e = self._reload(uow, enrolment_id)
            if from_job and last_attempt:
                self._attention(
                    uow,
                    actor,
                    e,
                    "ISSUE_RETRIES_EXHAUSTED",
                    "Policy not issued after the retry limit",
                )
                uow.enrolments.save(e)
                uow.commit()
                return ActionResult(
                    enrolment_id, ActionOutcome("NEEDS_ATTENTION", category, message)
                )
            if not from_job:
                self._enqueue(uow, "ISSUE_POLICY", e, self.d.config.issue_retry_limit)
            uow.enrolments.save(e)
            uow.commit()
        if not from_job:
            self.d.on_job_enqueued()
        return ActionResult(enrolment_id, ActionOutcome("QUEUED_FOR_RETRY", category, message))

    def _issue_inputs(self, e: Enrolment) -> tuple[str, Posting | None]:
        with self.d.uow() as uow:
            customer = uow.customers.get(e.customer_id)
        return (customer.bank_customer_id if customer else ""), e.successful_premium_posting()

    def _read_proposal(self, actor: Actor, e: Enrolment) -> ProposalRecord | None:
        outcome = self._insurer(
            e.enrolment_id,
            "get_proposal",
            actor,
            lambda: self.d.insurer.get_proposal(
                proposal_no=e.insurer_proposal_no,
                our_reference=e.our_reference_no,
                correlation_id=actor.correlation_id,
            ),
        )
        return outcome.data if isinstance(outcome, Success) else None

    def _apply_issued(self, actor: Actor, enrolment_id: UUID, issued: PolicyIssued) -> ActionResult:
        with self.d.uow() as uow:
            e = self._reload(uow, enrolment_id)
            if e.status != S.ISSUED:
                e.certificate_no = issued.certificate_no
                e.risk_start_date, e.risk_end_date = issued.risk_start_date, issued.risk_end_date
                e.issued_at = self._now()
                self._transition(uow, actor, e, S.ISSUED)
                uow.enrolments.save(e)
            for job in uow.jobs.list(entity_id=enrolment_id):
                if job.job_type == "ISSUE_POLICY" and job.status in ("QUEUED", "FAILED"):
                    uow.jobs.complete(job.job_id)
            uow.commit()
        self._fetch_certificate(actor, e)
        return ActionResult(enrolment_id, ActionOutcome())

    def _fetch_certificate(self, actor: Actor, e: Enrolment) -> None:
        if not e.certificate_no:
            return
        with self.d.uow() as uow:
            if uow.documents.latest(e.enrolment_id, "COI") is not None:
                return
        cert_no, proposal_no = e.certificate_no, e.insurer_proposal_no
        outcome = self._insurer(
            e.enrolment_id,
            "fetch_certificate",
            actor,
            lambda: self.d.insurer.fetch_certificate(
                cert_no, proposal_no, correlation_id=actor.correlation_id
            ),
        )
        if not isinstance(outcome, Success):
            return  # stays ISSUED without a PDF; RETRY_ISSUE re-fetches it
        content = outcome.data.content
        with self.d.uow() as uow:
            uow.documents.add(
                Document(
                    new_id(),
                    e.enrolment_id,
                    "COI",
                    f"COI-{cert_no.replace('/', '-')}.pdf",
                    outcome.data.content_type,
                    len(content),
                    hashlib.sha256(content).hexdigest(),
                    content,
                    "INSURER",
                    self._now(),
                )
            )
            audit(uow, actor, "CERTIFICATE_STORED", enrolment=e)
            uow.commit()

    # ================================================================ abandon
    def abandon(self, actor: Actor, enrolment_id: UUID, version: int, comment: str) -> ActionResult:
        with self.d.uow() as uow:
            e = load_enrolment(uow, actor, enrolment_id)
            self._require_branch_user(actor, e)
            if e.status not in (S.PROPOSAL_CREATED, S.PAYMENT_FAILED) or not e.insurer_proposal_no:
                raise invalid_state()
            check_version(e, version)
            if e.open_posting() is not None:
                raise ServiceError(409, "POSTING_UNRESOLVED")
        proposal_no = e.insurer_proposal_no
        outcome = self._insurer(
            enrolment_id,
            "cancel_proposal",
            actor,
            lambda: self.d.insurer.cancel_proposal(
                proposal_no, our_reference=e.our_reference_no, correlation_id=actor.correlation_id
            ),
        )
        if isinstance(outcome, Success):
            with self.d.uow() as uow:
                e = self._reload(uow, enrolment_id)
                self._transition(uow, actor, e, S.PROPOSAL_CANCELLED, comment)
                uow.enrolments.save(e)
                uow.commit()
            return ActionResult(enrolment_id, ActionOutcome())
        if isinstance(outcome, Rejected):
            return ActionResult(
                enrolment_id, ActionOutcome("REJECTED", outcome.category.value, outcome.message)
            )
        return ActionResult(
            enrolment_id,
            ActionOutcome(
                "NEEDS_ATTENTION" if isinstance(outcome, UnknownOutcome) else "QUEUED_FOR_RETRY",
                _category(outcome),
            ),
        )

    # ================================================================ cancellation
    def request_cancellation(
        self, actor: Actor, enrolment_id: UUID, version: int, reason_code: str, remarks: str | None
    ) -> ActionResult:
        now = self._now()
        with self.d.uow() as uow:
            e = load_enrolment(uow, actor, enrolment_id)
            self._require_branch_user(actor, e)
            if e.status != S.ISSUED or open_cancellation(e):
                raise invalid_state()
            check_version(e, version)
            if not any(c.code == reason_code for c in uow.reference.codes("CANCEL_REASON")):
                raise ServiceError(
                    422, "VALIDATION_FAILED", [field_error("reason_code", "INVALID_CODE")]
                )
            assert actor.user_id is not None  # noqa: S101
            checker_needed = (
                uow.reference.setting("maker_checker.cancellation") or "true"
            ) == "true"
            cancellation = Cancellation(
                new_id(),
                reason_code,
                "PENDING_CHECK" if checker_needed else "SUBMITTED",
                actor.user_id,
                now,
                remarks=remarks,
            )
            if checker_needed:
                approval = Approval(
                    new_id(),
                    "CANCELLATION",
                    cancellation.cancellation_id,
                    e.enrolment_id,
                    e.branch_code,
                    "CANCEL_CERTIFICATE",
                    actor.user_id,
                    "PENDING",
                    now,
                    maker_comment=remarks,
                )
                cancellation.approval_id = approval.approval_id
                uow.approvals.add(approval)
            e.cancellation = cancellation
            e.cancel_reason_code = reason_code
            e.updated_at = now
            uow.enrolments.save(e)
            audit(
                uow,
                actor,
                "CANCELLATION_REQUESTED",
                enrolment=e,
                when=now,
                detail=f"reason={reason_code}",
            )
            uow.commit()
        if checker_needed:
            return ActionResult(enrolment_id, ActionOutcome("PENDING_APPROVAL"))
        return self.execute_cancellation(actor, enrolment_id)

    def execute_cancellation(self, actor: Actor, enrolment_id: UUID) -> ActionResult:
        with self.d.uow() as uow:
            e = self._reload(uow, enrolment_id)
            if e.status == S.ISSUED:
                self._transition(uow, actor, e, S.CANCELLATION_PENDING, "Cancellation requested")
            if e.status != S.CANCELLATION_PENDING or e.cancellation is None or not e.certificate_no:
                raise invalid_state()
            e.cancellation.status = "SUBMITTED"
            uow.enrolments.save(e)
            uow.commit()
        cert_no = e.certificate_no
        outcome: Outcome[CancellationResult] = self._insurer(
            enrolment_id,
            "cancel_certificate",
            actor,
            lambda: self.d.insurer.cancel_certificate(
                cert_no, our_reference=e.our_reference_no, correlation_id=actor.correlation_id
            ),
        )
        if isinstance(outcome, Success):
            return self._apply_cancelled(actor, enrolment_id, outcome.data)
        with self.d.uow() as uow:
            e = self._reload(uow, enrolment_id)
            assert e.cancellation is not None  # noqa: S101
            if isinstance(outcome, UnknownOutcome):
                self._attention(uow, actor, e, "CANCEL_UNKNOWN", "Cancellation outcome unknown")
                result = ActionOutcome("NEEDS_ATTENTION", "UNKNOWN")
            elif isinstance(outcome, Rejected):
                # No CANCELLATION_PENDING -> ISSUED transition exists in the spec (open, Q36).
                e.cancellation.status = "FAILED"
                result = ActionOutcome("REJECTED", outcome.category.value, outcome.message)
            else:
                self._enqueue(uow, "CANCEL_CERTIFICATE", e, self.d.config.issue_retry_limit)
                result = ActionOutcome("QUEUED_FOR_RETRY", _category(outcome))
            uow.enrolments.save(e)
            uow.commit()
        return ActionResult(enrolment_id, result)

    def _apply_cancelled(
        self, actor: Actor, enrolment_id: UUID, data: CancellationResult
    ) -> ActionResult:
        now = self._now()
        refund = data.refund_amount
        posting: Posting | None = None
        original: Posting | None = None
        with self.d.uow() as uow:
            e = self._reload(uow, enrolment_id)
            assert e.cancellation is not None  # noqa: S101
            e.cancellation.refund_amount = refund  # as returned by the insurer
            account = (
                uow.customers.get_account(e.customer_account_id) if e.customer_account_id else None
            )
            pool = uow.reference.active_pool_account(now.date())
            if refund is not None and refund > 0 and account is not None and pool is not None:
                original = e.successful_premium_posting()
                posting = Posting(
                    new_id(),
                    "REFUND",
                    refund,
                    account.customer_account_id,
                    pool.pool_account_id,
                    f"{e.our_reference_no}-R1",
                    "PENDING",
                    1,
                    now,
                    created_by=actor.user_id,
                )
                e.postings.append(posting)
                e.cancellation.refund_posting_id = posting.posting_id
            uow.enrolments.save(e)
            uow.commit()
        result = PostingResult("SUCCESS")
        if posting is not None and account is not None and pool is not None:
            result = self.d.posting.post_refund(
                posting.cbs_request_ref,
                account.account_no,
                pool.account_no,
                posting.amount,
                f"GPA refund {e.our_reference_no}",
                original.cbs_request_ref if original else None,
            )
        with self.d.uow() as uow:
            e = self._reload(uow, enrolment_id)
            assert e.cancellation is not None  # noqa: S101
            p = next(
                (x for x in e.postings if posting and x.posting_id == posting.posting_id), None
            )
            if result.status == "SUCCESS":
                if p is not None:
                    p.status, p.cbs_tran_id, p.cbs_tran_at = (
                        "SUCCESS",
                        result.tran_id,
                        result.tran_at,
                    )
                    p.completed_at = now
                e.cancellation.status, e.cancellation.completed_at = "COMPLETED", now
                e.cancellation.refund_at = now if p is not None else None
                e.cancelled_at = now
                self._transition(uow, actor, e, S.CANCELLED)
                outcome = ActionOutcome()
            else:
                if p is not None:
                    p.status = "FAILED" if result.status == "FAILED" else "UNKNOWN"
                self._attention(uow, actor, e, "CANCEL_UNKNOWN", "Refund posting not completed")
                outcome = ActionOutcome("NEEDS_ATTENTION", "UNKNOWN")
            uow.enrolments.save(e)
            uow.commit()
        return ActionResult(enrolment_id, outcome)

    # ================================================================ jobs
    def job_handlers(self) -> dict[str, Callable[[Job], bool]]:
        def create(job: Job) -> bool:
            assert job.entity_id is not None  # noqa: S101
            try:
                result = self.create_proposal(SYSTEM, job.entity_id, None)
            except ServiceError:
                return True  # no longer APPROVED: nothing to do
            return result.outcome.result != "QUEUED_FOR_RETRY"

        def issue(job: Job) -> bool:
            assert job.entity_id is not None  # noqa: S101
            result = self.issue(
                SYSTEM,
                job.entity_id,
                readback=True,
                from_job=True,
                last_attempt=job.attempts >= job.max_attempts,
            )
            return result.outcome.result != "QUEUED_FOR_RETRY"

        def cancel(job: Job) -> bool:
            assert job.entity_id is not None  # noqa: S101
            try:
                result = self.execute_cancellation(SYSTEM, job.entity_id)
            except ServiceError:
                return True
            return result.outcome.result != "QUEUED_FOR_RETRY"

        return {"CREATE_PROPOSAL": create, "ISSUE_POLICY": issue, "CANCEL_CERTIFICATE": cancel}

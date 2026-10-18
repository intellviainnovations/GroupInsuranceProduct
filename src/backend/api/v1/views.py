"""Map service read models to API schemas. Account numbers, CIF and CBS transaction ids leave
only masked; payloads and nominee bank account numbers never leave."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from backend.adapters.cbs.customer_directory.base import CbsAccountRecord
from backend.api.v1 import schemas as s
from backend.domain.model import CustomerAccount, Enrolment, PlanRate, User
from backend.domain.model import Plan as PlanModel
from backend.services.common import mask
from backend.services.enrolments import LookupView
from backend.services.views import ApprovalBundle, EnrolmentBundle


def money(value: Decimal | None) -> str | None:
    return None if value is None else f"{value.quantize(Decimal('0.01')):.2f}"


def _m(value: Decimal) -> str:
    return f"{value.quantize(Decimal('0.01')):.2f}"


def percent(value: Decimal) -> str:
    text = format(value.normalize(), "f")
    return text


def utc(value: datetime) -> datetime:
    return value.astimezone(UTC)


def user_ref(user: User | None, user_id: UUID | None = None) -> s.UserRef:
    if user is None:
        return s.UserRef(user_id=user_id or UUID(int=0), roll_no="UNKNOWN")
    return s.UserRef(user_id=user.user_id, roll_no=user.roll_no, display_name=user.display_name)


def plan_rate(rate: PlanRate | None) -> s.PlanRate | None:
    if rate is None:
        return None
    return s.PlanRate(
        rate_id=rate.rate_id,
        sum_insured=_m(rate.sum_insured),
        net_premium=_m(rate.net_premium),
        gst_amount=_m(rate.gst_amount),
        gross_premium=_m(rate.gross_premium),
        policy_term_days=rate.policy_term_days,
        effective_from=rate.effective_from,
        synthetic=rate.synthetic,
        note=rate.note,
    )


def plan(p: PlanModel, rate: PlanRate | None) -> s.Plan:
    return s.Plan(plan_code=p.plan_code, name=p.name, rate=plan_rate(rate))


def lookup_result(view: LookupView) -> s.CustomerLookupResult:
    c = view.customer
    return s.CustomerLookupResult(
        customer=s.CbsCustomer(
            cif_masked=mask(c.cif) or "",
            first_name=c.first_name,
            middle_name=c.middle_name,
            last_name=c.last_name,
            gender_code=c.gender_code,
            date_of_birth=c.date_of_birth,
            mobile_masked=mask(c.mobile),
            city=c.city,
            state_code=c.state_code,
            kyc_status=c.kyc_status,
            customer_status=c.customer_status,
            home_branch_code=c.home_branch_code,
        ),
        accounts=[cbs_record(a.account_key, a.record, a.selectable) for a in view.accounts],
        fetched_at=utc(view.fetched_at),
    )


def cbs_record(key: str, a: CbsAccountRecord, selectable: bool) -> s.CbsAccount:
    return s.CbsAccount(
        account_key=key,
        account_no_masked=mask(a.account_no) or "",
        account_type=a.account_type,
        account_status=a.status,
        branch_code=a.branch_code,
        joint_account=a.joint_account,
        holder_name=a.holder_name,
        selectable=selectable,
    )


def account(a: CustomerAccount, selectable_statuses: frozenset[str]) -> s.CbsAccount:
    return s.CbsAccount(
        account_key=a.account_no_hash,
        account_no_masked=mask(a.account_no) or "",
        account_type=a.account_type,
        account_status=a.account_status,
        branch_code=a.cbs_branch_code,
        joint_account=a.joint_account,
        holder_name=a.holder_name,
        selectable=(a.account_status or "").upper() in selectable_statuses,
    )


def approval(b: ApprovalBundle) -> s.Approval:
    a = b.approval
    return s.Approval(
        approval_id=a.approval_id,
        entity_type=a.entity_type,  # type: ignore[arg-type]
        entity_id=a.entity_id,
        enrolment_id=a.enrolment_id,
        our_reference_no=b.our_reference_no,
        insured_name=(b.insured_name or "")[:182] or None,
        action=a.action,  # type: ignore[arg-type]
        proposed_status=a.proposed_status,  # type: ignore[arg-type]
        evidence_ref=a.evidence_ref,
        status=a.status,  # type: ignore[arg-type]
        maker=user_ref(b.maker, a.maker_user_id),
        checker=user_ref(b.checker, a.checker_user_id) if a.checker_user_id else None,
        maker_comment=a.maker_comment,
        checker_comment=a.checker_comment,
        requested_at=utc(a.requested_at),
        decided_at=utc(a.decided_at) if a.decided_at else None,
        can_decide=b.can_decide,
    )


def summary(e: Enrolment, maker: User | None) -> s.EnrolmentSummary:
    return s.EnrolmentSummary(
        enrolment_id=e.enrolment_id,
        our_reference_no=e.our_reference_no,
        status=e.status.value,
        status_changed_at=utc(e.status_changed_at),
        created_at=utc(e.created_at),
        branch_code=e.branch_code,
        insured_name=(e.insured.full_name or "-")[:182],
        plan_code=e.plan_code,
        gross_premium=money(e.gross_premium),
        insurer_proposal_no=e.insurer_proposal_no,
        certificate_no=e.certificate_no,
        created_by=user_ref(maker, e.created_by),
        attention_reason=e.attention_reason,  # type: ignore[arg-type]
    )


def detail(b: EnrolmentBundle, selectable_statuses: frozenset[str]) -> s.EnrolmentDetail:
    e = b.enrolment
    insured_values: dict[str, Any] = {
        k: getattr(e.insured, k) for k in s.InsuredInput.model_fields if hasattr(e.insured, k)
    }
    nominees = [
        s.Nominee(
            seq=n.seq,
            name=n.name,
            relation_code=n.relation_code,
            share_percent=percent(n.share_percent),
            date_of_birth=n.date_of_birth,
            age=n.age,
            gender_code=n.gender_code,
            mobile=n.mobile,
            email=n.email,
            present_address=n.present_address,
            permanent_address=n.permanent_address,
            bank_account_no=None,
            bank_account_masked=mask(n.bank_account_no),
            ifsc=n.ifsc,
            bank_name=n.bank_name,
            account_holder_name=n.account_holder_name,
            appointee_name=n.appointee_name,
            appointee_relation_code=n.appointee_relation_code,
            appointee_dob=n.appointee_dob,
            appointee_age=n.appointee_age,
            appointee_gender_code=n.appointee_gender_code,
        )
        for n in e.nominees
    ]
    premium = None
    if e.net_premium is not None and e.gst_amount is not None and e.gross_premium is not None:
        premium = s.Premium(
            net_premium=_m(e.net_premium),
            gst_amount=_m(e.gst_amount),
            gross_premium=_m(e.gross_premium),
            matches_rate=bool(e.premium_matches_rate),
        )
    certificate = None
    if e.certificate_no and e.risk_start_date and e.risk_end_date and e.issued_at:
        certificate = s.CertificateInfo(
            certificate_no=e.certificate_no,
            risk_start_date=e.risk_start_date,
            risk_end_date=e.risk_end_date,
            issued_at=utc(e.issued_at),
            pdf_available=b.pdf_available,
        )
    cancellation = None
    if e.cancellation is not None:
        c = e.cancellation
        cancellation = s.CancellationInfo(
            cancellation_id=c.cancellation_id,
            reason_code=c.reason_code,
            status=c.status,  # type: ignore[arg-type]
            requested_by=user_ref(b.users.get(c.requested_by), c.requested_by),
            requested_at=utc(c.requested_at),
            refund_amount=money(c.refund_amount),
            completed_at=utc(c.completed_at) if c.completed_at else None,
        )
    customer_cif = b.customer.bank_customer_id if b.customer else ""
    fetched = b.customer.cbs_fetched_at if b.customer else None
    if b.account is None:
        raise ValueError("enrolment without a debit account")
    return s.EnrolmentDetail(
        enrolment_id=e.enrolment_id,
        our_reference_no=e.our_reference_no,
        status=e.status.value,
        status_changed_at=utc(e.status_changed_at),
        version=e.version,
        branch=s.Branch(code=e.branch_code, name=b.branch.name if b.branch else None),
        created_by=user_ref(b.maker, e.created_by),
        created_at=utc(e.created_at),
        updated_at=utc(e.updated_at),
        customer=s.EnrolmentCustomer(
            customer_id=e.customer_id,
            cif_masked=mask(customer_cif) or "",
            cbs_fetched_at=utc(fetched) if fetched else None,
        ),
        debit_account=account(b.account, selectable_statuses),
        insured=s.Insured(cbs_sourced_fields=list(e.insured.cbs_sourced_fields), **insured_values),
        nominees=nominees,
        plan=plan(b.plan, b.rate) if b.plan else None,
        proposal=(
            s.Proposal(
                insurer_proposal_no=e.insurer_proposal_no, created_at=utc(e.proposal_created_at)
            )
            if e.insurer_proposal_no and e.proposal_created_at
            else None
        ),
        premium=premium,
        consent=(
            s.Consent(
                method=e.consent_method, reference=e.consent_ref, consented_at=utc(e.consent_at)
            )
            if e.consent_method and e.consent_ref and e.consent_at
            else None
        ),
        certificate=certificate,
        postings=[
            s.PostingItem(
                posting_id=p.posting_id,
                kind=p.kind,  # type: ignore[arg-type]
                amount=_m(p.amount),
                status=p.status,  # type: ignore[arg-type]
                cbs_request_ref=p.cbs_request_ref,
                cbs_tran_id_masked=mask(p.cbs_tran_id),
                cbs_tran_at=utc(p.cbs_tran_at) if p.cbs_tran_at else None,
                attempt_no=p.attempt_no,
                error_code=p.error_code,
                requested_at=utc(p.requested_at),
                completed_at=utc(p.completed_at) if p.completed_at else None,
            )
            for p in e.postings
        ],
        insurer_calls=[
            s.InsurerCallItem(
                operation=c.operation,
                attempt_no=c.attempt_no,
                status=c.status,  # type: ignore[arg-type]
                error_category=c.error_category,
                started_at=utc(c.started_at),
                duration_ms=c.duration_ms,
            )
            for c in e.insurer_calls[-100:]
        ],
        status_history=[
            s.StatusHistoryItem(
                from_status=h.from_status.value if h.from_status else None,
                to_status=h.to_status.value,
                reason=(h.reason or None) and h.reason[:300] if h.reason else None,
                actor=user_ref(b.users.get(h.actor_user_id), h.actor_user_id)
                if h.actor_user_id
                else None,
                correlation_id=h.correlation_id,
                changed_at=utc(h.changed_at),
            )
            for h in e.history
        ],
        approvals=[approval(a) for a in b.approvals[-20:]],
        documents=[
            s.DocumentItem(
                document_id=d.document_id,
                kind=d.kind,  # type: ignore[arg-type]
                file_name=d.file_name,
                size_bytes=d.size_bytes,
                created_at=utc(d.created_at),
            )
            for d in b.documents
        ],
        cancellation=cancellation,
        attention=(
            s.AttentionInfo(reason=e.attention_reason, since=utc(e.attention_since))  # type: ignore[arg-type]
            if e.attention_reason and e.attention_since
            else None
        ),
        allowed_actions=b.allowed_actions,  # type: ignore[arg-type]
    )

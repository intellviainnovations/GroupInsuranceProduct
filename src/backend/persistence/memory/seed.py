"""Load the synthetic seed (synthetic_v1.json) into a MemoryStore.

Timestamps are offsets resolved against the clock at load time, so the dashboard looks current.
Each seeded enrolment walks the spec's transitions from DRAFT to its seeded status, so history,
postings, insurer calls, approvals, documents and the audit chain are consistent.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

from backend.domain.model import (
    Approval,
    AuditEvent,
    Branch,
    Cancellation,
    Customer,
    CustomerAccount,
    Document,
    Enrolment,
    Insured,
    InsurerCall,
    Job,
    Nominee,
    Plan,
    PlanRate,
    PoolAccount,
    Posting,
    RefCode,
    Role,
    User,
    new_id,
)
from backend.domain.states import EnrolmentStatus as S
from backend.persistence.memory.store import MemoryStore, MemoryUnitOfWork
from backend.platform.pdf import specimen_pdf

SEED_PATH = Path(__file__).resolve().parent.parent / "seed" / "synthetic_v1.json"

_PATHS: dict[str, list[S]] = {
    "DRAFT": [],
    "PENDING_CHECK": [S.PENDING_CHECK],
    "REJECTED": [S.PENDING_CHECK, S.REJECTED],
    "APPROVED": [S.PENDING_CHECK, S.APPROVED],
    "PROPOSAL_REJECTED": [S.PENDING_CHECK, S.APPROVED, S.PROPOSAL_REJECTED],
    "PROPOSAL_CREATED": [S.PENDING_CHECK, S.APPROVED, S.PROPOSAL_CREATED],
    "PROPOSAL_CANCELLED": [S.PENDING_CHECK, S.APPROVED, S.PROPOSAL_CREATED, S.PROPOSAL_CANCELLED],
    "PAYMENT_PENDING": [S.PENDING_CHECK, S.APPROVED, S.PROPOSAL_CREATED, S.PAYMENT_PENDING],
    "PAYMENT_FAILED": [
        S.PENDING_CHECK,
        S.APPROVED,
        S.PROPOSAL_CREATED,
        S.PAYMENT_PENDING,
        S.PAYMENT_FAILED,
    ],
    "PAID": [S.PENDING_CHECK, S.APPROVED, S.PROPOSAL_CREATED, S.PAYMENT_PENDING, S.PAID],
    "ISSUED": [
        S.PENDING_CHECK,
        S.APPROVED,
        S.PROPOSAL_CREATED,
        S.PAYMENT_PENDING,
        S.PAID,
        S.ISSUED,
    ],
    "CANCELLED": [
        S.PENDING_CHECK,
        S.APPROVED,
        S.PROPOSAL_CREATED,
        S.PAYMENT_PENDING,
        S.PAID,
        S.ISSUED,
        S.CANCELLATION_PENDING,
        S.CANCELLED,
    ],
}


def read_seed(path: Path = SEED_PATH) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        data: dict[str, Any] = json.load(handle)
    return data


def _d(value: str) -> Decimal:
    return Decimal(value)


class _Loader:
    def __init__(
        self,
        uow: MemoryUnitOfWork,
        seed: Mapping[str, Any],
        now: datetime,
        account_hash: Callable[[str], str],
        retry_limit: int,
    ) -> None:
        self.uow = uow
        self.seed = seed
        self.app = seed["app"]
        self.now = now
        self.account_hash = account_hash
        self.retry_limit = retry_limit
        self.users: dict[str, User] = {}
        self.customers: dict[str, tuple[Customer, list[CustomerAccount]]] = {}
        self.proposal_seq = 0
        self.cert_seq = 0
        self.tran_seq = 0

    def audit(
        self,
        when: datetime,
        event_type: str,
        actor: User | None,
        e: Enrolment | None,
        detail: str | None = None,
    ) -> None:
        self.uow.audit.append(
            AuditEvent(
                event_time=when,
                event_type=event_type,
                outcome="SUCCESS",
                actor_user_id=actor.user_id if actor else None,
                actor_roll_no=actor.roll_no if actor else "SYSTEM",
                branch_code=e.branch_code if e else None,
                entity_type="ENROLMENT" if e else None,
                entity_id=e.enrolment_id if e else None,
                detail=detail,
            )
        )

    def reference_data(self) -> None:
        store, app = self.uow.store, self.app
        for b in app["branches"]:
            self.uow.users.upsert_branch(Branch(b["code"], b["name"]))
        for u in app["users"]:
            user = User(
                user_id=new_id(),
                roll_no=u["roll_no"],
                branch_code=u["branch_code"],
                display_name=u.get("display_name"),
                designation=u.get("designation"),
            )
            self.uow.users.save(user)
            store.user_roles[user.user_id] = frozenset(Role(r) for r in u["roles"])
            self.users[user.roll_no] = user
        for p in app["plans"]:
            store.plans[(app["product_code"], p["plan_code"])] = Plan(
                p["plan_code"], p["name"], app["product_code"]
            )
            r = p["rate"]
            rate = PlanRate(
                rate_id=new_id(),
                plan_code=p["plan_code"],
                effective_from=date.fromisoformat(r["effective_from"]),
                sum_insured=_d(r["sum_insured"]),
                net_premium=_d(r["net"]),
                gst_amount=_d(r["gst"]),
                gross_premium=_d(r["gross"]),
                policy_term_days=r["term_days"],
                synthetic=True,
                note=r["note"],
            )
            store.rates[rate.rate_id] = rate
        for category, items in app["ref_codes"].items():
            for order, (code, label) in enumerate(items, start=1):
                store.ref_codes.append(RefCode(category, code, label, order))
        for category, mapping in app["code_map"].items():
            for ours, theirs in mapping.items():
                store.code_map[(app["insurer_code"], category, ours)] = theirs
        store.settings.update(app["settings"])
        pool = app["pool_account"]
        store.pool_accounts.append(
            PoolAccount(
                new_id(), pool["account_no"], pool["label"], date.fromisoformat(pool["active_from"])
            )
        )

    def customer_for(self, account_no: str, when: datetime) -> tuple[Customer, CustomerAccount]:
        for c in self.seed["cbs_world"]["customers"]:
            if any(a["account_no"] == account_no for a in c["accounts"]):
                break
        else:
            raise KeyError("seed account not in cbs_world")
        if c["cif"] not in self.customers:
            customer = Customer(
                customer_id=new_id(),
                bank_customer_id=c["cif"],
                first_name=c["first_name"],
                middle_name=c.get("middle_name"),
                last_name=c["last_name"],
                gender_code=c.get("gender_code"),
                date_of_birth=date.fromisoformat(c["date_of_birth"]),
                mobile=c.get("mobile"),
                email=c.get("email"),
                address1=c.get("address1"),
                address2=c.get("address2"),
                city=c.get("city"),
                state_code=c.get("state_code"),
                pincode=c.get("pincode"),
                occupation_code=c.get("occupation_code"),
                kyc_status=c.get("kyc_status"),
                customer_status=c.get("customer_status"),
                home_branch_code=c.get("home_branch_code"),
                cbs_fetched_at=when,
            )
            accounts = [
                CustomerAccount(
                    customer_account_id=new_id(),
                    customer_id=customer.customer_id,
                    account_no=a["account_no"],
                    account_no_hash=self.account_hash(a["account_no"]),
                    holder_name=a.get("holder_name"),
                    account_type=a.get("account_type"),
                    account_status=a.get("status"),
                    joint_account=a.get("joint_account"),
                    cbs_branch_code=a.get("branch_code"),
                    cbs_fetched_at=when,
                )
                for a in c["accounts"]
            ]
            self.customers[c["cif"]] = self.uow.customers.upsert_snapshot(customer, accounts)
        customer, accounts = self.customers[c["cif"]]
        account = next(a for a in accounts if a.account_no == account_no)
        return customer, account

    def enrolment(self, spec: Mapping[str, Any]) -> None:
        app = self.app
        hours = 3 if spec["days_ago"] == 0 else 6
        t = self.now - timedelta(days=spec["days_ago"], hours=hours)
        step = timedelta(minutes=10)
        maker = self.users[spec["maker"]]
        checker = self.users.get(spec.get("checker", ""))
        customer, account = self.customer_for(spec["account"], t)
        cbs_fields = [
            f
            for f in (
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
            )
            if getattr(customer, f) is not None
        ]
        status_name = spec["status"]
        occupation = customer.occupation_code or (None if status_name == "DRAFT" else "SALARIED")
        insured = Insured(
            first_name=customer.first_name,
            middle_name=customer.middle_name,
            last_name=customer.last_name,
            gender_code=customer.gender_code,
            date_of_birth=customer.date_of_birth,
            mobile=customer.mobile,
            email=customer.email,
            address1=customer.address1,
            address2=customer.address2,
            city=customer.city,
            state_code=customer.state_code,
            pincode=customer.pincode,
            occupation_code=occupation,
            any_disability=False,
            cbs_sourced_fields=cbs_fields,
        )
        nominees = [
            Nominee(
                seq=i,
                name=n["name"],
                relation_code=n["relation_code"],
                share_percent=_d(n["share_percent"]),
                age=n.get("age"),
            )
            for i, n in enumerate(app["nominee_templates"][spec["nominees"]], start=1)
        ]
        rate = self.uow.reference.rate_in_force(spec["plan"], t.date())
        e = Enrolment(
            enrolment_id=new_id(),
            our_reference_no=self.uow.enrolments.next_reference_no(),
            status=S.DRAFT,
            status_changed_at=t,
            product_code=app["product_code"],
            customer_id=customer.customer_id,
            customer_account_id=account.customer_account_id,
            branch_code=spec["branch"],
            created_by=maker.user_id,
            created_at=t,
            updated_at=t,
            plan_code=spec["plan"],
            rate_id=rate.rate_id if rate else None,
            insured=insured,
            nominees=nominees,
        )
        self.audit(t, "ENROLMENT_CREATED", maker, e)
        path = list(_PATHS.get(status_name, []))
        if status_name == "NEEDS_ATTENTION":
            path = list(
                _PATHS["PAYMENT_PENDING" if spec["reason"] == "POSTING_UNKNOWN" else "PAID"]
            )
            path.append(S.NEEDS_ATTENTION)
        approvals: list[Approval] = []
        pool = self.uow.reference.active_pool_account(t.date())
        assert pool is not None  # noqa: S101 - seed invariant
        assert rate is not None  # noqa: S101 - seed invariant
        for target in path:
            t += step
            actor: User | None = maker
            reason: str | None = None
            if target == S.PENDING_CHECK:
                approvals.append(
                    Approval(
                        new_id(),
                        "ENROLMENT",
                        e.enrolment_id,
                        e.enrolment_id,
                        e.branch_code,
                        "SUBMIT_SALE",
                        maker.user_id,
                        "PENDING",
                        t,
                    )
                )
            elif target in (S.APPROVED, S.REJECTED) and checker is not None:
                actor = checker
                a = approvals[-1]
                a.status = "APPROVED" if target == S.APPROVED else "REJECTED"
                a.checker_user_id, a.decided_at = checker.user_id, t
                a.checker_comment = spec.get("checker_comment")
                reason = a.checker_comment
            elif target == S.PROPOSAL_CREATED:
                self.proposal_seq += 1
                figures = (
                    self.seed["fake_insurer"]["mismatch_premium_by_plan"][spec["plan"]]
                    if spec.get("mismatch")
                    else self.seed["fake_insurer"]["premium_by_plan"][spec["plan"]]
                )
                e.insurer_proposal_no = f"SYNP{self.proposal_seq:06d}"
                e.proposal_created_at = t
                e.net_premium, e.gst_amount = _d(figures["net"]), _d(figures["gst"])
                e.gross_premium = _d(figures["gross"])
                e.premium_matches_rate = (
                    e.net_premium == rate.net_premium
                    and e.gst_amount == rate.gst_amount
                    and e.gross_premium == rate.gross_premium
                )
                self.call(e, "create_proposal", "SUCCESS", t)
            elif target == S.PROPOSAL_REJECTED:
                e.insurer_message = spec.get("insurer_message")
                self.call(e, "create_proposal", "REJECTED", t, "VALIDATION")
                actor, reason = None, e.insurer_message
            elif target == S.PROPOSAL_CANCELLED:
                self.call(e, "cancel_proposal", "SUCCESS", t)
                reason = "Synthetic: customer withdrew"
            elif target == S.PAYMENT_PENDING:
                e.consent_method, e.consent_ref, e.consent_at = "SIGNED_FORM", "SYN-CONSENT-1", t
                e.consent_used = True
                e.postings.append(
                    Posting(
                        new_id(),
                        "PREMIUM",
                        e.gross_premium or Decimal("0"),
                        account.customer_account_id,
                        pool.pool_account_id,
                        f"{e.our_reference_no}-P1",
                        "PENDING",
                        1,
                        t,
                        created_by=maker.user_id,
                    )
                )
            elif target == S.PAYMENT_FAILED:
                p = e.postings[-1]
                p.status, p.completed_at = "FAILED", t
                p.error_code, p.error_text = "DECLINED", spec.get("posting_reason")
                actor, reason = None, "CBS declined"
            elif target == S.PAID:
                self.tran_seq += 1
                p = e.postings[-1]
                p.status, p.completed_at = "SUCCESS", t
                p.cbs_tran_id, p.cbs_tran_at = f"SYNTXN{self.tran_seq:06d}", t
                actor = None
            elif target == S.ISSUED:
                self.cert_seq += 1
                e.certificate_no = f"SYN/GPA/{self.cert_seq:06d}"
                e.risk_start_date = t.date()
                e.risk_end_date = t.date() + timedelta(days=rate.policy_term_days - 1)
                e.issued_at = t
                self.call(e, "issue_policy", "SUCCESS", t)
                self.call(e, "fetch_certificate", "SUCCESS", t)
                self.document(e, t)
                actor = None
            elif target == S.NEEDS_ATTENTION:
                actor = None
                if spec["reason"] == "POSTING_UNKNOWN":
                    e.postings[-1].status = "UNKNOWN"
                    reason = "CBS outcome unknown and not resolvable"
                else:
                    for _ in range(1 + self.retry_limit):
                        self.call(e, "issue_policy", "ERROR", t, "UNAVAILABLE")
                    reason = "Policy not issued after the retry limit"
                e.attention_reason, e.attention_since = spec["reason"], t
            elif target == S.CANCELLATION_PENDING:
                cancel_approval = Approval(
                    new_id(),
                    "CANCELLATION",
                    new_id(),
                    e.enrolment_id,
                    e.branch_code,
                    "CANCEL_CERTIFICATE",
                    maker.user_id,
                    "APPROVED",
                    t - step,
                    checker_user_id=checker.user_id if checker else None,
                    decided_at=t,
                )
                approvals.append(cancel_approval)
                e.cancellation = Cancellation(
                    cancel_approval.entity_id,
                    spec["cancel_reason"],
                    "SUBMITTED",
                    maker.user_id,
                    t - step,
                    approval_id=cancel_approval.approval_id,
                )
                e.cancel_reason_code = spec["cancel_reason"]
                actor = checker
            elif target == S.CANCELLED:
                assert e.cancellation is not None  # noqa: S101 - seed invariant
                self.call(e, "cancel_certificate", "SUCCESS", t)
                self.tran_seq += 1
                refund = Posting(
                    new_id(),
                    "REFUND",
                    e.gross_premium or Decimal("0"),
                    account.customer_account_id,
                    pool.pool_account_id,
                    f"{e.our_reference_no}-R1",
                    "SUCCESS",
                    1,
                    t,
                    cbs_tran_id=f"SYNTXN{self.tran_seq:06d}",
                    cbs_tran_at=t,
                    completed_at=t,
                )
                e.postings.append(refund)
                c = e.cancellation
                c.status, c.refund_amount, c.refund_at = "COMPLETED", refund.amount, t
                c.refund_posting_id, c.completed_at = refund.posting_id, t
                e.cancelled_at = t
                actor = None
            e.transition(target, t, actor_user_id=actor.user_id if actor else None, reason=reason)
            self.audit(t, "STATUS_CHANGED", actor, e, f"to={target.value}")
        if status_name == "PAID":
            self.call(e, "issue_policy", "ERROR", t, "UNAVAILABLE")
            self.uow.jobs.enqueue(
                Job(
                    new_id(),
                    "ISSUE_POLICY",
                    e.enrolment_id,
                    f"ISSUE_POLICY:{e.enrolment_id}",
                    "QUEUED",
                    self.now + timedelta(minutes=spec.get("retry_job_minutes", 2)),
                    0,
                    self.retry_limit,
                    t,
                )
            )
        if spec.get("pending_cancellation"):
            t += step
            cancellation_id = new_id()
            approval = Approval(
                new_id(),
                "CANCELLATION",
                cancellation_id,
                e.enrolment_id,
                e.branch_code,
                "CANCEL_CERTIFICATE",
                maker.user_id,
                "PENDING",
                t,
                maker_comment="Synthetic: customer asked to cancel",
            )
            approvals.append(approval)
            e.cancellation = Cancellation(
                cancellation_id,
                spec["cancel_reason"],
                "PENDING_CHECK",
                maker.user_id,
                t,
                approval_id=approval.approval_id,
            )
        for a in approvals:
            self.uow.approvals.add(a)
        e.updated_at = t
        self.uow.enrolments.add(e)

    def call(
        self, e: Enrolment, operation: str, status: str, when: datetime, category: str | None = None
    ) -> None:
        e.insurer_calls.append(
            InsurerCall(
                new_id(),
                operation,
                e.next_attempt(operation),
                status,
                when,
                our_reference=e.our_reference_no,
                error_category=category,
                finished_at=when,
                duration_ms=300,
            )
        )

    def document(self, e: Enrolment, when: datetime) -> None:
        content = specimen_pdf(
            "Certificate of Insurance - Group Personal Accident",
            [
                f"Certificate number: {e.certificate_no}",
                f"Proposal number: {e.insurer_proposal_no}",
                f"Insured: {e.insured.full_name.upper()}",
                f"Plan: {e.plan_code}",
                f"Gross premium (INR): {e.gross_premium}",
                f"Risk period: {e.risk_start_date} to {e.risk_end_date}",
                "Seeded by the demo backend. No cover exists.",
            ],
        )
        self.uow.documents.add(
            Document(
                document_id=new_id(),
                enrolment_id=e.enrolment_id,
                kind="COI",
                file_name=f"COI-{(e.certificate_no or '').replace('/', '-')}.pdf",
                content_type="application/pdf",
                size_bytes=len(content),
                sha256=hashlib.sha256(content).hexdigest(),
                content=content,
                source="INSURER",
                created_at=when,
            )
        )


def load_seed(
    store: MemoryStore,
    seed: Mapping[str, Any],
    *,
    now: datetime,
    account_hash: Callable[[str], str],
    retry_limit: int,
) -> None:
    """Populate an empty store from the seed. Raises on any inconsistency (fails loudly)."""
    with MemoryUnitOfWork(store) as uow:
        loader = _Loader(uow, seed, now, account_hash, retry_limit)
        loader.reference_data()
        for spec in seed["app"]["enrolments"]:
            loader.enrolment(spec)
        uow.commit()


def seeded_user_ids(store: MemoryStore) -> dict[str, UUID]:
    """Roll number -> user id (used by tests and the bootstrap)."""
    return {u.roll_no: u.user_id for u in store.table("app_user").values()}

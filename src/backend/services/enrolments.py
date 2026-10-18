"""Reference data, CBS lookup and the draft part of the sale (lookup -> draft -> submit).

Validation here is format and completeness only (required fields, codes, nominee shares total
100). Eligibility and nominee rules are insurance rules from a domain expert and are not invented.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from backend.adapters.cbs.customer_directory.base import (
    CbsAccountRecord,
    CbsCustomerRecord,
    CbsNotFound,
    CbsUnavailable,
    CustomerLookup,
)
from backend.domain.model import (
    INSURED_FIELDS,
    INSURED_REQUIRED_ON_SUBMIT,
    Approval,
    Customer,
    CustomerAccount,
    Document,
    Enrolment,
    Insured,
    Nominee,
    Plan,
    PlanRate,
    RefCode,
    Role,
    StatusChange,
    new_id,
)
from backend.domain.repositories import EnrolmentQuery, Page, UnitOfWork
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
    mask,
    not_found,
)
from backend.services.views import (
    EnrolmentBundle,
    check_version,
    enrolment_bundle,
    load_enrolment,
)

_CBS_INSURED = (
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
_INSURED_CODES = {"gender_code": "GENDER", "state_code": "STATE", "occupation_code": "OCCUPATION"}
_NOMINEE_CODES = {
    "relation_code": "RELATION",
    "gender_code": "GENDER",
    "appointee_relation_code": "RELATION",
    "appointee_gender_code": "GENDER",
}


@dataclass
class LookupAccount:
    account_key: str
    record: CbsAccountRecord
    selectable: bool


@dataclass
class LookupView:
    customer: CbsCustomerRecord
    accounts: list[LookupAccount]
    fetched_at: datetime


@dataclass
class DraftChanges:
    version: int
    debit_account_key: str | None = None
    plan_code: str | None = None
    insured: dict[str, Any] | None = None  # only the fields present in the request
    nominees: list[Nominee] | None = None
    fields_set: set[str] = field(default_factory=set)


def _masked_identifier(account_no: str | None, cif: str | None) -> str:
    return f"{'account' if account_no else 'cif'}:{mask(account_no or cif or '')}"


class EnrolmentService:
    def __init__(self, deps: Deps) -> None:
        self.d = deps

    # ---------------------------------------------------------------- reference
    def ref_codes(self) -> list[RefCode]:
        with self.d.uow() as uow:
            return uow.reference.codes()

    def plans(self) -> list[tuple[Plan, PlanRate | None]]:
        today = self.d.clock.now().date()
        with self.d.uow() as uow:
            plans = uow.reference.list_plans(self.d.config.product_code)
            return [(p, uow.reference.rate_in_force(p.plan_code, today)) for p in plans]

    # ---------------------------------------------------------------- CBS lookup
    def _read_cbs(self, actor: Actor, account_no: str | None, cif: str | None) -> CustomerLookup:
        identifier = _masked_identifier(account_no, cif)
        try:
            found = self.d.directory.find_customer(account_no=account_no, cif=cif)
            outcome = "SUCCESS"
        except CbsNotFound:
            found, outcome = None, "NOT_FOUND"
        except CbsUnavailable:
            found, outcome = None, "UNAVAILABLE"
        with self.d.uow() as uow:
            audit(uow, actor, "CUSTOMER_LOOKUP", outcome=outcome, detail=identifier)
            uow.commit()
        if outcome == "NOT_FOUND":
            raise ServiceError(404, "CUSTOMER_NOT_FOUND")
        if found is None:
            raise ServiceError(503, "CBS_UNAVAILABLE")
        return found

    def _selectable(self, record: CbsAccountRecord) -> bool:
        return (record.status or "").upper() in self.d.config.selectable_statuses

    def lookup(self, actor: Actor, account_no: str | None, cif: str | None) -> LookupView:
        found = self._read_cbs(actor, account_no, cif)
        if not found.accounts:
            raise ServiceError(404, "CUSTOMER_NOT_FOUND")
        accounts = [
            LookupAccount(self.d.keys.account_key(a.account_no), a, self._selectable(a))
            for a in found.accounts
        ]
        return LookupView(found.customer, accounts, self.d.clock.now())

    def _snapshot(
        self, uow: UnitOfWork, found: CustomerLookup, now: datetime
    ) -> tuple[Customer, list[CustomerAccount]]:
        c = found.customer
        customer = Customer(
            customer_id=new_id(),
            bank_customer_id=c.cif,
            first_name=c.first_name,
            middle_name=c.middle_name,
            last_name=c.last_name,
            gender_code=c.gender_code,
            date_of_birth=c.date_of_birth,
            mobile=c.mobile,
            email=c.email,
            address1=c.address1,
            address2=c.address2,
            city=c.city,
            state_code=c.state_code,
            pincode=c.pincode,
            occupation_code=c.occupation_code,
            kyc_status=c.kyc_status,
            customer_status=c.customer_status,
            home_branch_code=c.home_branch_code,
            cbs_fetched_at=now,
        )
        accounts = [
            CustomerAccount(
                customer_account_id=new_id(),
                customer_id=customer.customer_id,
                account_no=a.account_no,
                account_no_hash=self.d.keys.account_key(a.account_no),
                holder_name=a.holder_name,
                account_type=a.account_type,
                account_status=a.status,
                joint_account=a.joint_account,
                cbs_branch_code=a.branch_code,
                cbs_fetched_at=now,
            )
            for a in found.accounts
        ]
        return uow.customers.upsert_snapshot(customer, accounts)

    def _pick_account(
        self, accounts: list[CustomerAccount], key: str, path: str
    ) -> CustomerAccount:
        chosen = next((a for a in accounts if a.account_no_hash == key), None)
        if chosen is None:
            raise ServiceError(
                422, "VALIDATION_FAILED", [field_error(path, "ACCOUNT_NOT_OF_CUSTOMER")]
            )
        if (chosen.account_status or "").upper() not in self.d.config.selectable_statuses:
            raise ServiceError(
                422, "VALIDATION_FAILED", [field_error(path, "ACCOUNT_NOT_SELECTABLE")]
            )
        return chosen

    def _check_plan(self, uow: UnitOfWork, plan_code: str | None, path: str = "plan_code") -> None:
        if (
            plan_code is not None
            and uow.reference.get_plan(self.d.config.product_code, plan_code) is None
        ):
            raise ServiceError(422, "VALIDATION_FAILED", [field_error(path, "INVALID_CODE")])

    # ---------------------------------------------------------------- drafts
    def _new_draft(
        self,
        uow: UnitOfWork,
        actor: Actor,
        customer: Customer,
        account: CustomerAccount | None,
        plan_code: str | None,
        now: datetime,
    ) -> Enrolment:
        sourced = [f for f in _CBS_INSURED if getattr(customer, f) is not None]
        insured = Insured(**{f: getattr(customer, f) for f in _CBS_INSURED})
        insured.cbs_sourced_fields = sourced
        assert actor.user_id is not None  # noqa: S101
        assert actor.branch_code is not None  # noqa: S101
        e = Enrolment(
            enrolment_id=new_id(),
            our_reference_no=uow.enrolments.next_reference_no(),
            status=S.DRAFT,
            status_changed_at=now,
            product_code=self.d.config.product_code,
            customer_id=customer.customer_id,
            customer_account_id=account.customer_account_id if account else None,
            branch_code=actor.branch_code,  # the session's branch, never the client's
            created_by=actor.user_id,
            created_at=now,
            updated_at=now,
            plan_code=plan_code,
            insured=insured,
        )
        e.history.append(_creation_history(now, actor))
        return e

    def create_draft(
        self,
        actor: Actor,
        account_no: str | None,
        cif: str | None,
        debit_account_key: str,
        plan_code: str | None,
    ) -> UUID:
        found = self._read_cbs(actor, account_no, cif)  # fresh read; nothing saved if it fails
        now = self.d.clock.now()
        with self.d.uow() as uow:
            self._check_plan(uow, plan_code)
            customer, accounts = self._snapshot(uow, found, now)
            account = self._pick_account(accounts, debit_account_key, "debit_account_key")
            e = self._new_draft(uow, actor, customer, account, plan_code, now)
            uow.enrolments.add(e)
            audit(uow, actor, "ENROLMENT_CREATED", enrolment=e, when=now, detail="to=DRAFT")
            uow.commit()
        return e.enrolment_id

    def copy_rejected(self, actor: Actor, enrolment_id: UUID) -> UUID:
        with self.d.uow() as uow:
            original = load_enrolment(uow, actor, enrolment_id)
            if original.status != S.REJECTED:
                raise invalid_state()
            customer = uow.customers.get(original.customer_id)
            old_account = (
                uow.customers.get_account(original.customer_account_id)
                if original.customer_account_id
                else None
            )
        if customer is None:
            raise not_found()
        found = self._read_cbs(actor, None, customer.bank_customer_id)
        now = self.d.clock.now()
        with self.d.uow() as uow:
            customer, accounts = self._snapshot(uow, found, now)
            # Keep the same debit account when the CBS still lists it (re-read before posting
            # anyway); otherwise the first selectable one, for the maker to confirm.
            selectable = [
                a
                for a in accounts
                if (a.account_status or "").upper() in self.d.config.selectable_statuses
            ]
            account = next(
                (
                    a
                    for a in accounts
                    if old_account is not None and a.account_no_hash == old_account.account_no_hash
                ),
                selectable[0] if selectable else (accounts[0] if accounts else None),
            )
            e = self._new_draft(uow, actor, customer, account, original.plan_code, now)
            for name in INSURED_FIELDS:
                if name not in e.insured.cbs_sourced_fields:
                    setattr(e.insured, name, getattr(original.insured, name))
            e.nominees = list(original.nominees)
            uow.enrolments.add(e)
            audit(
                uow,
                actor,
                "ENROLMENT_COPIED",
                enrolment=e,
                when=now,
                detail=f"from={original.our_reference_no}",
            )
            uow.commit()
        return e.enrolment_id

    def update_draft(self, actor: Actor, enrolment_id: UUID, changes: DraftChanges) -> None:
        now = self.d.clock.now()
        with self.d.uow() as uow:
            e = load_enrolment(uow, actor, enrolment_id)
            _require_branch_user(actor, e)
            if e.status != S.DRAFT:
                raise invalid_state()
            check_version(e, changes.version)
            errors: list[dict[str, str]] = []
            if "debit_account_key" in changes.fields_set and changes.debit_account_key:
                accounts = uow.customers.accounts_for(e.customer_id)
                e.customer_account_id = self._pick_account(
                    accounts, changes.debit_account_key, "debit_account_key"
                ).customer_account_id
            if "plan_code" in changes.fields_set:
                self._check_plan(uow, changes.plan_code)
                e.plan_code = changes.plan_code
            if changes.insured is not None:
                errors += self._apply_insured(uow, e, changes.insured)
            if changes.nominees is not None:
                errors += self._check_nominee_codes(uow, changes.nominees)
                e.nominees = changes.nominees
            if errors:
                raise ServiceError(422, "VALIDATION_FAILED", errors)
            e.updated_at = now
            uow.enrolments.save(e)
            audit(
                uow,
                actor,
                "ENROLMENT_UPDATED",
                enrolment=e,
                when=now,
                detail="sections=" + ",".join(sorted(changes.fields_set - {"version"})),
            )
            uow.commit()

    def _apply_insured(
        self, uow: UnitOfWork, e: Enrolment, values: dict[str, Any]
    ) -> list[dict[str, str]]:
        errors = []
        sourced = set(e.insured.cbs_sourced_fields)
        for name in INSURED_FIELDS:
            if name in sourced:
                if name in values and values[name] != getattr(e.insured, name):
                    errors.append(field_error(f"insured.{name}", "CBS_SOURCED_READ_ONLY"))
                continue
            setattr(e.insured, name, values.get(name))  # the section replaces what is not CBS
        for name, category in _INSURED_CODES.items():
            code = values.get(name)
            if name not in sourced and code is not None and not _is_code(uow, category, code):
                errors.append(field_error(f"insured.{name}", "INVALID_CODE"))
        return errors

    def _check_nominee_codes(
        self, uow: UnitOfWork, nominees: list[Nominee]
    ) -> list[dict[str, str]]:
        errors = []
        for i, n in enumerate(nominees):
            for name, category in _NOMINEE_CODES.items():
                code = getattr(n, name)
                if code is not None and not _is_code(uow, category, code):
                    errors.append(field_error(f"nominees[{i}].{name}", "INVALID_CODE"))
        return errors

    def submit(
        self, actor: Actor, enrolment_id: UUID, version: int, comment: str | None
    ) -> ActionResult:
        now = self.d.clock.now()
        with self.d.uow() as uow:
            e = load_enrolment(uow, actor, enrolment_id)
            _require_branch_user(actor, e)
            if e.status != S.DRAFT:
                raise invalid_state()
            check_version(e, version)
            errors = self._completeness(uow, e)
            if errors:
                raise ServiceError(422, "VALIDATION_FAILED", errors)
            rate = uow.reference.rate_in_force(e.plan_code or "", now.date())
            e.rate_id = rate.rate_id if rate else None
            checker_needed = (uow.reference.setting("maker_checker.enrolment") or "true") == "true"
            assert actor.user_id is not None  # noqa: S101
            if checker_needed:
                e.transition(
                    S.PENDING_CHECK,
                    now,
                    actor_user_id=actor.user_id,
                    reason=comment,
                    correlation_id=actor.correlation_id,
                )
                uow.approvals.add(
                    Approval(
                        new_id(),
                        "ENROLMENT",
                        e.enrolment_id,
                        e.enrolment_id,
                        e.branch_code,
                        "SUBMIT_SALE",
                        actor.user_id,
                        "PENDING",
                        now,
                        maker_comment=comment,
                    )
                )
                outcome = ActionOutcome("PENDING_APPROVAL")
            else:
                e.transition(
                    S.APPROVED,
                    now,
                    actor_user_id=actor.user_id,
                    reason=comment,
                    correlation_id=actor.correlation_id,
                )
                outcome = ActionOutcome("DONE")
            uow.enrolments.save(e)
            audit(
                uow, actor, "STATUS_CHANGED", enrolment=e, when=now, detail=f"to={e.status.value}"
            )
            uow.commit()
        return ActionResult(e.enrolment_id, outcome)

    def _completeness(self, uow: UnitOfWork, e: Enrolment) -> list[dict[str, str]]:
        errors = []
        for name in INSURED_REQUIRED_ON_SUBMIT:
            if getattr(e.insured, name) is None:
                errors.append(field_error(f"insured.{name}", "REQUIRED"))
        for name, category in _INSURED_CODES.items():
            code = getattr(e.insured, name)
            if code is not None and not _is_code(uow, category, code):
                errors.append(field_error(f"insured.{name}", "INVALID_CODE"))
        if e.plan_code is None:
            errors.append(field_error("plan_code", "REQUIRED"))
        elif uow.reference.get_plan(e.product_code, e.plan_code) is None:
            errors.append(field_error("plan_code", "INVALID_CODE"))
        elif uow.reference.rate_in_force(e.plan_code, self.d.clock.now().date()) is None:
            errors.append(field_error("plan_code", "NOT_ALLOWED", "No plan rate in force"))
        if e.customer_account_id is None:
            errors.append(field_error("debit_account_key", "REQUIRED"))
        total = sum((n.share_percent for n in e.nominees), Decimal("0"))
        if total != Decimal("100"):
            errors.append(field_error("nominees", "SHARES_NOT_100"))
        errors += self._check_nominee_codes(uow, e.nominees)
        return errors

    def reopen(self, actor: Actor, enrolment_id: UUID, version: int) -> ActionResult:
        now = self.d.clock.now()
        with self.d.uow() as uow:
            e = load_enrolment(uow, actor, enrolment_id)
            _require_branch_user(actor, e)
            if e.status != S.PROPOSAL_REJECTED:
                raise invalid_state()
            check_version(e, version)
            e.transition(
                S.DRAFT,
                now,
                actor_user_id=actor.user_id,
                reason="Reopened to correct",
                correlation_id=actor.correlation_id,
            )
            uow.enrolments.save(e)
            audit(uow, actor, "STATUS_CHANGED", enrolment=e, when=now, detail="to=DRAFT")
            uow.commit()
        return ActionResult(e.enrolment_id, ActionOutcome())

    # ---------------------------------------------------------------- reads
    def detail(self, actor: Actor, enrolment_id: UUID) -> EnrolmentBundle:
        with self.d.uow() as uow:
            return enrolment_bundle(uow, actor, load_enrolment(uow, actor, enrolment_id))

    def search(
        self, actor: Actor, query: EnrolmentQuery, branch_code: str | None, mine: bool
    ) -> tuple[Page[Enrolment], dict[UUID, Any]]:
        scope = actor.scope()
        if scope is None and branch_code:
            scope = frozenset({branch_code})  # honoured only for cross-branch roles
        query.branch_codes = scope
        if mine:
            query.created_by = actor.user_id
        with self.d.uow() as uow:
            page = uow.enrolments.search(query)
            makers = {e.created_by: uow.users.get(e.created_by) for e in page.items}
        return page, makers

    def certificate(self, actor: Actor, enrolment_id: UUID) -> Document:
        with self.d.uow() as uow:
            e = load_enrolment(uow, actor, enrolment_id)
            doc = uow.documents.latest(e.enrolment_id, "COI")
            if doc is None:
                raise not_found()
            intact = hashlib.sha256(doc.content).hexdigest() == doc.sha256
            audit(
                uow,
                actor,
                "CERTIFICATE_DOWNLOADED",
                enrolment=e,
                outcome="SUCCESS" if intact else "FAILURE",
                detail=f"document={doc.document_id}",
            )
            uow.commit()
        if not intact:
            raise ServiceError(500, "INTERNAL")
        return doc


def _creation_history(now: datetime, actor: Actor) -> StatusChange:
    return StatusChange(new_id(), None, S.DRAFT, now, None, actor.user_id, actor.correlation_id)


def _is_code(uow: UnitOfWork, category: str, code: str) -> bool:
    return any(c.code == code for c in uow.reference.codes(category))


def _require_branch_user(actor: Actor, e: Enrolment) -> None:
    if not actor.has(Role.BRANCH_USER) or actor.branch_code != e.branch_code:
        raise ServiceError(403, "FORBIDDEN")

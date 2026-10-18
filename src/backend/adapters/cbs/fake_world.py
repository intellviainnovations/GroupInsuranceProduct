"""Synthetic CBS world shared by the fake customer directory and the fake posting gateway.

Behaviour is scripted by the last four digits of the account number (docs/design/repositories.md
section 6). Everything here is invented; no real customer, account or transaction exists.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from backend.adapters.cbs.customer_directory.base import (
    CbsAccountRecord,
    CbsBranchRecord,
    CbsCustomerRecord,
    CbsNotFound,
    CbsUnavailable,
    CustomerLookup,
)
from backend.adapters.cbs.posting.base import PostingResult


def _optional_date(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


@dataclass
class _PostingRecord:
    status: str
    tran_id: str | None
    tran_at: datetime | None
    amount: Decimal


@dataclass
class FakeCbsWorld:
    customers: dict[str, CbsCustomerRecord]
    accounts: dict[str, tuple[str, CbsAccountRecord]]  # account_no -> (cif, record)
    branches: dict[str, CbsBranchRecord]
    unavailable_ids: frozenset[str]
    slow_ids: frozenset[str]
    frozen_on_reread_suffix: str
    timeout_seconds: float
    delay_seconds: float = 0.0
    sleep: Callable[[float], None] = time.sleep
    clock: Callable[[], datetime] = lambda: datetime.now(UTC)
    postings: dict[str, _PostingRecord] = field(default_factory=dict)
    tran_seq: int = 0
    lock: threading.Lock = field(default_factory=threading.Lock)

    @classmethod
    def from_seed(
        cls,
        world: Mapping[str, Any],
        *,
        timeout_seconds: float,
        delay_seconds: float = 0.0,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], datetime] | None = None,
    ) -> FakeCbsWorld:
        customers: dict[str, CbsCustomerRecord] = {}
        accounts: dict[str, tuple[str, CbsAccountRecord]] = {}
        for c in world["customers"]:
            customers[c["cif"]] = CbsCustomerRecord(
                cif=c["cif"],
                first_name=c["first_name"],
                middle_name=c.get("middle_name"),
                last_name=c["last_name"],
                gender_code=c.get("gender_code"),
                date_of_birth=_optional_date(c.get("date_of_birth")),
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
            )
            for a in c["accounts"]:
                accounts[a["account_no"]] = (
                    c["cif"],
                    CbsAccountRecord(
                        account_no=a["account_no"],
                        status=a.get("status"),
                        account_type=a.get("account_type"),
                        branch_code=a.get("branch_code"),
                        joint_account=a.get("joint_account"),
                        holder_name=a.get("holder_name"),
                    ),
                )
        branches = {
            b["code"]: CbsBranchRecord(code=b["code"], name=b.get("name"), ifsc=b.get("ifsc"))
            for b in world["branches"]
        }
        return cls(
            customers=customers,
            accounts=accounts,
            branches=branches,
            unavailable_ids=frozenset(world["unavailable_ids"]),
            slow_ids=frozenset(world["slow_ids"]),
            frozen_on_reread_suffix=world["frozen_on_reread_suffix"],
            timeout_seconds=timeout_seconds,
            delay_seconds=delay_seconds,
            sleep=sleep,
            clock=clock or (lambda: datetime.now(UTC)),
        )

    def wait(self) -> None:
        if self.delay_seconds:
            self.sleep(self.delay_seconds)

    def guard(self, identifier: str) -> None:
        """Scripted unavailability; a slow reply waits out the configured timeout, then fails."""
        if identifier in self.unavailable_ids:
            raise CbsUnavailable
        if identifier in self.slow_ids:
            self.sleep(self.timeout_seconds)
            raise CbsUnavailable

    def prime_posting(
        self, ref: str, status: str, tran_id: str | None, tran_at: datetime | None, amount: Decimal
    ) -> None:
        with self.lock:
            self.postings[ref] = _PostingRecord(status, tran_id, tran_at, amount)
            if tran_id and tran_id[-6:].isdigit():
                self.tran_seq = max(self.tran_seq, int(tran_id[-6:]))

    def next_tran_id(self) -> str:
        with self.lock:
            self.tran_seq += 1
            return f"SYNTXN{self.tran_seq:06d}"


class FakeCustomerDirectory:
    def __init__(self, world: FakeCbsWorld) -> None:
        self._world = world

    def find_customer(
        self, *, account_no: str | None = None, cif: str | None = None
    ) -> CustomerLookup:
        world = self._world
        identifier = account_no if account_no is not None else (cif or "")
        world.guard(identifier)
        world.wait()
        if account_no is not None:
            if account_no.endswith("0000") or account_no not in world.accounts:
                raise CbsNotFound
            cif = world.accounts[account_no][0]
        customer = world.customers.get(cif or "")
        if customer is None:
            raise CbsNotFound
        accounts = [rec for owner, rec in world.accounts.values() if owner == customer.cif]
        return CustomerLookup(customer=customer, accounts=accounts)

    def get_account(self, account_no: str) -> CbsAccountRecord:
        world = self._world
        world.guard(account_no)
        world.wait()
        entry = world.accounts.get(account_no)
        if entry is None:
            raise CbsNotFound
        record = entry[1]
        if account_no.endswith(world.frozen_on_reread_suffix):
            return CbsAccountRecord(
                account_no=record.account_no,
                status="FROZEN",
                account_type=record.account_type,
                branch_code=record.branch_code,
                joint_account=record.joint_account,
                holder_name=record.holder_name,
            )
        return record

    def get_branch(self, code: str) -> CbsBranchRecord:
        branch = self._world.branches.get(code)
        if branch is None:
            raise CbsNotFound
        return branch


class FakePostingGateway:
    """``...7001`` declined, ``...7002`` unknown then SUCCESS on read, ``...7003`` unknown twice."""

    def __init__(self, world: FakeCbsWorld) -> None:
        self._world = world

    def _post(self, ref: str, account_no: str, amount: Decimal) -> PostingResult:
        world = self._world
        world.wait()
        with world.lock:
            existing = world.postings.get(ref)
        if existing is not None:  # same reference never posts twice
            if existing.status == "SUCCESS":
                return PostingResult("SUCCESS", existing.tran_id, existing.tran_at)
            return PostingResult(existing.status if existing.status != "UNCLEAR" else "UNKNOWN")
        suffix = account_no[-4:]
        if suffix == "7001":
            world.prime_posting(ref, "FAILED", None, None, amount)
            return PostingResult("FAILED", reason="Synthetic decline: insufficient funds")
        tran_id, tran_at = world.next_tran_id(), world.clock()
        if suffix == "7002":
            world.prime_posting(ref, "SUCCESS", tran_id, tran_at, amount)
            return PostingResult("UNKNOWN")
        if suffix == "7003":
            world.prime_posting(ref, "UNCLEAR", None, None, amount)
            return PostingResult("UNKNOWN")
        world.prime_posting(ref, "SUCCESS", tran_id, tran_at, amount)
        return PostingResult("SUCCESS", tran_id, tran_at)

    def post_premium(
        self,
        cbs_request_ref: str,
        customer_account_no: str,
        pool_account_no: str,
        amount: Decimal,
        narration: str,
    ) -> PostingResult:
        return self._post(cbs_request_ref, customer_account_no, amount)

    def post_refund(
        self,
        cbs_request_ref: str,
        customer_account_no: str,
        pool_account_no: str,
        amount: Decimal,
        narration: str,
        original_request_ref: str | None,
    ) -> PostingResult:
        world = self._world
        world.wait()
        tran_id, tran_at = world.next_tran_id(), world.clock()
        world.prime_posting(cbs_request_ref, "SUCCESS", tran_id, tran_at, amount)
        return PostingResult("SUCCESS", tran_id, tran_at)

    def get_posting_status(self, cbs_request_ref: str) -> PostingResult:
        world = self._world
        world.wait()
        with world.lock:
            record = world.postings.get(cbs_request_ref)
        if record is None:
            return PostingResult("NOT_FOUND")
        if record.status == "UNCLEAR":
            return PostingResult("UNKNOWN")
        return PostingResult(record.status, record.tran_id, record.tran_at)

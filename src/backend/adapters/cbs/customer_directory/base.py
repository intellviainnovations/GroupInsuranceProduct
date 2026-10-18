"""CBS customer directory port (read-only; docs/contracts/cbs-customer-lookup.md)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Protocol


class CbsNotFound(Exception):
    """No customer or account for the identifier."""


class CbsUnavailable(Exception):
    """The report server is unavailable or too slow (the call hit its timeout)."""


@dataclass(frozen=True)
class CbsCustomerRecord:
    cif: str
    first_name: str
    last_name: str
    middle_name: str | None = None
    gender_code: str | None = None
    date_of_birth: date | None = None
    mobile: str | None = None
    email: str | None = None
    address1: str | None = None
    address2: str | None = None
    city: str | None = None
    state_code: str | None = None
    pincode: str | None = None
    occupation_code: str | None = None
    kyc_status: str | None = None
    customer_status: str | None = None
    home_branch_code: str | None = None


@dataclass(frozen=True)
class CbsAccountRecord:
    account_no: str
    status: str | None
    account_type: str | None = None
    branch_code: str | None = None
    joint_account: bool | None = None
    currency: str | None = "INR"
    holder_name: str | None = None


@dataclass(frozen=True)
class CustomerLookup:
    customer: CbsCustomerRecord
    accounts: list[CbsAccountRecord]


@dataclass(frozen=True)
class CbsBranchRecord:
    code: str
    name: str | None = None
    region: str | None = None
    ifsc: str | None = None


class CustomerDirectory(Protocol):
    def find_customer(
        self, *, account_no: str | None = None, cif: str | None = None
    ) -> CustomerLookup: ...

    def get_account(self, account_no: str) -> CbsAccountRecord: ...

    def get_branch(self, code: str) -> CbsBranchRecord: ...


class UnconfiguredDirectory:
    """Default outside dev/demo until the real adapter exists (Q33): fails closed."""

    def find_customer(
        self, *, account_no: str | None = None, cif: str | None = None
    ) -> CustomerLookup:
        raise CbsUnavailable

    def get_account(self, account_no: str) -> CbsAccountRecord:
        raise CbsUnavailable

    def get_branch(self, code: str) -> CbsBranchRecord:
        raise CbsUnavailable

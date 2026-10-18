"""Scriptable fake insurer (dev, demo and tests). Synthetic data only.

Behaviour is selected by the last four digits of the debit account sent in ``create_proposal``
(docs/design/repositories.md section 6). Premium figures come from the seed's fake-insurer table:
this fake plays the insurer, the application still never calculates premium.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from backend.adapters.insurer.base import (
    CancellationResult,
    Certificate,
    ErrorCategory,
    IssueRequest,
    Outcome,
    PolicyIssued,
    ProposalCreated,
    ProposalRecord,
    ProposalRequest,
    Rejected,
    Success,
    TransientError,
    UnknownOutcome,
)
from backend.platform.pdf import specimen_pdf


@dataclass
class _Proposal:
    our_reference: str
    proposal_no: str
    suffix: str
    plan_code: str
    insured_name: str
    net: Decimal
    gst: Decimal
    gross: Decimal
    term_days: int
    status: str = "PROPOSAL"
    payment_status: str | None = None
    certificate_no: str | None = None
    risk_start: date | None = None
    risk_end: date | None = None
    cancelled: bool = False


class FakeInsurer:
    insurer_code = "USGIC"

    def __init__(
        self,
        config: Mapping[str, Any],
        *,
        delay_seconds: float = 0.0,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._premiums = config["premium_by_plan"]
        self._mismatch = config["mismatch_premium_by_plan"]
        self._terms: dict[str, int] = config["term_days_by_plan"]
        self._delay = delay_seconds
        self._sleep = sleep
        self._clock = clock or (lambda: datetime.now(UTC))
        self._lock = threading.Lock()
        self._by_ref: dict[str, _Proposal] = {}
        self._by_no: dict[str, _Proposal] = {}
        self._proposal_seq = 0
        self._cert_seq = 0
        self._transient_seen: set[str] = set()
        self.calls: list[str] = []  # operation names, for tests

    # ---- priming from the seed
    def prime(
        self,
        *,
        our_reference: str,
        proposal_no: str,
        account_no: str,
        plan_code: str,
        insured_name: str,
        net: Decimal,
        gst: Decimal,
        gross: Decimal,
        certificate_no: str | None = None,
        risk_start: date | None = None,
        risk_end: date | None = None,
        payment_status: str | None = None,
        cancelled: bool = False,
    ) -> None:
        record = _Proposal(
            our_reference=our_reference,
            proposal_no=proposal_no,
            suffix=account_no[-4:],
            plan_code=plan_code,
            insured_name=insured_name,
            net=net,
            gst=gst,
            gross=gross,
            term_days=self._terms.get(plan_code, 365),
            status="ISSUED" if certificate_no else "PROPOSAL",
            payment_status=payment_status,
            certificate_no=certificate_no,
            risk_start=risk_start,
            risk_end=risk_end,
            cancelled=cancelled,
        )
        with self._lock:
            self._by_ref[our_reference] = record
            self._by_no[proposal_no] = record
            self._proposal_seq = max(self._proposal_seq, int(proposal_no[-6:]))
            if certificate_no:
                self._cert_seq = max(self._cert_seq, int(certificate_no[-6:]))

    def _wait(self, operation: str) -> None:
        self.calls.append(operation)
        if self._delay:
            self._sleep(self._delay)

    # ---- operations
    def create_proposal(
        self, request: ProposalRequest, *, correlation_id: str | None
    ) -> Outcome[ProposalCreated]:
        self._wait("create_proposal")
        suffix = request.account_no[-4:]
        if suffix == "6001":
            return Rejected(
                ErrorCategory.VALIDATION,
                "Synthetic insurer rejection: nominee details do not pass validation",
            )
        if suffix == "6004" and request.our_reference_no not in self._transient_seen:
            self._transient_seen.add(request.our_reference_no)
            return TransientError(ErrorCategory.UNAVAILABLE)
        table = self._mismatch if suffix == "6003" else self._premiums
        figures = table[request.plan_code]
        with self._lock:
            existing = self._by_ref.get(request.our_reference_no)
            if existing is None or existing.cancelled:
                self._proposal_seq += 1
                existing = _Proposal(
                    our_reference=request.our_reference_no,
                    proposal_no=f"SYNP{self._proposal_seq:06d}",
                    suffix=suffix,
                    plan_code=request.plan_code,
                    insured_name=f"{request.first_name} {request.last_name}".upper(),
                    net=Decimal(figures["net"]),
                    gst=Decimal(figures["gst"]),
                    gross=Decimal(figures["gross"]),
                    term_days=self._terms.get(request.plan_code, 365),
                )
                self._by_ref[request.our_reference_no] = existing
                self._by_no[existing.proposal_no] = existing
        if suffix == "6002":
            return UnknownOutcome(ErrorCategory.TIMEOUT)  # created, but the reply was lost
        return Success(
            ProposalCreated(
                proposal_no=existing.proposal_no,
                net_premium=existing.net,
                gst_amount=existing.gst,
                gross_premium=existing.gross,
                insurer_status="SUCCESS",
            )
        )

    def issue_policy(
        self, request: IssueRequest, *, correlation_id: str | None
    ) -> Outcome[PolicyIssued]:
        self._wait("issue_policy")
        with self._lock:
            record = self._by_no.get(request.proposal_no)
            if record is None:
                return Rejected(ErrorCategory.NOT_FOUND, "Synthetic insurer: proposal not found")
            if record.suffix == "6005":
                return TransientError(ErrorCategory.UNAVAILABLE)
            if record.certificate_no is None:
                self._cert_seq += 1
                start = self._clock().date()
                record.certificate_no = f"SYN/GPA/{self._cert_seq:06d}"
                record.risk_start = start
                record.risk_end = start + timedelta(days=record.term_days - 1)
                record.status = "ISSUED"
                record.payment_status = request.payment_status
            issued = PolicyIssued(record.certificate_no, record.risk_start, record.risk_end)  # type: ignore[arg-type]
            unknown = record.suffix == "6006"
        if unknown:
            return UnknownOutcome(ErrorCategory.TIMEOUT)  # issued, but the reply was lost
        return Success(issued)

    def fetch_certificate(
        self, certificate_no: str, proposal_no: str | None, *, correlation_id: str | None
    ) -> Outcome[Certificate]:
        self._wait("fetch_certificate")
        with self._lock:
            record = next(
                (r for r in self._by_no.values() if r.certificate_no == certificate_no), None
            )
        if record is None:
            return Rejected(ErrorCategory.NOT_FOUND, "Synthetic insurer: certificate not found")
        return Success(Certificate(certificate_pdf(record)))

    def get_proposal(
        self, *, proposal_no: str | None, our_reference: str, correlation_id: str | None
    ) -> Outcome[ProposalRecord]:
        self._wait("get_proposal")
        with self._lock:
            record = self._by_no.get(proposal_no) if proposal_no else None
            if record is None:
                record = self._by_ref.get(our_reference)
        if record is None:
            return Rejected(ErrorCategory.NOT_FOUND, "Synthetic insurer: no such proposal")
        return Success(
            ProposalRecord(
                proposal_no=record.proposal_no,
                status=record.status,
                payment_status=record.payment_status,
                certificate_no=record.certificate_no,
                risk_start_date=record.risk_start,
                risk_end_date=record.risk_end,
                net_premium=record.net,
                gst_amount=record.gst,
                gross_premium=record.gross,
                cancelled=record.cancelled,
            )
        )

    def cancel_certificate(
        self, certificate_no: str, *, our_reference: str, correlation_id: str | None
    ) -> Outcome[CancellationResult]:
        self._wait("cancel_certificate")
        with self._lock:
            record = next(
                (r for r in self._by_no.values() if r.certificate_no == certificate_no), None
            )
            if record is None:
                return Rejected(ErrorCategory.NOT_FOUND, "Synthetic insurer: certificate not found")
            record.cancelled = True
            record.status = "CANCELLED"
            unknown = record.suffix == "8001"
            # The fake's synthetic refund figure: the premium it charged. Not a refund rule (Q26).
            refund = CancellationResult(record.gross, self._clock().date())
        if unknown:
            return UnknownOutcome(ErrorCategory.TIMEOUT)
        return Success(refund)

    def cancel_proposal(
        self, proposal_no: str, *, our_reference: str, correlation_id: str | None
    ) -> Outcome[bool]:
        self._wait("cancel_proposal")
        with self._lock:
            record = self._by_no.get(proposal_no)
            if record is None:
                return Rejected(ErrorCategory.NOT_FOUND, "Synthetic insurer: proposal not found")
            record.cancelled = True
            record.status = "CANCELLED"
        return Success(True)


def certificate_pdf(record: _Proposal) -> bytes:
    return specimen_pdf(
        "Certificate of Insurance - Group Personal Accident",
        [
            f"Certificate number: {record.certificate_no}",
            f"Proposal number: {record.proposal_no}",
            f"Insured: {record.insured_name}",
            f"Plan: {record.plan_code}",
            f"Gross premium (INR): {record.gross}",
            f"Risk period: {record.risk_start} to {record.risk_end}",
            "Issued by a fake insurer for demonstration. No cover exists.",
        ],
    )

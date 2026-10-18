"""CBS posting port (transactions only; docs/contracts/cbs-posting.md).

``get_pool_statement`` (reconciliation) joins with the reconciliation task.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol


@dataclass(frozen=True)
class PostingResult:
    status: str  # SUCCESS, FAILED, UNKNOWN; NOT_FOUND only from get_posting_status
    tran_id: str | None = None
    tran_at: datetime | None = None
    reason: str | None = None


class PostingGateway(Protocol):
    def post_premium(
        self,
        cbs_request_ref: str,
        customer_account_no: str,
        pool_account_no: str,
        amount: Decimal,
        narration: str,
    ) -> PostingResult: ...

    def post_refund(
        self,
        cbs_request_ref: str,
        customer_account_no: str,
        pool_account_no: str,
        amount: Decimal,
        narration: str,
        original_request_ref: str | None,
    ) -> PostingResult: ...

    def get_posting_status(self, cbs_request_ref: str) -> PostingResult: ...


class UnconfiguredPosting:
    """Default outside dev/demo until the CBS transaction spec arrives (Q27).

    Fails before anything is sent, so a posting never reaches an unknown state through it.
    """

    def post_premium(
        self,
        cbs_request_ref: str,
        customer_account_no: str,
        pool_account_no: str,
        amount: Decimal,
        narration: str,
    ) -> PostingResult:
        return PostingResult("FAILED", reason="CBS posting is not configured")

    def post_refund(
        self,
        cbs_request_ref: str,
        customer_account_no: str,
        pool_account_no: str,
        amount: Decimal,
        narration: str,
        original_request_ref: str | None,
    ) -> PostingResult:
        return PostingResult("FAILED", reason="CBS posting is not configured")

    def get_posting_status(self, cbs_request_ref: str) -> PostingResult:
        return PostingResult("UNKNOWN")

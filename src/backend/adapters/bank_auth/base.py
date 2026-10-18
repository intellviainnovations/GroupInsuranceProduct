"""Bank authentication port (docs/contracts/bank-auth.md). The password exists only in memory."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol


class AuthStatus(StrEnum):
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    OTP_REQUIRED = "OTP_REQUIRED"
    LOCKED = "LOCKED"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass(frozen=True)
class BankIdentity:
    user_id: str  # the bank's roll number
    branch_code: str
    email: str | None = None
    designation: str | None = None
    display_name: str | None = None


@dataclass(frozen=True)
class AuthResult:
    status: AuthStatus
    identity: BankIdentity | None = None
    challenge_ref: str | None = None
    bank_session_ref: str | None = None


class AuthProvider(Protocol):
    def authenticate(
        self, branch_code: str, user_id: str, password: str, request_id: str
    ) -> AuthResult: ...

    def verify_otp(self, challenge_ref: str, otp: str, request_id: str) -> AuthResult: ...

    def logout(self, bank_session_ref: str) -> None: ...


class UnconfiguredAuthProvider:
    """Default outside dev/demo until the bank ESB provider is configured (Q29): fails closed."""

    def authenticate(
        self, branch_code: str, user_id: str, password: str, request_id: str
    ) -> AuthResult:
        return AuthResult(AuthStatus.UNAVAILABLE)

    def verify_otp(self, challenge_ref: str, otp: str, request_id: str) -> AuthResult:
        return AuthResult(AuthStatus.UNAVAILABLE)

    def logout(self, bank_session_ref: str) -> None:
        return None

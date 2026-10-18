"""Fake bank authentication for dev/demo (docs/design/repositories.md section 6). Synthetic only.

Triggers: the configured OTP user needs an OTP (valid value from the seed), the locked user is
LOCKED, the unavailable user is UNAVAILABLE, a wrong password or branch is FAILED.
"""

from __future__ import annotations

import hmac
import secrets
import threading
import time
from collections.abc import Callable, Mapping
from typing import Any

from backend.adapters.bank_auth.base import AuthResult, AuthStatus, BankIdentity


class FakeAuthProvider:
    def __init__(
        self,
        config: Mapping[str, Any],
        *,
        delay_seconds: float = 0.0,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._password: str = config["fake_password"]
        self._otp_user: str = config["otp_user"]
        self._valid_otp: str = config["valid_otp"]
        self._locked_user: str = config["locked_user"]
        self._unavailable_user: str = config["unavailable_user"]
        self._users = {
            u["roll_no"].upper(): BankIdentity(
                user_id=u["roll_no"],
                branch_code=u["branch_code"],
                email=u.get("email"),
                designation=u.get("designation"),
                display_name=u.get("display_name"),
            )
            for u in config["users"]
        }
        self._challenges: dict[str, BankIdentity] = {}
        self._lock = threading.Lock()
        self._delay = delay_seconds
        self._sleep = sleep

    def _wait(self) -> None:
        if self._delay:
            self._sleep(self._delay)

    def authenticate(
        self, branch_code: str, user_id: str, password: str, request_id: str
    ) -> AuthResult:
        self._wait()
        roll = user_id.upper()
        if roll == self._unavailable_user:
            return AuthResult(AuthStatus.UNAVAILABLE)
        if roll == self._locked_user:
            return AuthResult(AuthStatus.LOCKED)
        identity = self._users.get(roll)
        password_ok = hmac.compare_digest(password.encode(), self._password.encode())
        if identity is None or not password_ok or identity.branch_code != branch_code:
            return AuthResult(AuthStatus.FAILED)
        if roll == self._otp_user:
            ref = secrets.token_hex(16)
            with self._lock:
                self._challenges[ref] = identity
            return AuthResult(AuthStatus.OTP_REQUIRED, challenge_ref=ref)
        return AuthResult(
            AuthStatus.SUCCESS, identity=identity, bank_session_ref=secrets.token_hex(16)
        )

    def verify_otp(self, challenge_ref: str, otp: str, request_id: str) -> AuthResult:
        self._wait()
        with self._lock:
            identity = self._challenges.pop(challenge_ref, None)
        if identity is None or not hmac.compare_digest(otp.encode(), self._valid_otp.encode()):
            return AuthResult(AuthStatus.FAILED)
        return AuthResult(
            AuthStatus.SUCCESS, identity=identity, bank_session_ref=secrets.token_hex(16)
        )

    def logout(self, bank_session_ref: str) -> None:
        return None

"""Sign-in, OTP, sessions and logout (docs/contracts/bank-auth.md, staff-api.md).

The password lives only in the call to the provider; it is never logged, audited or stored.
Roles come from our own user-role data, never from the bank's designation text.
"""

from __future__ import annotations

import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from backend.adapters.bank_auth.base import AuthResult, AuthStatus, BankIdentity
from backend.domain.model import Branch, LoginChallenge, Session, ThrottleState, User, new_id
from backend.domain.repositories import UnitOfWork
from backend.services.common import Actor, Deps, ServiceError, audit, session_hash


@dataclass(frozen=True)
class SessionContext:
    actor: Actor
    session: Session
    session_id: str
    user: User


@dataclass(frozen=True)
class LoginOutcome:
    status: str  # SIGNED_IN or OTP_REQUIRED
    context: SessionContext | None = None
    challenge_id: UUID | None = None
    challenge_expires_at: datetime | None = None


def _anonymous(
    roll_no: str, branch_code: str | None, client_ip: str | None, correlation_id: str | None
) -> Actor:
    return Actor(
        None,
        roll_no[:20],
        branch_code,
        frozenset(),
        client_ip=client_ip,
        correlation_id=correlation_id,
    )


class AuthService:
    def __init__(self, deps: Deps) -> None:
        self.d = deps

    # ---------------------------------------------------------------- throttling
    def _check_throttle(self, uow: UnitOfWork, key: str, now: datetime) -> None:
        state = uow.sessions.throttle_get(key)
        if state is not None and state.locked_until is not None and state.locked_until > now:
            retry = max(1, int((state.locked_until - now).total_seconds()) + 1)
            raise ServiceError(429, "RATE_LIMITED", headers={"Retry-After": str(retry)})

    def _record_failure(self, key: str, now: datetime) -> None:
        cfg = self.d.config
        with self.d.uow() as uow:
            state = uow.sessions.throttle_get(key)
            if state is None or now - state.window_start > cfg.login_lock:
                state = ThrottleState(key, 0, now)
            state.fail_count += 1
            if state.fail_count >= cfg.login_max_failures:
                state.locked_until = now + cfg.login_lock
                state.fail_count = 0
                state.window_start = now
            uow.sessions.throttle_save(state)
            uow.commit()

    def _reset_throttle(self, uow: UnitOfWork, key: str, now: datetime) -> None:
        if uow.sessions.throttle_get(key) is not None:
            uow.sessions.throttle_save(ThrottleState(key, 0, now))

    def _fail(self, actor: Actor, key: str, now: datetime, detail: str) -> ServiceError:
        self._record_failure(key, now)
        with self.d.uow() as uow:
            audit(uow, actor, "LOGIN", outcome="FAILURE", detail=detail, when=now)
            uow.commit()
        return ServiceError(401, "LOGIN_FAILED")

    # ---------------------------------------------------------------- login
    def login(
        self,
        branch_code: str,
        roll_no: str,
        password: str,
        *,
        client_ip: str | None,
        correlation_id: str | None,
        previous_session_id: str | None,
    ) -> LoginOutcome:
        now = self.d.clock.now()
        key = f"roll:{roll_no.upper()}"
        actor = _anonymous(roll_no, branch_code, client_ip, correlation_id)
        with self.d.uow() as uow:
            self._check_throttle(uow, key, now)
        result = self.d.auth.authenticate(branch_code, roll_no, password, uuid.uuid4().hex)
        del password
        return self._handle(result, actor, key, now, previous_session_id)

    def verify_otp(
        self,
        challenge_id: UUID,
        otp: str,
        *,
        client_ip: str | None,
        correlation_id: str | None,
        previous_session_id: str | None,
    ) -> LoginOutcome:
        now = self.d.clock.now()
        with self.d.uow() as uow:
            challenge = uow.sessions.consume_challenge(challenge_id, now)
            uow.commit()
        if challenge is None:
            actor = _anonymous("UNKNOWN", None, client_ip, correlation_id)
            with self.d.uow() as uow:
                audit(uow, actor, "LOGIN_OTP", outcome="FAILURE", detail="challenge invalid")
                uow.commit()
            raise ServiceError(401, "LOGIN_FAILED")
        key = f"roll:{challenge.roll_no.upper()}"
        actor = _anonymous(challenge.roll_no, challenge.branch_code, client_ip, correlation_id)
        with self.d.uow() as uow:
            self._check_throttle(uow, key, now)
        result = self.d.auth.verify_otp(challenge.challenge_ref, otp, uuid.uuid4().hex)
        if result.status == AuthStatus.OTP_REQUIRED:  # a second OTP round is not supported
            raise self._fail(actor, key, now, "otp repeated")
        return self._handle(result, actor, key, now, previous_session_id)

    def _handle(
        self,
        result: AuthResult,
        actor: Actor,
        key: str,
        now: datetime,
        previous_session_id: str | None,
    ) -> LoginOutcome:
        if result.status == AuthStatus.UNAVAILABLE:
            with self.d.uow() as uow:
                audit(uow, actor, "LOGIN", outcome="FAILURE", detail="provider unavailable")
                uow.commit()
            raise ServiceError(503, "AUTH_UNAVAILABLE")
        if result.status in (AuthStatus.FAILED, AuthStatus.LOCKED):
            raise self._fail(actor, key, now, f"status={result.status.value}")
        if result.status == AuthStatus.OTP_REQUIRED:
            if not result.challenge_ref:
                raise self._fail(actor, key, now, "otp without challenge")
            challenge = LoginChallenge(
                challenge_id=new_id(),
                challenge_ref=result.challenge_ref,
                branch_code=actor.branch_code or "",
                roll_no=actor.roll_no,
                expires_at=now + self.d.config.otp_challenge,
            )
            with self.d.uow() as uow:
                uow.sessions.add_challenge(challenge)
                audit(uow, actor, "LOGIN", outcome="OTP_REQUIRED", when=now)
                uow.commit()
            return LoginOutcome(
                "OTP_REQUIRED",
                challenge_id=challenge.challenge_id,
                challenge_expires_at=challenge.expires_at,
            )
        if result.identity is None:
            raise self._fail(actor, key, now, "success without identity")
        context = self._establish(
            result.identity, result.bank_session_ref, actor, key, now, previous_session_id
        )
        return LoginOutcome("SIGNED_IN", context=context)

    def _establish(
        self,
        identity: BankIdentity,
        bank_session_ref: str | None,
        actor: Actor,
        key: str,
        now: datetime,
        previous_session_id: str | None,
    ) -> SessionContext:
        cfg = self.d.config
        session_id = secrets.token_urlsafe(32)  # 256-bit, rotated at every sign-in
        with self.d.uow() as uow:
            if previous_session_id:
                self._revoke(uow, previous_session_id, now, "ROTATED")
            # The branch always comes from the bank's reply, never from the request.
            if uow.users.get_branch(identity.branch_code) is None:
                uow.users.upsert_branch(Branch(identity.branch_code, None))
            user = uow.users.get_by_roll_no(identity.user_id)
            if user is None:
                user = User(
                    user_id=new_id(),
                    roll_no=identity.user_id,
                    branch_code=identity.branch_code,
                    display_name=identity.display_name,
                    first_login_at=now,
                )
            user.branch_code = identity.branch_code
            user.designation = identity.designation
            user.email = identity.email
            user.last_login_at = now
            user.first_login_at = user.first_login_at or now
            uow.users.save(user)
            session = Session(
                session_hash=session_hash(session_id),
                user_id=user.user_id,
                branch_code=identity.branch_code,
                created_at=now,
                last_seen_at=now,
                idle_expires_at=now + cfg.session_idle,
                absolute_expires_at=now + cfg.session_absolute,
                bank_session_ref=bank_session_ref,
                designation=identity.designation,
                client_ip=actor.client_ip,
            )
            uow.sessions.create(session)
            self._reset_throttle(uow, key, now)
            roles = uow.users.roles_for(user.user_id)
            signed_in = Actor(
                user.user_id,
                user.roll_no,
                user.branch_code,
                roles,
                user.display_name,
                actor.client_ip,
                actor.correlation_id,
            )
            audit(uow, signed_in, "LOGIN", detail=f"roles={','.join(sorted(roles))}", when=now)
            uow.commit()
        return SessionContext(signed_in, session, session_id, user)

    # ---------------------------------------------------------------- sessions
    def resolve(
        self, session_id: str, *, client_ip: str | None, correlation_id: str | None
    ) -> SessionContext | None:
        now = self.d.clock.now()
        with self.d.uow() as uow:
            session = uow.sessions.get_by_hash(session_hash(session_id))
            if session is None or session.revoked_at is not None:
                return None
            if now >= session.idle_expires_at or now >= session.absolute_expires_at:
                session.revoked_at, session.revoke_reason = now, "EXPIRED"
                uow.sessions.save(session)
                uow.commit()
                return None
            user = uow.users.get(session.user_id)
            if user is None or user.status != "ACTIVE":
                return None
            session.last_seen_at = now
            session.idle_expires_at = min(
                now + self.d.config.session_idle, session.absolute_expires_at
            )
            uow.sessions.save(session)
            roles = uow.users.roles_for(user.user_id)
            uow.commit()
        actor = Actor(
            user.user_id,
            user.roll_no,
            session.branch_code,
            roles,
            user.display_name,
            client_ip,
            correlation_id,
        )
        return SessionContext(actor, session, session_id, user)

    def _revoke(self, uow: UnitOfWork, session_id: str, now: datetime, reason: str) -> None:
        session = uow.sessions.get_by_hash(session_hash(session_id))
        if session is not None and session.revoked_at is None:
            session.revoked_at, session.revoke_reason = now, reason
            uow.sessions.save(session)

    def logout(self, context: SessionContext) -> None:
        now = self.d.clock.now()
        with self.d.uow() as uow:
            self._revoke(uow, context.session_id, now, "LOGOUT")
            audit(uow, context.actor, "LOGOUT", when=now)
            uow.commit()
        if context.session.bank_session_ref:
            self.d.auth.logout(context.session.bank_session_ref)

    def maker_checker(self) -> tuple[bool, bool]:
        with self.d.uow() as uow:
            enrol = (uow.reference.setting("maker_checker.enrolment") or "true") == "true"
            cancel = (uow.reference.setting("maker_checker.cancellation") or "true") == "true"
        return enrol, cancel

    def branch_name(self, code: str) -> str | None:
        with self.d.uow() as uow:
            branch = uow.users.get_branch(code)
        return branch.name if branch else None

    def audit_denied(self, actor: Actor, detail: str) -> None:
        with self.d.uow() as uow:
            audit(uow, actor, "ACCESS_DENIED", outcome="DENIED", detail=detail)
            uow.commit()

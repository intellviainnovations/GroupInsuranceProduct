"""Composition root: the only module that imports concrete persistence and adapters.

Reads ``Settings``, builds the unit-of-work factory and the adapters, primes the fakes from the
synthetic seed (memory backend), and returns the services. Services and routes see only ports.
"""

from __future__ import annotations

import logging
import secrets
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from backend.adapters.bank_auth.base import AuthProvider, UnconfiguredAuthProvider
from backend.adapters.bank_auth.fake import FakeAuthProvider
from backend.adapters.cbs.customer_directory.base import CustomerDirectory, UnconfiguredDirectory
from backend.adapters.cbs.fake_world import FakeCbsWorld, FakeCustomerDirectory, FakePostingGateway
from backend.adapters.cbs.posting.base import PostingGateway, UnconfiguredPosting
from backend.adapters.insurer.base import InsurerAdapter, UnconfiguredInsurer
from backend.adapters.insurer.fake import FakeInsurer
from backend.adapters.insurer.usgic.adapter import UsgicConfig, UsgicInsurer
from backend.adapters.insurer.usgic.cipher import PayloadCipher, build_cipher
from backend.domain.repositories import BackendUnavailable, UnitOfWork, UnitOfWorkFactory
from backend.persistence.memory.seed import load_seed, read_seed
from backend.persistence.memory.store import MemoryStore, memory_uow_factory
from backend.platform.config import Settings
from backend.services.approvals import ApprovalService, OperationsService
from backend.services.auth import AuthService
from backend.services.common import Clock, Deps, Keyring, ServiceConfig
from backend.services.enrolments import EnrolmentService
from backend.services.platform_services import (
    DashboardService,
    IdempotencyService,
    JobRunner,
    JobWorker,
)
from backend.services.sale import SaleService

logger = logging.getLogger("backend.bootstrap")


@dataclass
class Container:
    settings: Settings
    deps: Deps
    auth: AuthService
    enrolments: EnrolmentService
    sale: SaleService
    approvals: ApprovalService
    operations: OperationsService
    dashboard: DashboardService
    idempotency: IdempotencyService
    jobs: JobRunner
    worker: JobWorker | None
    readiness: dict[str, Callable[[], bool]] = field(default_factory=dict)
    store: MemoryStore | None = None
    fakes: dict[str, Any] = field(default_factory=dict)


def _sql_unavailable() -> UnitOfWork:
    raise BackendUnavailable("SQL backend is not implemented yet (T-002)")


def build_container(settings: Settings) -> Container:
    clock = Clock()
    secret_value = settings.session_secret.get_secret_value() if settings.session_secret else None
    secret = secret_value.encode() if secret_value else secrets.token_bytes(32)
    keys = Keyring(secret)
    delay = settings.fake_delay_ms / 1000
    readiness: dict[str, Callable[[], bool]] = {}
    fakes: dict[str, Any] = {}

    store: MemoryStore | None = None
    seed: dict[str, Any] | None = None
    uow: UnitOfWorkFactory
    if settings.resolved_data_backend == "memory":
        store = MemoryStore()
        seed = read_seed()
        load_seed(
            store,
            seed,
            now=clock.now(),
            account_hash=keys.account_key,
            retry_limit=settings.issue_retry_limit,
        )
        uow = memory_uow_factory(store)
    else:
        uow = _sql_unavailable

    needs_seed = settings.synthetic_allowed and seed is None
    if needs_seed and any(
        settings.resolved_adapter(n) == "fake" for n in ("insurer_adapter", "bank_auth", "cbs")
    ):
        seed = read_seed()  # fakes need the synthetic world even without the memory backend

    auth: AuthProvider = UnconfiguredAuthProvider()
    if settings.resolved_adapter("bank_auth") == "fake" and seed is not None:
        auth = FakeAuthProvider(seed["bank_auth"], delay_seconds=delay)
        fakes["bank_auth"] = auth

    directory: CustomerDirectory = UnconfiguredDirectory()
    posting: PostingGateway = UnconfiguredPosting()
    if settings.resolved_adapter("cbs") == "fake" and seed is not None:
        world = FakeCbsWorld.from_seed(
            seed["cbs_world"],
            timeout_seconds=settings.cbs_timeout_seconds,
            delay_seconds=delay,
            clock=clock.now,
        )
        directory, posting = FakeCustomerDirectory(world), FakePostingGateway(world)
        fakes["cbs_world"] = world

    insurer: InsurerAdapter = UnconfiguredInsurer()
    insurer_choice = settings.resolved_adapter("insurer_adapter")
    if insurer_choice == "fake" and seed is not None:
        insurer = FakeInsurer(seed["fake_insurer"], delay_seconds=delay, clock=clock.now)
        fakes["insurer"] = insurer
    elif insurer_choice == "usgic":
        cipher_key: bytes | None = None
        if settings.usgic_cipher == "aes-256-cbc" and settings.usgic_cipher_key:
            cipher_key = settings.usgic_cipher_key.get_secret_value().encode("utf-8")
        cipher: PayloadCipher = build_cipher(settings.usgic_cipher, key=cipher_key)

        # ABHI APIM subscription key for Azure API Management authentication.
        abhi_key: str | None = None
        if settings.abhi_apim_subscription_key:
            abhi_key = settings.abhi_apim_subscription_key.get_secret_value()

        def code_mapper(category: str, our_code: str) -> str | None:
            with uow() as u:
                return u.reference.map_code("USGIC", category, our_code)

        insurer = UsgicInsurer(
            UsgicConfig(
                base_url=settings.usgic_base_url or "",
                user_name=settings.usgic_user_name or "",
                product_code=settings.usgic_product_code or "",
                password=(
                    settings.usgic_password.get_secret_value() if settings.usgic_password else None
                ),
                intermediary_code=settings.usgic_intermediary_code,
                intermediary_branch_code=settings.usgic_intermediary_branch_code,
                token_header=settings.usgic_token_header,
                refresh_margin_seconds=settings.usgic_token_refresh_margin_seconds,
                default_token_ttl_seconds=settings.usgic_token_default_ttl_seconds,
                connect_timeout_seconds=settings.usgic_connect_timeout_seconds,
                read_timeout_seconds=settings.usgic_read_timeout_seconds,
                apim_subscription_key=abhi_key,
            ),
            cipher,
            code_mapper,
            clock=clock.now,
        )
        readiness["insurer_cipher"] = lambda: cipher.configured

    config = ServiceConfig(
        env=settings.env,
        synthetic_data=settings.synthetic_data,
        selectable_statuses=settings.selectable_status_set,
        issue_retry_limit=settings.issue_retry_limit,
        retry_delay_seconds=settings.retry_delay_seconds,
        session_idle=_minutes(settings.session_idle_minutes),
        session_absolute=_minutes(settings.session_absolute_minutes),
        login_max_failures=settings.login_max_failures,
        login_lock=_minutes(settings.login_lock_minutes),
        otp_challenge=_minutes(settings.otp_challenge_minutes),
    )
    deps = Deps(uow, insurer, auth, directory, posting, keys, clock, config)
    if isinstance(insurer, FakeInsurer) and store is not None:
        _prime_fakes(store, insurer, fakes.get("cbs_world"))

    sale = SaleService(deps)
    runner = JobRunner(deps, sale.job_handlers())
    worker = None
    if settings.job_worker_enabled and store is not None:
        worker = JobWorker(runner, settings.job_poll_seconds)
        deps.on_job_enqueued = worker.wake
    if settings.synthetic_data:
        logger.warning(
            "synthetic data active (memory backend or fake adapters); not for production"
        )
    return Container(
        settings=settings,
        deps=deps,
        auth=AuthService(deps),
        enrolments=EnrolmentService(deps),
        sale=sale,
        approvals=ApprovalService(deps, sale),
        operations=OperationsService(deps, sale),
        dashboard=DashboardService(deps),
        idempotency=IdempotencyService(deps),
        jobs=runner,
        worker=worker,
        readiness=readiness,
        store=store,
        fakes=fakes,
    )


def _minutes(value: int) -> timedelta:
    return timedelta(minutes=value)


def _prime_fakes(store: MemoryStore, insurer: FakeInsurer, world: FakeCbsWorld | None) -> None:
    """Teach the fakes the proposals and postings of seeded enrolments (so RECHECK works)."""
    accounts = store.table("customer_account")
    for e in store.table("enrolment").values():
        account = accounts.get(e.customer_account_id)
        if account is None:
            continue
        if (
            e.insurer_proposal_no
            and e.net_premium is not None
            and e.gst_amount is not None
            and e.gross_premium is not None
        ):
            insurer.prime(
                our_reference=e.our_reference_no,
                proposal_no=e.insurer_proposal_no,
                account_no=account.account_no,
                plan_code=e.plan_code or "A",
                insured_name=e.insured.full_name.upper(),
                net=e.net_premium,
                gst=e.gst_amount,
                gross=e.gross_premium,
                certificate_no=e.certificate_no,
                risk_start=e.risk_start_date,
                risk_end=e.risk_end_date,
                payment_status="SUCCESS" if e.successful_premium_posting() else None,
                cancelled=e.status.value in ("CANCELLED", "PROPOSAL_CANCELLED"),
            )
        if world is None:
            continue
        for p in e.postings:
            status = {"SUCCESS": "SUCCESS", "FAILED": "FAILED", "UNKNOWN": "UNCLEAR"}.get(p.status)
            if status is not None:
                world.prime_posting(
                    p.cbs_request_ref, status, p.cbs_tran_id, p.cbs_tran_at, p.amount
                )

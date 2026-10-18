"""Staff API routes under /api/v1 (docs/contracts/staff-api.openapi.yaml).

Every route is authenticated and authorised through ``deps`` (deny by default); unsafe methods
also pass the Origin and CSRF checks. Routes are synchronous: adapters block, so FastAPI runs
them in its thread pool.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Path, Query, Request, Response
from fastapi.responses import JSONResponse

from backend.api.v1 import schemas as s
from backend.api.v1 import views
from backend.api.v1.deps import (
    SESSION_COOKIE,
    client_ip,
    container,
    cookie_session_id,
    csrf_session_context,
    error_responses,
    json_body,
    origin_check,
    roles,
    roles_csrf,
    session_context,
)
from backend.bootstrap import Container
from backend.domain.model import Nominee, Role
from backend.domain.repositories import EnrolmentQuery
from backend.platform.request_context import get_correlation_id
from backend.services.auth import LoginOutcome, SessionContext
from backend.services.common import ActionOutcome, ActionResult, Actor
from backend.services.enrolments import DraftChanges

R = Role
router = APIRouter(prefix="/api/v1", dependencies=[Depends(origin_check)])

C = Annotated[Container, Depends(container)]
IdemKey = Annotated[UUID, Header(alias="Idempotency-Key")]
IdemKeyOpt = Annotated[UUID | None, Header(alias="Idempotency-Key")]
EnrolmentId = Annotated[UUID, Path()]
ApprovalId = Annotated[UUID, Path()]
PageQ = Annotated[int, Query(ge=1, le=10000)]
PageSizeQ = Annotated[int, Query(ge=1, le=100)]

AnyRole = Annotated[Actor, Depends(roles())]
Readers = Annotated[Actor, Depends(roles(R.BRANCH_USER, R.CHECKER, R.OPERATIONS, R.AUDITOR))]
MakerPost = Annotated[Actor, Depends(roles_csrf(R.BRANCH_USER))]
IssuePost = Annotated[Actor, Depends(roles_csrf(R.BRANCH_USER, R.OPERATIONS))]
DeciderPost = Annotated[Actor, Depends(roles_csrf(R.CHECKER, R.OPERATIONS))]
OpsPost = Annotated[Actor, Depends(roles_csrf(R.OPERATIONS))]


def _set_cookie(c: Container, response: Response, session_id: str) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        session_id,
        httponly=True,
        secure=c.settings.session_cookie_secure,
        samesite="strict",
        path="/api",
    )


def _me(c: Container, ctx: SessionContext) -> s.Me:
    enrol, cancel = c.auth.maker_checker()
    actor, user = ctx.actor, ctx.user
    mode = c.settings.env if c.settings.env in ("dev", "demo", "uat") else "prod"
    return s.Me(
        user_id=user.user_id,
        roll_no=user.roll_no,
        display_name=user.display_name,
        designation=ctx.session.designation or user.designation,
        branch=s.Branch(
            code=ctx.session.branch_code, name=c.auth.branch_name(ctx.session.branch_code)
        ),
        roles=sorted(r.value for r in actor.roles),
        cross_branch=actor.cross_branch,
        csrf_token=c.deps.keys.csrf_token(ctx.session_id),
        session=s.MeSession(
            idle_expires_at=views.utc(ctx.session.idle_expires_at),
            absolute_expires_at=views.utc(ctx.session.absolute_expires_at),
        ),
        environment=s.MeEnvironment(mode=mode, synthetic_data=c.settings.synthetic_data),  # type: ignore[arg-type]
        settings=s.MeSettings(maker_checker_enrolment=enrol, maker_checker_cancellation=cancel),
    )


def _login_result(c: Container, outcome: LoginOutcome, response: Response) -> s.LoginResult:
    if outcome.context is not None:
        _set_cookie(c, response, outcome.context.session_id)
        return s.LoginResult(status="SIGNED_IN", me=_me(c, outcome.context))
    return s.LoginResult(
        status="OTP_REQUIRED",
        challenge_id=outcome.challenge_id,
        challenge_expires_at=(
            views.utc(outcome.challenge_expires_at) if outcome.challenge_expires_at else None
        ),
    )


# ====================================================================== auth
@router.post(
    "/auth/login",
    tags=["auth"],
    operation_id="login",
    response_model=s.LoginResult,
    responses=error_responses(401, 422, 429, 503),
    dependencies=[Depends(json_body)],
)
def login(body: s.LoginRequest, request: Request, response: Response, c: C) -> s.LoginResult:
    outcome = c.auth.login(
        body.branch_code,
        body.roll_no,
        body.password,
        client_ip=client_ip(request),
        correlation_id=get_correlation_id(),
        previous_session_id=cookie_session_id(request),
    )
    return _login_result(c, outcome, response)


@router.post(
    "/auth/otp",
    tags=["auth"],
    operation_id="verifyOtp",
    response_model=s.LoginResult,
    responses=error_responses(401, 422, 429, 503),
    dependencies=[Depends(json_body)],
)
def verify_otp(body: s.OtpRequest, request: Request, response: Response, c: C) -> s.LoginResult:
    outcome = c.auth.verify_otp(
        body.challenge_id,
        body.otp,
        client_ip=client_ip(request),
        correlation_id=get_correlation_id(),
        previous_session_id=cookie_session_id(request),
    )
    return _login_result(c, outcome, response)


@router.post(
    "/auth/logout",
    tags=["auth"],
    operation_id="logout",
    status_code=204,
    responses=error_responses(401, 403),
)
def logout(ctx: Annotated[SessionContext, Depends(csrf_session_context)], c: C) -> Response:
    c.auth.logout(ctx)
    response = Response(status_code=204)
    response.delete_cookie(
        SESSION_COOKIE,
        path="/api",
        secure=c.settings.session_cookie_secure,
        httponly=True,
        samesite="strict",
    )
    return response


@router.get(
    "/me", tags=["auth"], operation_id="getMe", response_model=s.Me, responses=error_responses(401)
)
def get_me(ctx: Annotated[SessionContext, Depends(session_context)], c: C) -> s.Me:
    return _me(c, ctx)


# ====================================================================== reference
@router.get(
    "/reference/codes",
    tags=["reference"],
    operation_id="listRefCodes",
    response_model=s.RefCodes,
    responses=error_responses(401, 403),
)
def list_ref_codes(actor: AnyRole, c: C) -> s.RefCodes:
    grouped: dict[str, list[s.RefCodeItem]] = {k: [] for k in s.RefCodes.model_fields}
    for code in c.enrolments.ref_codes():
        if code.category in grouped:
            grouped[code.category].append(s.RefCodeItem(code=code.code, label=code.label))
    return s.RefCodes(**grouped)


@router.get(
    "/reference/plans",
    tags=["reference"],
    operation_id="listPlans",
    response_model=s.PlanList,
    responses=error_responses(401, 403),
)
def list_plans(actor: AnyRole, c: C) -> s.PlanList:
    return s.PlanList(items=[views.plan(p, r) for p, r in c.enrolments.plans()])


# ====================================================================== customers
@router.post(
    "/customers/lookup",
    tags=["customers"],
    operation_id="lookupCustomer",
    response_model=s.CustomerLookupResult,
    responses=error_responses(401, 403, 404, 422, 503),
)
def lookup_customer(
    body: s.CustomerLookupRequest, actor: MakerPost, c: C
) -> s.CustomerLookupResult:
    return views.lookup_result(c.enrolments.lookup(actor, body.account_no, body.cif))


# ====================================================================== enrolments
def _detail(c: Container, actor: Actor, enrolment_id: UUID) -> s.EnrolmentDetail:
    bundle = c.enrolments.detail(actor, enrolment_id)
    return views.detail(bundle, c.deps.config.selectable_statuses)


def _action(
    c: Container,
    actor: Actor,
    operation: str,
    target: UUID,
    key: UUID | None,
    body: dict[str, Any],
    run: Any,
) -> s.ActionResult:
    result: ActionResult = c.idempotency.run(actor, operation, target, key, body, run)
    o = result.outcome
    outcome = s.Outcome.model_validate(
        {
            "result": o.result,
            "category": o.category,
            "message": o.message[:300] if o.message else None,
            "replayed": o.replayed,
        }
    )
    return s.ActionResult(enrolment=_detail(c, actor, result.enrolment_id), outcome=outcome)


@router.get(
    "/enrolments",
    tags=["enrolments"],
    operation_id="listEnrolments",
    response_model=s.EnrolmentPage,
    responses=error_responses(401, 403, 422),
)
def list_enrolments(
    actor: Readers,
    c: C,
    status: Annotated[list[s.EnrolmentStatus] | None, Query(max_length=14)] = None,
    created_from: date | None = None,
    created_to: date | None = None,
    q: Annotated[
        str | None, Query(min_length=3, max_length=40, pattern=r"^[A-Za-z0-9/_-]+$")
    ] = None,
    branch_code: Annotated[str | None, Query(pattern=r"^[A-Z0-9]{1,10}$")] = None,
    mine: bool = False,
    page: PageQ = 1,
    page_size: PageSizeQ = 20,
    sort: Literal[
        "-created_at", "created_at", "-status_changed_at", "status_changed_at"
    ] = "-created_at",
) -> s.EnrolmentPage:
    query = EnrolmentQuery(
        branch_codes=None,
        statuses=frozenset(status) if status else None,
        created_from=created_from,
        created_to=created_to,
        text_prefix=q,
        page=page,
        page_size=page_size,
        sort=sort,
    )
    found, makers = c.enrolments.search(actor, query, branch_code, mine)
    return s.EnrolmentPage(
        items=[views.summary(e, makers.get(e.created_by)) for e in found.items],
        page=found.page,
        page_size=found.page_size,
        total=found.total,
    )


@router.post(
    "/enrolments",
    tags=["enrolments"],
    operation_id="createDraft",
    status_code=201,
    response_model=s.EnrolmentDetail,
    responses=error_responses(401, 403, 404, 409, 422, 503),
)
def create_draft(
    body: s.DraftCreate, actor: MakerPost, c: C, key: IdemKeyOpt = None
) -> JSONResponse:
    def run() -> ActionResult:
        new_id = c.enrolments.create_draft(
            actor, body.lookup.account_no, body.lookup.cif, body.debit_account_key, body.plan_code
        )
        return ActionResult(new_id, _done(), 201)

    result = c.idempotency.run(actor, "create_draft", None, key, body.model_dump(mode="json"), run)
    return _created(c, actor, result.enrolment_id)


def _done() -> ActionOutcome:
    return ActionOutcome()


def _created(c: Container, actor: Actor, enrolment_id: UUID) -> JSONResponse:
    detail = _detail(c, actor, enrolment_id)
    return JSONResponse(
        detail.model_dump(mode="json"),
        status_code=201,
        headers={"Location": f"/api/v1/enrolments/{enrolment_id}"},
    )


@router.get(
    "/enrolments/{enrolment_id}",
    tags=["enrolments"],
    operation_id="getEnrolment",
    response_model=s.EnrolmentDetail,
    responses=error_responses(401, 403, 404),
)
def get_enrolment(enrolment_id: EnrolmentId, actor: Readers, c: C) -> s.EnrolmentDetail:
    return _detail(c, actor, enrolment_id)


def _nominee(seq: int, n: s.NomineeInput) -> Nominee:
    values = n.model_dump()
    values["share_percent"] = Decimal(n.share_percent)
    return Nominee(seq=seq, **values)


@router.patch(
    "/enrolments/{enrolment_id}",
    tags=["enrolments"],
    operation_id="updateDraft",
    response_model=s.EnrolmentDetail,
    responses=error_responses(401, 403, 404, 409, 422),
)
def update_draft(
    enrolment_id: EnrolmentId, body: s.DraftPatch, actor: MakerPost, c: C
) -> s.EnrolmentDetail:
    changes = DraftChanges(
        version=body.version,
        debit_account_key=body.debit_account_key,
        plan_code=body.plan_code,
        insured=body.insured.model_dump(exclude_unset=True) if body.insured is not None else None,
        nominees=(
            [_nominee(i, n) for i, n in enumerate(body.nominees, start=1)]
            if body.nominees is not None
            else None
        ),
        fields_set=set(body.model_fields_set),
    )
    c.enrolments.update_draft(actor, enrolment_id, changes)
    return _detail(c, actor, enrolment_id)


@router.post(
    "/enrolments/{enrolment_id}/submit",
    tags=["enrolments"],
    operation_id="submitDraft",
    response_model=s.ActionResult,
    responses=error_responses(401, 403, 404, 409, 422),
)
def submit_draft(
    enrolment_id: EnrolmentId, body: s.SubmitRequest, actor: MakerPost, c: C
) -> s.ActionResult:
    return _action(
        c,
        actor,
        "submit",
        enrolment_id,
        None,
        {},
        lambda: c.enrolments.submit(actor, enrolment_id, body.version, body.comment),
    )


@router.post(
    "/enrolments/{enrolment_id}/proposal",
    tags=["enrolments"],
    operation_id="createProposal",
    response_model=s.ActionResult,
    responses=error_responses(401, 403, 404, 409, 422),
)
def create_proposal(
    enrolment_id: EnrolmentId, body: s.VersionOnly, actor: MakerPost, c: C, key: IdemKey
) -> s.ActionResult:
    return _action(
        c,
        actor,
        "proposal",
        enrolment_id,
        key,
        body.model_dump(),
        lambda: c.sale.create_proposal(actor, enrolment_id, body.version),
    )


@router.post(
    "/enrolments/{enrolment_id}/consent",
    tags=["enrolments"],
    operation_id="recordConsent",
    response_model=s.ActionResult,
    responses=error_responses(401, 403, 404, 409, 422),
)
def record_consent(
    enrolment_id: EnrolmentId, body: s.ConsentRequest, actor: MakerPost, c: C
) -> s.ActionResult:
    amount = Decimal(body.confirmed_amount) if body.confirmed_amount else None
    return _action(
        c,
        actor,
        "consent",
        enrolment_id,
        None,
        {},
        lambda: c.sale.record_consent(
            actor, enrolment_id, body.version, body.method, body.reference, amount
        ),
    )


@router.post(
    "/enrolments/{enrolment_id}/payment",
    tags=["enrolments"],
    operation_id="postPayment",
    response_model=s.ActionResult,
    responses=error_responses(401, 403, 404, 409, 422),
)
def post_payment(
    enrolment_id: EnrolmentId, body: s.VersionOnly, actor: MakerPost, c: C, key: IdemKey
) -> s.ActionResult:
    return _action(
        c,
        actor,
        "payment",
        enrolment_id,
        key,
        body.model_dump(),
        lambda: c.sale.post_payment(actor, enrolment_id, body.version),
    )


@router.post(
    "/enrolments/{enrolment_id}/policy",
    tags=["enrolments"],
    operation_id="retryIssue",
    response_model=s.ActionResult,
    responses=error_responses(401, 403, 404, 409),
)
def retry_issue(
    enrolment_id: EnrolmentId, body: s.VersionOnly, actor: IssuePost, c: C, key: IdemKey
) -> s.ActionResult:
    return _action(
        c,
        actor,
        "policy",
        enrolment_id,
        key,
        body.model_dump(),
        lambda: c.sale.retry_issue(actor, enrolment_id, body.version),
    )


@router.post(
    "/enrolments/{enrolment_id}/reopen",
    tags=["enrolments"],
    operation_id="reopenDraft",
    response_model=s.ActionResult,
    responses=error_responses(401, 403, 404, 409),
)
def reopen_draft(
    enrolment_id: EnrolmentId, body: s.VersionOnly, actor: MakerPost, c: C
) -> s.ActionResult:
    return _action(
        c,
        actor,
        "reopen",
        enrolment_id,
        None,
        {},
        lambda: c.enrolments.reopen(actor, enrolment_id, body.version),
    )


@router.post(
    "/enrolments/{enrolment_id}/abandon",
    tags=["enrolments"],
    operation_id="abandonProposal",
    response_model=s.ActionResult,
    responses=error_responses(401, 403, 404, 409),
)
def abandon_proposal(
    enrolment_id: EnrolmentId, body: s.CommentedVersion, actor: MakerPost, c: C, key: IdemKey
) -> s.ActionResult:
    return _action(
        c,
        actor,
        "abandon",
        enrolment_id,
        key,
        body.model_dump(),
        lambda: c.sale.abandon(actor, enrolment_id, body.version, body.comment),
    )


@router.post(
    "/enrolments/{enrolment_id}/copy",
    tags=["enrolments"],
    operation_id="copyToDraft",
    status_code=201,
    response_model=s.EnrolmentDetail,
    responses=error_responses(401, 403, 404, 409, 503),
)
def copy_to_draft(
    enrolment_id: EnrolmentId, actor: MakerPost, c: C, key: IdemKeyOpt = None
) -> JSONResponse:
    def run() -> ActionResult:
        return ActionResult(c.enrolments.copy_rejected(actor, enrolment_id), _done(), 201)

    result = c.idempotency.run(actor, "copy", enrolment_id, key, {}, run)
    return _created(c, actor, result.enrolment_id)


@router.get(
    "/enrolments/{enrolment_id}/certificate",
    tags=["enrolments"],
    operation_id="downloadCertificate",
    response_class=Response,
    responses={
        200: {
            "content": {
                "application/pdf": {
                    "schema": {"type": "string", "contentMediaType": "application/pdf"}
                }
            }
        },
        **error_responses(401, 403, 404),
    },
)
def download_certificate(enrolment_id: EnrolmentId, actor: Readers, c: C) -> Response:
    doc = c.enrolments.certificate(actor, enrolment_id)
    return Response(
        doc.content,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{doc.file_name}"'},
    )


@router.post(
    "/enrolments/{enrolment_id}/cancellation",
    tags=["enrolments"],
    operation_id="requestCancellation",
    response_model=s.ActionResult,
    responses=error_responses(401, 403, 404, 409, 422),
)
def request_cancellation(
    enrolment_id: EnrolmentId, body: s.CancellationRequest, actor: MakerPost, c: C, key: IdemKey
) -> s.ActionResult:
    return _action(
        c,
        actor,
        "cancellation",
        enrolment_id,
        key,
        body.model_dump(),
        lambda: c.sale.request_cancellation(
            actor, enrolment_id, body.version, body.reason_code, body.remarks
        ),
    )


# ====================================================================== approvals
@router.get(
    "/approvals",
    tags=["approvals"],
    operation_id="listApprovals",
    response_model=s.ApprovalPage,
    responses=error_responses(401, 403),
)
def list_approvals(
    actor: Annotated[Actor, Depends(roles(R.CHECKER, R.OPERATIONS, R.AUDITOR))],
    c: C,
    action: s.ApprovalAction | None = None,
    status: Literal["PENDING", "APPROVED", "REJECTED", "WITHDRAWN"] = "PENDING",
    entity_type: Literal["ENROLMENT", "CANCELLATION"] | None = None,
    page: PageQ = 1,
    page_size: PageSizeQ = 20,
) -> s.ApprovalPage:
    found = c.approvals.search(
        actor, action=action, status=status, entity_type=entity_type, page=page, page_size=page_size
    )
    return s.ApprovalPage(
        items=[views.approval(b) for b in found.items],
        page=found.page,
        page_size=found.page_size,
        total=found.total,
    )


@router.post(
    "/approvals/{approval_id}/approve",
    tags=["approvals"],
    operation_id="approve",
    response_model=s.ActionResult,
    responses=error_responses(401, 403, 404, 409),
)
def approve(
    approval_id: ApprovalId, body: s.DecisionRequest, actor: DeciderPost, c: C, key: IdemKey
) -> s.ActionResult:
    return _action(
        c,
        actor,
        "approve",
        approval_id,
        key,
        body.model_dump(),
        lambda: c.approvals.approve(actor, approval_id, body.comment),
    )


@router.post(
    "/approvals/{approval_id}/reject",
    tags=["approvals"],
    operation_id="reject",
    response_model=s.ActionResult,
    responses=error_responses(401, 403, 404, 409, 422),
)
def reject(
    approval_id: ApprovalId, body: s.RejectRequest, actor: DeciderPost, c: C
) -> s.ActionResult:
    return _action(
        c,
        actor,
        "reject",
        approval_id,
        None,
        {},
        lambda: c.approvals.reject(actor, approval_id, body.comment),
    )


# ====================================================================== operations
@router.get(
    "/operations/attention",
    tags=["operations"],
    operation_id="listAttention",
    response_model=s.EnrolmentPage,
    responses=error_responses(401, 403),
)
def list_attention(
    actor: Annotated[Actor, Depends(roles(R.OPERATIONS, R.AUDITOR))],
    c: C,
    reason: s.AttentionReason | None = None,
    page: PageQ = 1,
    page_size: PageSizeQ = 20,
) -> s.EnrolmentPage:
    found, makers = c.operations.attention(actor, reason, page, page_size)
    return s.EnrolmentPage(
        items=[views.summary(e, makers.get(e.created_by)) for e in found.items],
        page=found.page,
        page_size=found.page_size,
        total=found.total,
    )


@router.post(
    "/operations/attention/{enrolment_id}/resolve",
    tags=["operations"],
    operation_id="resolveAttention",
    response_model=s.ActionResult,
    responses=error_responses(401, 403, 404, 409, 422),
)
def resolve_attention(
    enrolment_id: EnrolmentId, body: s.ResolveRequest, actor: OpsPost, c: C, key: IdemKey
) -> s.ActionResult:
    return _action(
        c,
        actor,
        "resolve",
        enrolment_id,
        key,
        body.model_dump(),
        lambda: c.operations.resolve(
            actor,
            enrolment_id,
            body.version,
            body.action,
            body.target_status,
            body.note,
            body.evidence_ref,
        ),
    )


# ====================================================================== dashboard
@router.get(
    "/dashboard",
    tags=["dashboard"],
    operation_id="getDashboard",
    response_model=s.Dashboard,
    responses=error_responses(401, 403),
)
def get_dashboard(actor: AnyRole, c: C) -> s.Dashboard:
    data = c.dashboard.build(actor)
    queues: dict[str, Any] = {}
    for name, items in data.queues.items():
        if name == "awaiting_my_approval":
            queues[name] = [views.approval(b) for b in items]
        else:
            queues[name] = [views.summary(e, data.makers.get(e.created_by)) for e in items]
    return s.Dashboard(
        as_of=views.utc(data.as_of),
        scope=s.DashboardScope(all_branches=data.all_branches, branch_code=data.branch_code),
        kpis=s.DashboardKpis(**data.kpis),
        queues=s.DashboardQueues(**queues),
    )

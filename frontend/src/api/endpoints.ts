// One function per contract operation (docs/contracts/staff-api.openapi.yaml).
import { apiBlob, apiRequest } from "./client";
import type {
  ActionResult,
  ApprovalAction,
  ApprovalPage,
  ApprovalStatus,
  AttentionReason,
  CancellationRequest,
  CommentedVersion,
  ConsentRequest,
  CustomerLookupRequest,
  CustomerLookupResult,
  Dashboard,
  DecisionRequest,
  DraftCreate,
  DraftPatch,
  EnrolmentDetail,
  EnrolmentPage,
  EnrolmentStatus,
  LoginRequest,
  LoginResult,
  Me,
  OtpRequest,
  Plan,
  RefCodes,
  RejectRequest,
  ResolveRequest,
  SubmitRequest,
  VersionOnly,
} from "./types";

const enc = encodeURIComponent;

export const api = {
  login: (body: LoginRequest) => apiRequest<LoginResult>("POST", "/auth/login", { body }),
  otp: (body: OtpRequest) => apiRequest<LoginResult>("POST", "/auth/otp", { body }),
  logout: () => apiRequest<void>("POST", "/auth/logout"),
  me: () => apiRequest<Me>("GET", "/me"),

  refCodes: () => apiRequest<RefCodes>("GET", "/reference/codes"),
  plans: () => apiRequest<{ items: Plan[] }>("GET", "/reference/plans"),

  lookupCustomer: (body: CustomerLookupRequest) =>
    apiRequest<CustomerLookupResult>("POST", "/customers/lookup", { body }),

  listEnrolments: (q: {
    status?: EnrolmentStatus[] | undefined;
    created_from?: string | undefined;
    created_to?: string | undefined;
    q?: string | undefined;
    branch_code?: string | undefined;
    mine?: boolean | undefined;
    page?: number | undefined;
    page_size?: number | undefined;
    sort?: string | undefined;
  }) => apiRequest<EnrolmentPage>("GET", "/enrolments", { query: q }),
  createEnrolment: (body: DraftCreate, idempotencyKey: string) =>
    apiRequest<EnrolmentDetail>("POST", "/enrolments", { body, idempotencyKey }),
  getEnrolment: (id: string) => apiRequest<EnrolmentDetail>("GET", `/enrolments/${enc(id)}`),
  patchEnrolment: (id: string, body: DraftPatch) =>
    apiRequest<EnrolmentDetail>("PATCH", `/enrolments/${enc(id)}`, { body }),
  submit: (id: string, body: SubmitRequest) =>
    apiRequest<ActionResult>("POST", `/enrolments/${enc(id)}/submit`, { body }),
  proposal: (id: string, body: VersionOnly, idempotencyKey: string) =>
    apiRequest<ActionResult>("POST", `/enrolments/${enc(id)}/proposal`, { body, idempotencyKey }),
  consent: (id: string, body: ConsentRequest) =>
    apiRequest<ActionResult>("POST", `/enrolments/${enc(id)}/consent`, { body }),
  payment: (id: string, body: VersionOnly, idempotencyKey: string) =>
    apiRequest<ActionResult>("POST", `/enrolments/${enc(id)}/payment`, { body, idempotencyKey }),
  policy: (id: string, body: VersionOnly, idempotencyKey: string) =>
    apiRequest<ActionResult>("POST", `/enrolments/${enc(id)}/policy`, { body, idempotencyKey }),
  reopen: (id: string, body: VersionOnly) =>
    apiRequest<ActionResult>("POST", `/enrolments/${enc(id)}/reopen`, { body }),
  abandon: (id: string, body: CommentedVersion, idempotencyKey: string) =>
    apiRequest<ActionResult>("POST", `/enrolments/${enc(id)}/abandon`, { body, idempotencyKey }),
  copy: (id: string, idempotencyKey: string) =>
    apiRequest<EnrolmentDetail>("POST", `/enrolments/${enc(id)}/copy`, { body: {}, idempotencyKey }),
  certificate: (id: string) => apiBlob(`/enrolments/${enc(id)}/certificate`),
  cancellation: (id: string, body: CancellationRequest, idempotencyKey: string) =>
    apiRequest<ActionResult>("POST", `/enrolments/${enc(id)}/cancellation`, { body, idempotencyKey }),

  listApprovals: (q: {
    action?: ApprovalAction | undefined;
    status?: ApprovalStatus | undefined;
    page?: number | undefined;
    page_size?: number | undefined;
  }) => apiRequest<ApprovalPage>("GET", "/approvals", { query: q }),
  approve: (id: string, body: DecisionRequest, idempotencyKey: string) =>
    apiRequest<ActionResult>("POST", `/approvals/${enc(id)}/approve`, { body, idempotencyKey }),
  reject: (id: string, body: RejectRequest) => apiRequest<ActionResult>("POST", `/approvals/${enc(id)}/reject`, { body }),

  listAttention: (q: { reason?: AttentionReason | undefined; page?: number | undefined; page_size?: number | undefined }) =>
    apiRequest<EnrolmentPage>("GET", "/operations/attention", { query: q }),
  resolve: (id: string, body: ResolveRequest, idempotencyKey: string) =>
    apiRequest<ActionResult>("POST", `/operations/attention/${enc(id)}/resolve`, { body, idempotencyKey }),

  dashboard: () => apiRequest<Dashboard>("GET", "/dashboard"),
};

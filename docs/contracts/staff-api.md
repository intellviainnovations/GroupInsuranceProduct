# Contract: staff API (browser <-> backend)

- **Status:** Proposed (architect, 2026-10-18). Source of truth: [`staff-api.openapi.yaml`](staff-api.openapi.yaml) (OpenAPI 3.1, base path `/api/v1`). Replaces the `member-enrolment-api` placeholder.
- **Scope:** Phase 1 staff web app: sign-in, dashboard, new-sale wizard to certificate, approvals, enrolment list and detail, certificate download, cancellation request, needs-attention queue. Reports and admin come later.
- **Inputs:** `docs/specs/usgic-gpa-sale-flow.md`, `docs/design/data-model.md`, `bank-auth.md`, `cbs-customer-lookup.md`, `cbs-posting.md`. Backing stores: `docs/design/repositories.md`.

## Conventions
| Topic | Rule | Status |
|---|---|---|
| Session | Cookie `gip_session`: opaque 256-bit id, `HttpOnly; Secure; SameSite=Strict; Path=/api`, stored hashed (ADR-0002). Rotated at login, cleared at logout. `Secure` may be dropped only when `ENV=dev` on `localhost` | Proposed |
| CSRF | **Session-bound synchronizer token, stateless:** `csrf_token = base64url(HMAC-SHA256(session_secret, session_id))`, returned in the login/OTP result and `GET /me`. The SPA keeps it in memory (never storage) and sends `X-CSRF-Token` on every POST/PATCH; the server recomputes and compares in constant time. Login and OTP have no session yet: they require `Content-Type: application/json` (forces a CORS preflight, and no CORS is enabled) and an `Origin` in `APP_ALLOWED_ORIGINS` when the header is present. Same `Origin` check on every unsafe method. Needs a new secret `APP_SESSION_SECRET` (>= 32 bytes; random per start in memory mode) | Decided (product owner, 2026-10-18) |
| OTP challenge | `challenge_id` is our UUID; the bank's `challenge_ref` stays server-side, single use, 5 min expiry. Held in the memory store for now (Decided); the SQL table is a pending schema change | Proposed |
| Operations resolve | `RECHECK` by one OPERATIONS user (the state follows the insurer/CBS read-back only). `CONFIRM` (PAID or PAYMENT_FAILED) creates an `approval` (entity `ENROLMENT`, action `ATTENTION_RESOLVE`) that a **different** OPERATIONS user approves or rejects; the transition happens only on approval. ISSUED only via RECHECK (certificate data must come from the insurer) | Decided (two people, 2026-10-18); RECHECK single-user and ISSUED-via-RECHECK are Proposed |
| Errors | `{error, code, correlation_id, fields?}`. `error` is a generic message; `code` is a stable enum the UI maps to text; `fields[]` = `{field, code, message?}` with JSON paths, never submitted values. Extends the scaffold's `{error, correlation_id}` additively (`platform/errors.py`) | Proposed |
| Out-of-scope ids | Another branch's enrolment returns **404**, not 403 (no enumeration) | Proposed |
| Login failure | One generic 401 `LOGIN_FAILED` for wrong password, locked user, bad/expired OTP (bank-auth contract). Bank down: 503 `AUTH_UNAVAILABLE` | Decided by `bank-auth.md` |
| Money | Decimal string, two places, INR (`"118.00"`). Never a JSON number | Proposed |
| Time | Timestamps UTC ISO 8601; dates `YYYY-MM-DD`; list date filters are IST business dates | Proposed |
| Pagination | `page` (1-based), `page_size` (default 20, max 100); response `{items, page, page_size, total}` | Proposed |
| Optimistic locking | Every state-changing body carries the enrolment `version`; mismatch: 409 `VERSION_CONFLICT`, the UI reloads | Proposed |
| Idempotency | `Idempotency-Key` (UUID, one per user intent) **required** on `proposal`, `payment`, `policy`, `abandon`, `cancellation`, `approve`, `resolve`; optional on create/copy. Scope = user + operation + target id; kept 24 h. Same key + same body: replay (current resource, original status, `outcome.replayed=true`). Same key + different body: 422 `IDEMPOTENCY_KEY_REUSED`. Still running: 409 `IDEMPOTENCY_IN_PROGRESS`. This is in addition to `our_reference_no` / `cbs_request_ref`, which protect the external calls themselves | Proposed |
| Action results | Flow actions return 200 `ActionResult {enrolment, outcome}`: the insurer refusing, a queued retry or a move to `NEEDS_ATTENTION` are outcomes, not HTTP errors. 409 only when the action is not allowed in the current state or is blocked (`PREMIUM_MISMATCH`, `CONSENT_REQUIRED`, `ACCOUNT_NOT_ELIGIBLE`, `POSTING_UNRESOLVED`) | Proposed |
| UI rules | The server returns `allowed_actions` per enrolment and `can_decide` per approval; the UI shows only those buttons, the server re-checks everything. No business rule lives in the browser | Proposed |
| Personal data | Account numbers never return to the browser (masked + `account_key` keyed hash). CIF and CBS transaction ids are masked. Lookups are POST so identifiers stay out of URLs and logs | Proposed |
| Demo banner | `Me.environment.synthetic_data = true` whenever the memory backend or any fake adapter is active; the UI shows a permanent "Synthetic data" banner. Synthetic plan rates carry `synthetic: true` | Proposed |
| Production | `/docs` and `/openapi.json` stay off when `ENV` is not `dev` (scaffold) | Decided (scaffold) |

### Why separate flow actions instead of one "proceed"
Each step has different inputs (consent method and reference), different preconditions and refusals, different idempotency scopes, and different failure UX (insurer rejection vs CBS decline vs unknown). Separate endpoints keep each one auditable, testable from the spec's transition table, and safe to retry. The one deliberate chain: a successful `payment` continues to `issue_policy` and certificate fetch in the same request, because a customer debited must never wait for a click to get the policy; `policy` exists for retry.

## Endpoints and roles
`ANY_SESSION` includes a user with no role; `ANY_ROLE` needs at least one role. Branch-scoped roles see their own branch; `OPERATIONS` and `AUDITOR` see all branches (Proposed, Q32). Flow actions may be taken by any `BRANCH_USER` of the enrolment's branch, not only its maker (Assumption: shift handover, Q32); the actor is audited.

| Method | Path | Roles | Idem. |
|---|---|---|---|
| POST | `/auth/login` | public | |
| POST | `/auth/otp` | public | |
| POST | `/auth/logout` | ANY_SESSION | |
| GET | `/me` | ANY_SESSION | |
| GET | `/reference/codes` | ANY_ROLE | |
| GET | `/reference/plans` | ANY_ROLE | |
| POST | `/customers/lookup` | BRANCH_USER | |
| GET | `/enrolments` | BRANCH_USER, CHECKER, OPERATIONS, AUDITOR | |
| POST | `/enrolments` | BRANCH_USER | opt |
| GET | `/enrolments/{id}` | BRANCH_USER, CHECKER, OPERATIONS, AUDITOR | |
| PATCH | `/enrolments/{id}` | BRANCH_USER | |
| POST | `/enrolments/{id}/submit` | BRANCH_USER | |
| POST | `/enrolments/{id}/proposal` | BRANCH_USER | req |
| POST | `/enrolments/{id}/consent` | BRANCH_USER | |
| POST | `/enrolments/{id}/payment` | BRANCH_USER | req |
| POST | `/enrolments/{id}/policy` | BRANCH_USER, OPERATIONS | req |
| POST | `/enrolments/{id}/reopen` | BRANCH_USER | |
| POST | `/enrolments/{id}/abandon` | BRANCH_USER | req |
| POST | `/enrolments/{id}/copy` | BRANCH_USER | opt |
| GET | `/enrolments/{id}/certificate` | BRANCH_USER, CHECKER, OPERATIONS, AUDITOR | |
| POST | `/enrolments/{id}/cancellation` | BRANCH_USER | req |
| GET | `/approvals` | CHECKER, OPERATIONS, AUDITOR | |
| POST | `/approvals/{id}/approve` | CHECKER for `SUBMIT_SALE`/`CANCEL_CERTIFICATE`; OPERATIONS for `ATTENTION_RESOLVE`; never the requester | req |
| POST | `/approvals/{id}/reject` | same as approve | |
| GET | `/operations/attention` | OPERATIONS, AUDITOR | |
| POST | `/operations/attention/{id}/resolve` | OPERATIONS (`CONFIRM` creates an approval) | req |
| GET | `/dashboard` | ANY_ROLE | |

`/health` and `/ready` (scaffold) stay outside `/api/v1`, unauthenticated.

## Frontend types
**Generated, not hand-maintained (Decided, product owner, 2026-10-19).** `frontend/scripts/gen-api-types.mjs` (Node built-ins only, no generator dependency) reads `docs/contracts/staff-api.openapi.snapshot.json` (FastAPI's `app.openapi()`, dumped by the backend test suite) and writes `frontend/src/api/types.ts`, marked "generated, do not edit". `npm run gen:api` regenerates it. `npm run check:api` (run in CI) regenerates it in memory and fails if the committed file differs. UI-only aliases (for example `EnrolmentStatus` and `Role`, derived from the generated types) live in `frontend/src/api/model.ts`. `frontend/src/api/client.ts` is a thin `fetch` wrapper: cookie credentials, CSRF header, `Idempotency-Key`, `Error` parsing.

Order of truth: YAML (this contract) -> backend Pydantic schemas (tests assert the generated OpenAPI matches the YAML's schemas) -> snapshot -> `types.ts`.

## Open questions
Q26 (insurer cancel and refund), Q28 (consent mechanism; `CONSENT_METHOD` codes are synthetic placeholders), Q30 (who clears a premium mismatch), Q32 (roles, cross-branch scope, maker-checker per action), Q33 (editable CBS fields, selectable account statuses), Q36 (2026-10-18): CSRF secret, `ENV=demo`, two-person `CONFIRM` and memory-held OTP challenges are Decided; still open are the SQL challenge table (pending schema change) and a `NEEDS_ATTENTION -> CANCELLED` transition (not in the spec, left unchanged).

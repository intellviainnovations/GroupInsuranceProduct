# Architecture overview

- **Status:** Proposed, follows ADR-0001 (Accepted) and ADR-0002 (Proposed). Owner: architect.
- **Scope:** Phase 1: one insurer (USGIC Group Personal Accident), one bank (D-022, D-020).

## Context
```
 Bank staff browser (React, later React Native)
        │ HTTPS (bank reverse proxy / WAF / TLS)
        ▼
 ┌──────────────── our application (FastAPI, modular monolith) ────────────────┐
 │ API layer → application services → domain (states, rules)                   │
 │                    │                                                        │
 │ ports: BankAuth · Insurer · CustomerDirectory · CbsPosting · Clock · Cipher │
 │                    │                                                        │
 │ PostgreSQL ◄── persistence      worker (jobs, retries, reconciliation)      │
 └───────┬──────────────┬──────────────────────┬───────────────────────────────┘
         ▼              ▼                      ▼
  Bank AD/CHRISS    Bank CBS             USGIC Banca API
  auth API          report server DB     (proposal, policy,
                    (customer read-only) COI, cancel, endorse)
                    + CBS transaction
                    path (debit + pool
                    credit only)
```
The application owns the whole sale process, moved out of the CBS (Finacle) menus. The CBS appears twice: a **read-only customer directory** on the report server, and a **transaction path** used only to debit the customer and credit the pool account (D-031). External systems are reached only through ports, so each can be replaced by a fake (development, CI) or by another insurer or bank (D-020).

## Backend layout (`src/backend/`)
| Package | Contents | Depends on |
|---|---|---|
| `api/` | FastAPI routers, request/response schemas, authentication and permission dependencies, error mapping | `services` |
| `services/` | Use cases: sale, approval, cancellation, endorsement, reconciliation, reporting, user and role admin | `domain`, ports |
| `domain/` | Enrolment state machine, validation rules, money types, value objects | nothing external |
| `adapters/insurer/` | Port, `usgic/`, `fake/` | `platform` |
| `adapters/bank_auth/` | Port, `esb/`, `fake/` | `platform` |
| `adapters/cbs/customer_directory/` | Read-only port (`find_customer`, `get_account`, `get_branch`), `fake/`; real adapter when Q33 is answered | `platform` |
| `adapters/cbs/posting/` | Transaction port (`post_premium`, `post_refund`, `get_posting_status`, `get_pool_statement`), `fake/`; real adapter when the Q27 spec arrives | `platform` |
| `persistence/` | SQLAlchemy models, repositories, unit of work | `domain` |
| `platform/` | Configuration, secrets, crypto, logging, audit, job runner, clock, request context | stdlib and approved libraries |
Dependency rule: `domain` imports nothing from the other packages; adapters never import `services`. Migrations live in `migrations/` (Alembic).

## Frontend (`frontend/`)
React with TypeScript, built by Vite to static files. Screens for Phase 1: sign-in, new sale (account or CIF lookup, then insured, nominees, plan), approvals queue, enrolment list and detail, certificate download, in-process and needs-attention queue, cancellation and endorsement requests, reports, admin (users, roles, rates, reference data). The API client and types are generated from the backend's OpenAPI contract. No secrets or business rules live in the browser; every rule is enforced by the server.

## Main flows
1. **Sign in:** browser → our API → bank auth port → session row → opaque cookie (contract `bank-auth.md`).
2. **Sale:** the maker keys an account or CIF number, the customer directory returns the customer and accounts (what the Finacle menu does today), the maker completes the rest. See the state machine in `docs/specs/usgic-gpa-sale-flow.md`. Steps that call the insurer or the CBS are executed by the service layer with a persisted state before and after each call; retries go through the `job` table.
3. **Reconciliation:** a scheduled job compares CBS pool-account entries, our `cbs_posting` rows and issued certificates and writes `reconciliation_item` rows for exceptions.

## Cross-cutting design
| Concern | Design |
|---|---|
| Consistency | Each external call is wrapped: persist intent → call → persist result. An unknown outcome is resolved by a read-back call, never by repeating a money-moving call |
| Authorisation | Deny by default; every endpoint declares required roles; branch scoping is applied in the query layer from the session |
| Audit | Append-only, hash-chained `audit_event` (ADR-0002) |
| Configuration | Environment and a protected config file; per-bank values (branch map, pool account, reference mappings, rates) are data or configuration, not code (D-020) |
| Errors | Generic messages to clients with a correlation id; details only in protected logs |
| Observability | Structured logs without personal data, health and readiness endpoints, a support-bundle command (D-007) |
| Production hardening | Interactive API docs and schema endpoints off, no server or version headers, security headers, request throttling |
| Time | UTC in storage, IST in the UI; one date-parsing module for insurer formats |

## Deployment
Signed bundle containing the backend (pinned wheels for offline install), prebuilt frontend assets, Alembic migrations, configuration templates, runbook and release notes (D-007). TLS termination, reverse proxy and WAF are the bank's (Q20). Network paths from the bank environment to the insurer's production gateway, to the CBS transaction path and to the CBS report-server database are bank-arranged (Q26, Q27, Q33). The report-server account is read-only.

## Mapping to the clearance matrix (owner: security-reviewer)
Authentication and sessions C-01 to C-09 are designed in `bank-auth.md`; access control C-10 to C-14 in the layout and cross-cutting table above; input and business-logic controls C-15 to C-22 in the spec and data model; transport and header controls C-23 to C-28 in hardening and the bank's proxy; data protection C-29 to C-31 in ADR-0002; logging C-32 and C-33 in the audit design. Statuses stay `Not started` until evidence exists.

## First build tasks (hand to the orchestrator)
None of these needs an insurance rule; they use fakes only.
1. **Scaffold:** backend package, configuration, logging, request context, health endpoint, CI jobs (lint, type check, tests, dependency and secret scan), frontend project with a sign-in page placeholder. Dependencies only from ADR-0001's baseline list.
2. **Persistence:** SQLAlchemy models and the first Alembic migration from `docs/design/data-model.md` (human approves the migration), seed data for roles, reference codes and the USGIC product, plans and a synthetic rate set.
3. **Auth:** `AuthProvider` port, fake provider, session handling, user and role tables, login endpoint, permission dependencies, audit writer.
4. **Adapters:** insurer port with the scriptable fake; CBS customer-directory and posting ports with fakes; bank-auth ESB provider written against the contract (tested with the cipher's own round-trip until the bank's test vectors arrive).
5. **Sale flow:** domain state machine, services, job runner, endpoints, in that order; QA writes tests from `docs/specs/usgic-gpa-sale-flow.md` first.
6. **Frontend:** sign-in, new sale, queues, certificate download against the generated client.
7. **Reviewer:** threat model for the sale flow, then matrix evidence as features land.
8. **Release agent (to be added):** bundle, signing and offline dependency packaging.

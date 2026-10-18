# ADR-0001: Technology stack and deployment packaging

- **Status:** Accepted (product owner, 2026-10-18). Remaining bank-side confirmations are listed at the end and do not block the build.
- **Date:** 2026-10-18 (first drafted 2026-10-16)
- **Deciders:** product owner, tech lead

## Context
- Web app for bank employees; a mobile app (Android and iOS) comes later, so the backend is API-first (D-001, D-006).
- Deployed on the bank's on-prem servers or private cloud; no remote access for the startup; the bank installs signed bundles (D-004, D-007).
- First deliverable is a go-live product for one insurer (USGIC, Group Personal Accident), more insurers later behind one adapter interface (D-022).
- Our application owns every sale; the bank's core banking system (CBS) is called only to debit the customer and credit the pool account (D-023).
- Development happens outside the bank network, so the dev and CI database cannot be the bank's (D-008).
- The pilot bank's own database is reported to be Oracle 19c (product owner, 2026-10-18). Other banks may differ (D-020, Q16).
- Bank infosec reviews the stack; dependencies must be few, mainstream, pinned and patchable (clearance matrix).

## Options considered
| Dimension | Chosen | Main alternative and why not |
|---|---|---|
| Backend | Python + FastAPI | Java/Spring or .NET: heavier to install and package offline; no team advantage |
| Database | PostgreSQL | Oracle 19c as primary: cannot be used in development outside the bank; kept as a portability target instead |
| Frontend | React + TypeScript, built to static files | Server-rendered pages: simpler, but the mobile plan favours a client built on the same API and shared TypeScript |
| Mobile (later) | React Native (Proposed) | Native Swift/Kotlin: two code bases; PWA: weaker device features |
| Sessions | Server-side, in the database | Redis: one more component to install, patch and clear with the bank; no measured need |
| Identity | Bank AD/CHRISS authentication API behind our own `AuthProvider` interface | Local accounts: duplicates the bank's identity and password policy |

## Decision (Decided unless stated)
| Area | Choice |
|---|---|
| Language/runtime | Python 3.12 (any 3.12 patch; bank accepts any Python version, product owner 2026-10-18) |
| Backend framework | FastAPI with Pydantic v2, run by an ASGI server (uvicorn) behind the bank's reverse proxy / TLS termination |
| Architecture | Modular monolith (D-006) with a ports-and-adapters layout: domain, application services, and adapters for insurer, bank auth, CBS |
| Database | PostgreSQL (a currently supported major version) for development, CI and the first release |
| Data access | SQLAlchemy 2.x and Alembic migrations, parameterised queries only |
| Portability | **Proposed:** keep schema and queries in a portable SQL subset so Oracle 19c, MSSQL or MySQL can be added later (rules in ADR-0002). Not a delivery commitment |
| Outbound HTTP | `httpx` |
| Cryptography | `cryptography` library only; no hand-written crypto |
| Frontend | React with TypeScript, built with Vite to static files served by the reverse proxy; no Node runtime on bank hosts |
| Mobile (later) | **Proposed:** React Native, sharing TypeScript types and the API client generated from our OpenAPI contract |
| Authentication | Bank AD/CHRISS API through an `AuthProvider` interface; further providers (other banks' domain/LDAP/OIDC) can be added without changing callers. Contract: `docs/contracts/bank-auth.md` |
| Sessions | Server-side session rows in the database, opaque random cookie for web; bearer token for mobile later. **Proposed** detail in ADR-0002 |
| Middleware | None to start: no Redis, no broker. An in-process worker plus a database job table covers retries and reconciliation (Q20) |
| Packaging | Signed release bundle with pinned, offline-installable Python wheels and prebuilt frontend assets. Container vs VM image is the bank's choice (Q21) |
| Tests | `pytest` for the backend, a fake adapter for each external system, contract tests from `docs/contracts` |

### Approved baseline dependencies
Approved by accepting this ADR. Any other dependency needs a human's approval (CLAUDE.md).
- Backend: `fastapi`, `uvicorn`, `pydantic`, `sqlalchemy`, `alembic`, `psycopg` (v3), `httpx`, `cryptography`; dev only: `pytest`, `ruff`, `mypy`, `pip-audit`.
- Frontend: `react`, `react-dom`, `react-router`, `typescript`, `vite`; dev only: `vitest`, `eslint`.

### Repository layout (target)
`src/backend/` Python package; `frontend/` React source (not released, only its build output); `migrations/` Alembic; `config-templates/`; `tests/`. See `docs/design/architecture.md`.

## Consequences
- Development, CI and demos need no bank access. Bank-internal APIs (auth, CBS) are exercised through fakes until the code runs in bank UAT.
- The Oracle 19c reality at the pilot bank is a risk to manage: ADR-0002 rules (portable types, normalised empty strings, no database-specific features) keep a later port cheap, and a second-database test run must pass before any port is promised (Q16).
- No Redis means sessions, jobs and rate limits live in the database; revisit only with measured need.
- React Native shares logic with the web app but not screens; mobile is a separate later project.

## Confirmations still needed (non-blocking)
- Bank hosting: operating system, container platform, reverse proxy / WAF owner (Q8, Q20, Q21).
- **Production database at the pilot bank:** will the bank install and support PostgreSQL, or must production run on its Oracle 19c? If Oracle, the portability work in ADR-0002 becomes a delivery task, not an option (Q16).
- Python 3.12 availability on the bank's hosts.
- Bank infosec acceptance of the open-source dependency list above.

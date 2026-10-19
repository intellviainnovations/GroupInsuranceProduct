# Context pack: backend (one page; read this first, then only what the handoff names)

**Product:** staff web app for selling USGIC Group Personal Accident through a bank (D-022, D-031). Python 3.12, FastAPI, Pydantic v2 (ADR-0001). Modular monolith, ports and adapters.

## Where things are (`src/backend/`)
| Path | Contents |
|---|---|
| `api/app.py`, `api/middleware.py`, `api/errors.py` | App factory, security headers, throttle, request context, generic errors |
| `api/v1/routes.py`, `schemas.py`, `deps.py`, `views.py` | `/api/v1` routers, request/response schemas, auth/CSRF/role dependencies |
| `services/` | Use cases: `auth`, `sale`, `enrolments`, `approvals`, `views`, `platform_services` (audit, idempotency, jobs) |
| `domain/states.py`, `model.py`, `repositories.py` | Enrolment state machine (spec transitions only), records, repository ports |
| `persistence/memory/`, `persistence/seed/synthetic_v1.json` | In-memory store and synthetic seed; `persistence/sql/` is T-002 |
| `adapters/insurer/` (`fake/`, `usgic/`), `adapters/bank_auth/`, `adapters/cbs/` | External systems behind ports; fakes have failure triggers |
| `bootstrap.py`, `platform/config.py` | Wiring and settings: `ENV`, `APP_DATA_BACKEND`, `APP_INSURER_ADAPTER`, `APP_SESSION_SECRET`, `APP_ALLOWED_ORIGINS` |

## Sources of truth
- HTTP API: `docs/contracts/staff-api.openapi.yaml` (+ `staff-api.md`). Snapshot: `docs/contracts/staff-api.openapi.snapshot.json`.
- Flow and states: `docs/specs/usgic-gpa-sale-flow.md`. Data: `docs/design/data-model.md`, `docs/design/repositories.md`. Rules: ADR-0002.

## Must always hold
Deny by default; branch from the session; maker ≠ checker; two-person operations CONFIRM (D-036); `Idempotency-Key` on money and insurer actions; CSRF on state changes (D-035); persist intent → call → persist result, never re-post a debit on an unknown outcome; no personal data, tokens or account numbers in logs; fakes only in `ENV=dev|demo` (D-034); no new dependencies without approval; never invent insurance rules.

## Checks
`ruff check src tests`, `ruff format --check src tests`, `mypy`, `pytest` (6 known `check_repo.sh` failures by design), `bash scripts/check_repo.sh`.

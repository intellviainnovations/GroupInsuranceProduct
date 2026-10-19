# Context pack: staff API (one page; read this first, then only what the handoff names)

**Contract:** `docs/contracts/staff-api.openapi.yaml` (OpenAPI 3.1, source of truth) and `docs/contracts/staff-api.md` (conventions and roles table). The backend's generated snapshot is `docs/contracts/staff-api.openapi.snapshot.json`; the frontend's `frontend/src/api/types.ts` is generated from it and CI fails on drift (`npm run check:api`).

## Conventions (summary; details in `staff-api.md`)
| Topic | Rule |
|---|---|
| Base path | `/api/v1`; breaking changes need a version note or a compatible path (bank installs cannot be hot-patched) |
| Auth | Opaque HttpOnly session cookie; bearer token for mobile later |
| CSRF | `X-CSRF-Token` on every state change; Origin check on login and OTP (D-035) |
| Idempotency | `Idempotency-Key` on money and insurer actions |
| Ids and values | UUIDs; money as decimal strings; ISO dates; account numbers never returned in full |
| Errors | `{error, code, correlation_id, fields[]}`; 409 for wrong state or a block; other branch's records return 404 |
| Flow results | 200 with `{enrolment, outcome}`; insurer rejection, queued retry, needs-attention are outcomes |
| Roles | Deny by default; roles per operation in `staff-api.md`; maker ≠ checker; two-person operations CONFIRM (D-036) |
| Lists | Pagination and filters as defined in the contract |

## Code
Routers and schemas in `src/backend/api/v1/`; services in `src/backend/services/`. Contract tests in `tests/test_demo_config_and_contract.py`.

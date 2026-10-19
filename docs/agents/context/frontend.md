# Context pack: frontend (one page; read this first, then only what the handoff names)

**Product:** "Group Insurance Desk", a staff web app for bank branch employees selling USGIC Group Personal Accident. React + TypeScript 6.0 + Tailwind CSS v4, built by Vite to static files (ADR-0001, Amendments 1 and 2).

## Where things are (`frontend/`)
| Path | Contents |
|---|---|
| `src/api/types.ts` | **Generated** from the OpenAPI snapshot (`npm run gen:api`); never edit by hand |
| `src/api/model.ts`, `client.ts`, `endpoints.ts`, `reference.ts` | UI aliases, fetch client (CSRF header, `Idempotency-Key`), endpoint functions, reference-data cache |
| `src/auth/AuthContext.tsx` | Session (`/me`), sign-in, sign-out |
| `src/layout/AppLayout.tsx` | Sidebar by role, top bar |
| `src/pages/` | SignIn, Dashboard, EnrolmentList, EnrolmentDetail, NewSale, Approvals, Attention, DecisionDialog, NotFound |
| `src/ui/` | Shared components, icons (inline SVG), toasts, formatting, `useAction` |
| `src/strings.ts` | All user-facing text |
| `README.md` | How to run with the demo backend, demo logins, failure triggers |

## Design inputs
`docs/design/design-brief.md` (character, inspiration, budget), `docs/design/design-system.md` (tokens and components, ui-designer), `docs/design/ux/<screen>.md` (flows and states, ux-designer). Build from these; do not make design decisions in code.

## Must always hold
No business rules in the browser: actions from `allowed_actions` / `can_decide`, amounts exactly as returned. No tokens or personal data in local storage or URLs. Escape all output (no raw HTML). Generic errors with the correlation id. Clear form state on sign-out. No new dependencies without approval. Synthetic data only.

## Checks
`npm run typecheck`, `npm run lint`, `npm run check:api`, `npm run test`, `npm run build`, then `bash scripts/check_repo.sh` from the repo root.

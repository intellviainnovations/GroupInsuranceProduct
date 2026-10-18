# Frontend (staff web app): Group Insurance Desk

React + TypeScript, built by Vite to static files (no Node runtime on bank hosts). Dependencies: the ADR-0001 baseline (`react`, `react-dom`, `react-router`, `typescript`, `vite`, `vitest`, `eslint`) plus Amendment 1 (`tailwindcss`, `@tailwindcss/vite`, `@types/react`, `@types/react-dom`). All versions are pinned exactly; `package-lock.json` is committed.

Screens: sign-in (with OTP step), dashboard, enrolment list and detail (with flow actions), new-sale wizard, approvals, needs-attention queue. Buttons come only from the server's `allowed_actions` / `can_decide`; amounts are shown exactly as the API returns them (formatted as INR for display only).

## Run backend + frontend together (Windows PowerShell)
Terminal 1, backend (from the repo root, venv already set up as in the root `README.md`):
```powershell
.venv\Scripts\Activate.ps1
$env:ENV = "demo"
$env:APP_SESSION_SECRET = "demo-session-secret-0123456789abcdef"
$env:APP_ALLOWED_ORIGINS = "http://localhost:5173"
uvicorn --factory backend.api.app:create_app --no-server-header --app-dir src --workers 1 --host 127.0.0.1 --port 8000
```
`APP_ALLOWED_ORIGINS` is required: the backend rejects login and every POST/PATCH whose `Origin` is not on the list.

Terminal 2, frontend:
```powershell
cd frontend
npm ci
npm run dev
```
Open http://localhost:5173 (use `localhost`, not `127.0.0.1`). The Vite dev server proxies `/api` to `http://127.0.0.1:8000`, so the browser sees one origin, with no CORS. The session cookie is `Secure`, and browsers accept it on `http://localhost`. The demo data lives in memory, so restarting the backend resets it.

## Demo logins
Password for every user: `Synthetic#Demo2026`. It is synthetic and is accepted only by the fake bank-auth provider (`src/backend/persistence/seed/synthetic_v1.json`, `fake_password`).

| Branch | Roll no | Role | Use it to |
|---|---|---|---|
| 0101 | D1001 | Branch user (maker) | New sale, proposal, consent, payment |
| 0101 | D1002 | Checker | Approve or reject 0101 sales |
| 0102 | D1003 | Branch user + checker | See "cannot decide" on your own sale |
| 0102 | D1009 | Branch user | Maker for branch 0102 |
| 0900 | D1004 | Operations | Needs-attention: RECHECK / CONFIRM |
| 0900 | D1008 | Operations | Second person who approves D1004's CONFIRM |
| 0900 | D1005 | Auditor | Read-only, all branches |
| 0102 | D1007 | No role | "No access" page |
| 0101 | D9001 | Branch user, needs OTP | OTP `123456` is valid; any other OTP fails |
| any | D9002 | Locked | Generic sign-in failure |
| any | D9003 | Bank auth down | "Sign-in service unavailable" |

## Customer lookups and failure triggers (new sale)
| Enter | Shows |
|---|---|
| CIF `SYN0001` / account `509900011001` | Happy path through to certificate |
| CIF `SYN0002` | Several accounts; a dormant one cannot be selected |
| CIF `SYN0003` | Only a closed account; nothing can be selected |
| CIF `SYN0009` | Some fields missing in CBS; the maker fills them in |
| Any account ending `0000`, or an unknown CIF | Customer not found |
| Account `509999999901` / CIF `SYN9901` (or `...902` / `SYN9902`) | CBS unavailable |

The last four digits of the **debit account** pick what the fake insurer or CBS does:
- `6001`: the insurer rejects the proposal.
- `6003`: premium mismatch, so payment is blocked.
- `6004`: queued for retry.
- `6005`: issue retries run out, then NEEDS_ATTENTION.
- `7001`: CBS declines the debit (PAYMENT_FAILED).
- `7002`: posting outcome unknown, then resolves.
- `7003`: posting unknown and unresolved (NEEDS_ATTENTION).
- `7004`: account frozen (not eligible).

The accounts for these codes are listed in `docs/design/repositories.md` section 5 (for example CIF `SYN0004` = `...7001`, `SYN0007` = `...6001` / `...7004`, `SYN0008` = `...6003` / `...6005`).

## Commands (run from `frontend/`)
| Task | Command |
|---|---|
| Install exactly from the lockfile | `npm ci` |
| Dev server (with `/api` proxy) | `npm run dev` |
| Lint + security scan | `npm run lint` |
| Type check | `npm run typecheck` |
| Tests | `npm run test` |
| Production build (output in `dist/`) | `npm run build` |

## Notes
- Code layout:
  - `src/api/`: hand-maintained `types.ts` matching the OpenAPI contract, plus `client.ts`, a fetch wrapper that sends the cookie, `X-CSRF-Token` from login or `/me` (kept in memory only) and a `crypto.randomUUID()` `Idempotency-Key` per user intent.
  - `src/auth/`: the session context.
  - `src/ui/`: components, icons and toasts.
  - `src/pages/`: the screens.
- Signing out, or the session expiring, remounts every screen and clears the reference-data cache, so no form state survives.
- All user-visible text is in `src/strings.ts` (localisation later, Q17).
- The production build has source maps off, no inline scripts and no `data:` assets (strict CSP). Serve `dist/` at the site root, behind the same origin as `/api`.
- `scripts/check-security.mjs` (part of `npm run lint`) fails on `dangerouslySetInnerHTML`, `innerHTML =`, browser storage APIs, `eval` and inline scripts.
- **Known gap:** `typescript-eslint` (approved) is not installed. Its current release (8.71.2) needs `typescript < 6.1`, but the baseline pins TypeScript 7.0.2, which ships no JavaScript compiler API. ESLint therefore still covers only the `.js`/`.mjs` files. TypeScript is checked by `npm run typecheck` and the security scan.

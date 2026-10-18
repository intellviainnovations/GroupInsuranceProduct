# Frontend (staff web app)

React + TypeScript, built by Vite to static files (no Node runtime on bank hosts). Only the ADR-0001 baseline dependencies are used: `react`, `react-dom`, `react-router`, `typescript`, `vite`; dev only `vitest`, `eslint`. All versions are pinned exactly in `package.json`; `package-lock.json` is committed.

Current state: scaffold only. `/sign-in` is a placeholder form (branch code, roll number, password; autocomplete off) with no submit logic and no network calls; unknown paths show a 404 page. No business rules live in the browser.

## Commands (run from `frontend/`)
| Task | Command |
|---|---|
| Install exactly from the lockfile | `npm ci` |
| Dev server | `npm run dev` |
| Lint | `npm run lint` |
| Type check | `npm run typecheck` |
| Tests | `npm run test` |
| Production build (output in `dist/`) | `npm run build` |

CI runs `npm ci`, then `lint`, `typecheck`, `test`, `build`.

## Notes
- All user-visible text is in `src/strings.ts` (localisation later, Q17). Components must not contain literal visible text.
- The production build has source maps off, no inline scripts and no `data:` asset inlining, so the bank proxy can apply a strict CSP. Assets are referenced from `/assets/`, so serve `dist/` at the site root.
- No secrets or tokens in code or browser storage; the session will be an HttpOnly cookie set by the backend. `npm run lint` also runs `scripts/check-security.mjs`, which fails on `dangerouslySetInnerHTML`, `innerHTML =`, `localStorage`/`sessionStorage`, `eval` and inline scripts in `index.html`.
- The API client and types will be generated from the backend OpenAPI contract later; do not hand-write request shapes that the contract defines.
- Known gaps (waiting for human approval of extra dev dependencies): `src/vendor-types.d.ts` is a temporary stand-in for `@types/react`, and ESLint currently covers only the plain JavaScript files because it cannot parse TypeScript without `typescript-eslint`.

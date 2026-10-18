# GroupInsuranceProduct

Bancassurance web application for bank employees to sell insurance partners' products. Group policies first (personal accident, health without pre-medical checks; the SHG-linked hospital-cash product is deferred), retail policies and mobile later. Deployed on the bank's on-prem or private-cloud infrastructure.

**Status:** build-ready design. Stack accepted (`docs/adr/0001-technology-stack.md`); first product is USGIC Group Personal Accident. A runnable scaffold exists: a FastAPI backend (app factory, typed configuration, JSON logging with redaction, security headers, request throttling, `/health` and `/ready`) and a React sign-in placeholder, both with CI. There are no business features yet: no authentication, persistence, CBS or insurer adapters, and no sale flow.

## Repository map
| Path | Purpose |
|---|---|
| `CLAUDE.md` | Rules and pointers for every Claude session |
| `docs/specs/` | Requirements, domain rules, acceptance criteria |
| `docs/adr/` | Architecture decision records |
| `docs/design/` | Architecture overview and the logical data model |
| `docs/contracts/` | Interface definitions (insurer adapter, APIs) |
| `docs/security/` | Bank security-clearance control matrix and review evidence |
| `docs/templates/` | Task handoff and result templates |
| `docs/agents/` | Playbook for the main-session orchestrator |
| `.claude/agents/` | Subagent definitions |
| `release/allowlist.txt` | The only paths that may enter a release bundle |
| `scripts/check_repo.sh` | Repo hygiene check (also run in CI) |

Project background, decisions and open questions: `intellviainnovations/GroupInsuranceProduct-Project-Knowledge`.

## Developing
Backend (Python 3.12 for CI and release; any 3.12 or newer works locally). From the repo root:
```bash
python -m venv .venv && . .venv/bin/activate        # Windows: .venv\Scripts\activate
python -m pip install -r requirements/dev.txt        # exact pinned versions
ENV=dev uvicorn --factory backend.api.app:create_app --no-server-header --app-dir src --reload
# then: curl http://127.0.0.1:8000/health   (interactive docs at /docs in dev mode only)
ruff check src tests && ruff format --check src tests && mypy && pytest
bash scripts/check_repo.sh                           # hygiene and secret scan
```
Any `ENV` other than `dev` (including unset) is production mode: docs and schema endpoints are off, `APP_DATABASE_URL` is required, and startup fails with a clear message if it is missing. Always start uvicorn with `--no-server-header`. Settings come from environment variables and an optional protected TOML file (`APP_CONFIG_FILE`); see `config-templates/`. Frontend (Node 22, see `frontend/.nvmrc`): see `frontend/README.md`.

## Licence
Proprietary. © 2026 Intellvia Innovations LLP. All rights reserved. See `LICENSE`.

## Not in this repo
Secrets, real customer or member data, bank-confidential documents, signing keys.

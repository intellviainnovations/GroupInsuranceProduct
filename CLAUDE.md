# CLAUDE.md – GroupInsuranceProduct

Bancassurance web app used by bank employees to sell insurers' products (group policies first, retail later). Deployed on the bank's on-prem/private cloud; the startup has no remote access to it. Mobile later.

**Background, decisions, open questions live in the knowledge repo:**
`intellviainnovations/GroupInsuranceProduct-Project-Knowledge` (start at its `README.md`). Check its `docs/decisions.md` and `docs/open-questions.md` before proposing design changes. Do not re-open **Decided** items.

## Status
Build-ready. Stack is **Accepted** in `docs/adr/0001-technology-stack.md` (Python 3.12 + FastAPI, PostgreSQL, React + TypeScript, bank AD/CHRISS authentication behind an `AuthProvider` port). Only the baseline dependencies in that ADR are approved; anything else needs a human's approval.

**First product:** USGIC Group Personal Accident (knowledge repo D-022). The application owns the whole sale process, moved out of the bank's CBS (Finacle) menus (knowledge repo D-031): customer and account details are **read** from the CBS report-server database, and the CBS **transaction path** is used only to debit the customer and credit the pool account.

**Where to start a build session:** `docs/design/architecture.md` ("First build tasks"), then `docs/specs/usgic-gpa-sale-flow.md`, `docs/design/data-model.md`, and the contracts in `docs/contracts/`. The sale-flow spec is **Draft**: build the flow, states and failure handling, but never invent insurance rules (listed in the spec as needed from a domain expert).

**Dev has no bank access:** develop and test against the fakes in each adapter package; real bank and insurer calls are exercised only in the bank's or insurer's UAT. Insurer and bank source documents are never stored in this repo.

## Working rules
- Read only what the task needs. Specs: `docs/specs`. Interfaces: `docs/contracts`. Decisions: `docs/adr`.
- Use `docs/templates/task-handoff.md` for every assignment and `task-result.md` for every result.
- **Builder never verifies own work.** QA writes tests from the spec; a separate reviewer checks the PR.
- **Contracts before parallel work.** Define the interface (e.g. insurer adapter) in `docs/contracts` first.
- **Stop and ask a human** on: insurance rules that are ambiguous, any premium/payout/eligibility calculation, security-sensitive choices, schema changes, new dependencies, conflicting specs.
- Synthetic data only. Never real member/customer data, credentials, keys or bank-confidential documents in this repo.
- Work on a branch; never push to `main`. Do not open a PR unless asked. Humans merge to release and hold signing keys.
- Run `scripts/check_repo.sh` before pushing.

## Release
Deliverables are signed bundles built from `release/allowlist.txt`. UAT/production never clone this repo. See the knowledge repo `docs/delivery-and-operations.md`.

## Agents
- Main-session playbook: `docs/agents/orchestrator.md` (subagents cannot spawn subagents, so the orchestrator runs as the main session).
- Subagents: `.claude/agents/` (architect, qa, backend, frontend, reviewer). A release agent is added when bundling starts.
- Bank security clearance: follow `docs/security/clearance-matrix.md` (owner: reviewer). Controls need evidence; the bank's original checklist workbook is not stored in this repo.

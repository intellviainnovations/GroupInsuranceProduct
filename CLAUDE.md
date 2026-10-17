# CLAUDE.md – GroupInsuranceProduct

Bancassurance web app used by bank employees to sell insurers' products (group policies first, retail later). Deployed on the bank's on-prem/private cloud; the startup has no remote access to it. Mobile later.

**Background, decisions, open questions live in the knowledge repo:**
`intellviainnovations/GroupInsuranceProduct-Project-Knowledge` (start at its `README.md`). Check its `docs/decisions.md` and `docs/open-questions.md` before proposing design changes. Do not re-open **Decided** items.

## Status
Pre-build. Technology stack is **not chosen** – it is settled in `docs/adr/0001-technology-stack.md`. Do not add application code or dependencies until that ADR is Accepted.

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
- Subagents: `.claude/agents/` (architect, qa, backend, reviewer). More are added as the build starts (adapter, frontend, release).
- Bank security clearance: follow `docs/security/clearance-matrix.md` (owner: reviewer). Controls need evidence; the bank's original checklist workbook is not stored in this repo.

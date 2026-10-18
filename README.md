# GroupInsuranceProduct

Bancassurance web application for bank employees to sell insurance partners' products. Group policies first (personal accident, health without pre-medical checks; the SHG-linked hospital-cash product is deferred), retail policies and mobile later. Deployed on the bank's on-prem or private-cloud infrastructure.

**Status:** build-ready design. Stack accepted (`docs/adr/0001-technology-stack.md`); first product is USGIC Group Personal Accident. No application code yet.

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

## Licence
Proprietary. © 2026 Intellvia Innovations LLP. All rights reserved. See `LICENSE`.

## Not in this repo
Secrets, real customer or member data, bank-confidential documents, signing keys.

# GroupInsuranceProduct

Bancassurance web application for bank employees to sell insurance partners' products. Group policies first (personal accident, health without pre-medical checks, SHG-linked hospital cash), retail policies and mobile later. Deployed on the bank's on-prem or private-cloud infrastructure.

**Status:** pre-build scaffold. Technology stack not yet chosen (see `docs/adr/0001-technology-stack.md`).

## Repository map
| Path | Purpose |
|---|---|
| `CLAUDE.md` | Rules and pointers for every Claude session |
| `docs/specs/` | Requirements, domain rules, acceptance criteria |
| `docs/adr/` | Architecture decision records |
| `docs/contracts/` | Interface definitions (insurer adapter, APIs) |
| `docs/templates/` | Task handoff and result templates |
| `docs/agents/` | Playbook for the main-session orchestrator |
| `.claude/agents/` | Subagent definitions |
| `release/allowlist.txt` | The only paths that may enter a release bundle |
| `scripts/check_repo.sh` | Repo hygiene check (also run in CI) |

Project background, decisions and open questions: `intellviainnovations/GroupInsuranceProduct-Project-Knowledge`.

## Not in this repo
Secrets, real customer or member data, bank-confidential documents, signing keys.

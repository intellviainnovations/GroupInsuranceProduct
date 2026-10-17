# ADR-0001: Technology stack and deployment packaging

- **Status:** Proposed (not decided – awaiting product owner and bank hosting standards)
- **Date:** 2026-10-16
- **Deciders:** product owner, tech lead

## Context
- Web app for bank employees; mobile later, so the backend should be API-first.
- Deployed on the bank's on-prem servers or private cloud; no remote access for the startup; installs and upgrades are done by the bank from signed bundles.
- Modest scale assumed (sizing target deferred, D-014/Q2), 8 insurer integrations, single group product first.
- Bank infosec review will assess the stack (dependencies, patching, hardening).
- Unknowns: bank's approved OS/database/container platform and middleware (Q8), SSO and core-banking integration (Q9).

## Options to evaluate
| Dimension | Candidates / questions |
|---|---|
| Backend language/framework | Choose from what the team can maintain and the bank's security team accepts. |
| Database | A mainstream relational database already approved or supported by the bank. |
| Frontend | A mainstream SPA or server-rendered framework; no exotic build chains. |
| Packaging | Container images vs VM image vs native installer, depending on what the bank can run offline. |
| Identity | Bank SSO protocol in use (to confirm). |

## Decision
_Pending._ Gather Q8/Q9 answers first, then record the choice, rationale and rejected options here.

## Consequences
_To be completed._

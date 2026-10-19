# Security clearance matrix

Working tracker for the bank's Application Security Clearance Checklist (v3.0, Jan 2025; a newer version may exist, see knowledge-repo Q15). **Owner of this file: security-reviewer agent.** The bank's original workbook is not stored in this repo; item numbers below point into it (`W` = Web sheet, `A` = API sheet). Mobile rows are added when mobile starts (D-001).

## How to use
- The bank wants a YES / NO / NA answer **with evidence** per control (code snippet, config screenshot, scan output). NA needs a written justification. A control we cannot meet needs a risk acceptance signed by the business head. Clearance is given only after controls are implemented.
- **Status:** `Not started` / `Designed` / `Built` / `Evidenced` (YES, evidence path filled) / `NA` (reason + bank acceptance) / `Gap` (needs risk acceptance).
- Update a row only with evidence you have seen. Evidence is a path or link, never pasted secrets or real data.
- Web rows (`W`) apply to any browser-facing tier we deliver; API rows (`A`) apply to the backend. Frontend stack is not chosen yet, so W rows stay `Not started` until it is.
- Owner: **be** backend, **fe** frontend, **arch** architect, **rev** security-reviewer, **hum** human (us), **bank** bank-side.

## Controls (merged where Web and API overlap)
All rows start as `Not started`. Evidence column is filled as work lands.

### Authentication and sessions (depends on bank SSO, Q9)
| ID | Control | Refs | Owner | Evidence | Status |
|---|---|---|---|---|---|
| C-01 | Standard token/SSO authentication; no Basic Auth | A1 | arch, be | | Not started |
| C-02 | Token hygiene: strong secret or key, fixed signing algorithm, short lifetime, no sensitive data inside tokens | A4–A7 | be | | Not started |
| C-03 | If OAuth/OIDC is used: whitelisted redirect URIs, code flow only, state parameter, validated scopes | A8–A11 | arch, be | | Not started |
| C-04 | Local credentials (only if SSO does not cover them): strong salted adaptive hash, password policy, reset flow without account disclosure, lockout/jail on repeated failures, generic auth errors | W9, W22–W25, A3 | be | | Not started |
| C-05 | CAPTCHA on login and registration | W21 | fe, be | | Not started |
| C-06 | MFA for sensitive areas | W27 | arch | | Not started |
| C-07 | Session lifecycle: random IDs, regenerate on login/privilege change, idle and absolute timeouts, destroy on logout and on tampering, logout on every page | W29–W35 | be, fe | | Not started |
| C-08 | Cookie flags (HttpOnly, Secure), scoped domain/path, sensible expiry | W36–W38 | be, fe | | Not started |
| C-09 | No hard-coded credentials; DB and service credentials held centrally and locked down | W20, W26 | be, rev | | Not started |

> If login is delegated to the bank's SSO, C-04, C-05 and parts of C-06/C-07 may become `NA (delegated to bank IdP)`. The bank must accept this in writing.

### Access control
| ID | Control | Refs | Owner | Evidence | Status |
|---|---|---|---|---|---|
| C-10 | Every endpoint authenticated; one common access-check gate (complete mediation) | W52, A17 | be | | Not started |
| C-11 | Least privilege and deny by default; role-based access with periodic role review | W53, W56 | arch, be | | Not started |
| C-12 | No direct object references; checks use server-side identity; unvalidated redirects/forwards blocked | W54, W55 | be | | Not started |
| C-13 | App and middleware run with minimal OS/DB privileges | W28 | arch, bank | | Not started |
| C-14 | Non-guessable resource IDs (UUIDs, not auto-increment) | A18 | arch, be | | Not started |

### Input, output and business logic
| ID | Control | Refs | Owner | Evidence | Status |
|---|---|---|---|---|---|
| C-15 | Validate and sanitise all input; whitelist over blacklist; right HTTP method (405) and content type (406); validate input source | W40, W41, W47, A14–A16 | be | | Not started |
| C-16 | Parameterized queries only | W42 | be, rev | | Not started |
| C-17 | Contextual output encoding; fixed UTF-8 encoding | W39, W44 | fe, be | | Not started |
| C-18 | CSRF tokens where cookie sessions are used | W43 | be, fe | | Not started |
| C-19 | File uploads: validate size, type, content, and destination; nosniff on served uploads | W45, W46 | be | | Not started |
| C-20 | XML parsing without external entities | A19 | be | | Not started |
| C-21 | Business rules enforced server-side (limits, workflow cannot be bypassed) | W61 | be, rev | | Not started |
| C-22 | Transaction integrity: timestamped, user-attributed records, role-limited changes, tamper-evident (hash/signature) | W50 | arch, be | | Not started |

### Transport, headers and errors
| ID | Control | Refs | Owner | Evidence | Status |
|---|---|---|---|---|---|
| C-23 | HTTPS everywhere; HTTP disabled; HSTS | W6–W8, A13 | bank, arch | | Not started |
| C-24 | Strong TLS config; valid CA certificate matching the host | W12, W13 | bank | | Not started |
| C-25 | Security headers: nosniff, frame deny, CSP, no-cache for sensitive pages, autocomplete off on sensitive fields | W14, W48, W49, A21–A23 | be, fe | | Not started |
| C-26 | Remove fingerprinting headers; debug mode off in production | A20, A24 | be | | Not started |
| C-27 | Generic error messages; no stack traces or paths | W1, W25 | be | | Not started |
| C-28 | Request throttling against abuse | A12 | be, bank | | Not started |

### Data protection and keys
| ID | Control | Refs | Owner | Evidence | Status |
|---|---|---|---|---|---|
| C-29 | Encrypt sensitive data at rest and in transit; encryption on all sensitive API data | W18, A2 | arch, be | | Not started |
| C-30 | Key management: secure exchange, restricted storage, need-to-know access (on-prem key store, bank to confirm) | W10, W11 | arch, bank | | Not started |
| C-31 | Minimise sensitive data collected and stored; tokenise where possible | W15 | arch | | Not started |

### Logging and audit
| ID | Control | Refs | Owner | Evidence | Status |
|---|---|---|---|---|---|
| C-32 | Log all authentication events, privilege changes and admin actions | W2–W4, A26–A28 | be | | Not started |
| C-33 | Logs stored securely, tamper-resistant, retained per policy | W5, A29 | arch, bank | | Not started |

### Process, platform and bank-side
| ID | Control | Refs | Owner | Evidence | Status |
|---|---|---|---|---|---|
| C-34 | Security-focused code review on every PR | W16 | rev | | Not started |
| C-35 | Production servers hardened, VA-scanned, patched; compliant with the bank's secure-configuration document | W17, W57, W60, A25 | bank | | Not started |
| C-36 | Incident handling plan, tested, with a current contact list | W19 | hum, bank | | Not started |
| C-37 | Backup policy defined and implemented | W58 | hum, bank | | Not started |
| C-38 | WAF and DDoS applicability identified and enrolment validated | W59 | bank | | Not started |
| C-39 | PCI SSF/DSS applicability confirmed | W62 | hum, bank | | Not started |

## Clearance pack (Application Details form)
Items the bank also needs with the submission. Reviewer drafts from the repo; humans supply the rest.

| Item | Source | Owner |
|---|---|---|
| Data-flow diagram incl. network diagram; process flow and description | Architecture docs | rev, arch |
| Connections to bank servers (protocol, ports, API, websockets); DC and DR servers touched; security per connection | Contracts, deployment design | arch, bank |
| Data stored by the product and where; hardware needs; OS and versions | ADR-0001, deployment design | arch |
| Controls available: data wiping, user management, logs; user types and privileges | Design, matrix | rev, be |
| Functional-test and UAT sign-off | QA reports, UAT | qa-backend, qa-frontend, hum |
| Pre-implementation IS audit, VAPT report and closure status, SOC onboarding | Bank | bank |
| Maintenance model; previous clearance reference (if any); signatures (lead developer, CM, AGM/DGM) | Company, bank | hum, bank |

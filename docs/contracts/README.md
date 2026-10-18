# Contracts

Interface definitions that implementations must follow. Define a contract **before** parallel work starts. Insurer and bank source documents are not stored here; contracts are written in our own words with synthetic examples only.

| Contract | Purpose | Status |
|---|---|---|
| [`insurer-adapter`](insurer-adapter.md) | Common interface for all insurers: operations, outcome model, idempotency, normalisation | Proposed |
| [`usgic-gpa`](usgic-gpa.md) | First insurer (USGIC Group Personal Accident): operation and field mapping, inconsistencies to raise | Proposed |
| [`bank-auth`](bank-auth.md) | Staff sign-in through the bank's AD/CHRISS API behind an `AuthProvider` port; our session flow | Proposed |
| [`cbs-customer-lookup`](cbs-customer-lookup.md) | Read-only customer and account lookup from the CBS report server, replacing the Finacle menu | Proposed shape, blocked by access details (Q33) |
| [`cbs-posting`](cbs-posting.md) | Debit customer and credit pool account through the CBS transaction path; reconciliation reads | Proposed shape, blocked by the CBS transaction spec (Q27) |
| [`staff-api`](staff-api.md) ([OpenAPI](staff-api.openapi.yaml)) | Our own HTTP API for the staff web app (and later mobile): auth, CSRF, reference data, CBS lookup, sale flow actions, approvals, operations queue, dashboard. Replaces the `member-enrolment-api` placeholder | Proposed (2026-10-18) |
| `release-bundle` | Contents and signature format of a release bundle | To be written (owner: architect, with the release agent) |

Format for the HTTP API: an OpenAPI file plus a short README. The generated client types are shared with the React app (and a later React Native app).

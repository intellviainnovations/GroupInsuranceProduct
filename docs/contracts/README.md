# Contracts

Interface definitions that implementations must follow. Define a contract **before** parallel work starts. Insurer and bank source documents are not stored here; contracts are written in our own words with synthetic examples only.

| Contract | Purpose | Status |
|---|---|---|
| [`insurer-adapter`](insurer-adapter.md) | Common interface for all insurers: operations, outcome model, idempotency, normalisation | Proposed |
| [`usgic-gpa`](usgic-gpa.md) | First insurer (USGIC Group Personal Accident): operation and field mapping, inconsistencies to raise | Proposed |
| [`bank-auth`](bank-auth.md) | Staff sign-in through the bank's AD/CHRISS API behind an `AuthProvider` port; our session flow | Proposed |
| [`cbs-posting`](cbs-posting.md) | Debit customer and credit pool account through the CBS; reconciliation reads | Proposed shape, blocked by the CBS spec (Q27) |
| `member-enrolment-api` | Our own HTTP API for the web (and later mobile) client | To be written as an OpenAPI file by the first backend tasks, from `docs/specs/usgic-gpa-sale-flow.md` and `docs/design/data-model.md` |
| `release-bundle` | Contents and signature format of a release bundle | To be written (owner: architect, with the release agent) |

Format for the HTTP API: an OpenAPI file plus a short README. The generated client types are shared with the React app (and a later React Native app).

# Contracts

Interface definitions that implementations must follow. Define a contract **before** parallel work starts.

## To be written (owner: architect)
| Contract | Purpose | Blocked by |
|---|---|---|
| `insurer-adapter` | Common interface for the 8 insurer integrations (enrol, endorse, cancel, certificate, premium/MIS, status) and a normalised error model | Per-insurer API details (Q10), member model (Q3, Q4) |
| `member-enrolment-api` | Internal API for member and enrolment lifecycle | Data model |
| `bank-integration` | SSO, customer lookup, premium debit | Q9 |
| `release-bundle` | Contents and signature format of a release bundle | ADR-0001 |

Format: an OpenAPI/JSON Schema file plus a short README per contract. Use synthetic examples only.

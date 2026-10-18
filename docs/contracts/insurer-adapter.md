# Contract: insurer adapter

- **Status:** Proposed (architect draft, 2026-10-18). Derived from the first insurer's documented operations (USGIC, `docs/contracts/usgic-gpa.md`); to be generalised as further insurers are added (Q10).
- **Purpose:** the one interface through which the application talks to any insurer. Application services never see an insurer's field names, date formats, encryption or error text.
- **Location in code:** `src/backend/adapters/insurer/` with `base.py` (the port), one package per insurer, and `fake/` (used by tests and development).

## Operations
All operations take and return our own types (dates as real dates, money as `Decimal`, empty values as `None`). Every call receives a `correlation_id` and an `our_reference` and records an `insurer_call` row.

| Operation | Inputs | Result on success | Used for |
|---|---|---|---|
| `create_proposal` | enrolment snapshot, nominees, plan, `our_reference_no` | insurer proposal number, net/GST/gross premium (`Decimal`), insurer status text | Step 1 of a sale |
| `issue_policy` | proposal number, bank customer id, payment details (status, our CBS transaction id, transaction date) | certificate number, risk start and end dates | After the premium is posted |
| `fetch_certificate` | certificate number | PDF bytes and content type | Certificate of insurance (COI) |
| `get_proposal` | proposal number | current record: status, payment status, certificate number, dates, premium | Resolving an unknown outcome, reconciliation |
| `cancel_certificate` | certificate number | refund amount, refund date | Cancellation of an issued policy |
| `cancel_proposal` | proposal number | acknowledgement | Abandoned or failed sale |
| `endorse` | proposal or certificate number, changed fields, remarks | new proposal number, endorsed certificate number | After-sale change |
| `list_expired` | branch, optional filters | list of expired certificates with member and premium | Renewal work lists |

## Outcome model
Every operation returns exactly one of:

| Outcome | Meaning | Caller must |
|---|---|---|
| `Success(data)` | The insurer confirmed | Continue |
| `Rejected(category, message)` | The insurer understood and refused (for example validation or business rule) | Show the message, keep the state, never retry unchanged |
| `TransientError(category)` | Clear failure before the insurer acted (connection refused, 5xx known to be safe) | Retry with backoff through the job table |
| `UnknownOutcome` | The call may or may not have taken effect (timeout, dropped connection, unparsable reply) | **Read the remote state with `get_proposal` (or the equivalent) before any retry; if still unclear, set the enrolment to `NEEDS_ATTENTION`** |

Error categories (ours): `VALIDATION`, `AUTH`, `NOT_FOUND`, `BUSINESS_RULE`, `UNAVAILABLE`, `TIMEOUT`, `UNKNOWN`. Insurers may not send error codes (USGIC sends free text only), so each adapter owns a small, tested classifier from HTTP status and message text to our categories.

## Rules
1. **Idempotency:** the `our_reference` identifies one logical request. An adapter must not send a second create for the same reference without first checking whether the first took effect.
2. **No money logic:** premium and refund figures come from the insurer and are stored as received. The application compares them with `plan_rate` and flags a mismatch for a human; it never calculates premium (Q30).
3. **Normalisation:** insurer dates, genders, relations, occupations and branch codes are converted through `insurer_code_map` and parsers owned by the adapter. Empty strings become `None`.
4. **Secrets:** insurer credentials, tokens and encryption keys come from configuration only. Tokens are cached in memory until shortly before expiry and refreshed once on an authentication failure.
5. **Logging:** log operation, reference, outcome and duration. Never log personal data, tokens, keys or raw payloads. Raw payloads, if kept, go into `insurer_call` encrypted (Q31).
6. **Time limits:** every call has a connect and read timeout set in configuration; there is no unbounded wait.
7. **Contract tests:** each adapter must pass the same behaviour suite against its `fake/` and, in UAT, against the insurer's sandbox. The fake must be able to produce every outcome above on demand (success, rejection, transient error, unknown outcome, slow reply).

## Open points
- Which operations other insurers lack (for example a refund quote or a batch route), and how the interface degrades (Q10).
- A webhook or callback would add an inbound operation; USGIC has none in the document we hold.

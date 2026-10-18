# Spec: USGIC Group Personal Accident sale flow

- **Status:** Draft. The flow, states and failure handling below are ours and ready to build. **Insurance rules (eligibility, limits, waiting periods, nominee rules, refunds) are not specified here and must be supplied by a domain expert from the insurer's policy wording before they are marked Accepted.** Do not invent them.
- **Source:** product owner (D-022, D-031); contracts `docs/contracts/usgic-gpa.md`, `insurer-adapter.md`, `cbs-customer-lookup.md`, `cbs-posting.md`, `bank-auth.md`; data model `docs/design/data-model.md`.
- **Open questions:** Q3, Q26 to Q33 in the knowledge repo.

## Purpose
A bank employee sells a USGIC Group Personal Accident certificate to a bank customer. The application creates the proposal at the insurer, collects the premium through the CBS into the pool account, obtains the policy from the insurer, stores the certificate, and keeps a complete, auditable record.

## Actors
| Actor | Role in the flow |
|---|---|
| Maker (`BRANCH_USER`) | Enters the customer, insured, nominee and plan; starts the sale |
| Checker (`CHECKER`) | Approves or rejects before anything is sent, if maker-checker is on for the action (Q32). Must differ from the maker |
| Operations (`OPERATIONS`) | Resolves `NEEDS_ATTENTION` items, runs reconciliation |
| Customer | Gives consent to the debit (mechanism open, Q28) |
| Systems | USGIC API, bank CBS (report-server database for customer data; transaction path for debit and pool credit), bank authentication API |

## Happy path
1. **Lookup and draft.** Maker keys the customer's account number or CIF number; the application reads the customer and account details from the CBS report server (as the Finacle menu does today) and pre-fills them. The maker picks the debit account, completes what the CBS lacks, and enters nominee(s) and plan. Validation runs on the server (required fields, formats, nominee shares total 100). The configured plan rate is shown for information.
2. **Check.** If maker-checker is on, the sale goes to `PENDING_CHECK`; a different user approves or rejects with a comment.
3. **Proposal.** The application calls the insurer's `create_proposal` with our unique reference. The insurer returns a proposal number and net, GST and gross premium. The application compares them with the plan rate; a mismatch stops the sale for a human (`premium_matches_rate = false`, Q30).
4. **Consent.** The customer's consent to the debit of the gross premium is captured and recorded (method and reference; Q28).
5. **Payment.** The application posts one CBS transaction: debit the customer's account, credit the pool account, for the insurer's gross premium. It stores the CBS transaction id and time.
6. **Policy.** The application calls `issue_policy` with the proposal number and the posting details. The insurer returns the certificate number and the risk start and end dates.
7. **Certificate.** The application fetches the certificate PDF, stores it as received, and shows it to the maker. The enrolment is `ISSUED`.

## States
| State | Meaning |
|---|---|
| `DRAFT` | Being entered by the maker |
| `PENDING_CHECK` | Waiting for a checker |
| `REJECTED` | Checker refused; terminal, the maker may copy into a new draft |
| `APPROVED` | Cleared to go to the insurer (also the next state after `DRAFT` when no checker is needed) |
| `PROPOSAL_CREATED` | Insurer returned proposal number and premium |
| `PAYMENT_PENDING` | Consent captured; CBS posting in progress |
| `PAYMENT_FAILED` | CBS declined; no money moved; may retry |
| `PAID` | CBS posting succeeded; pool account credited |
| `ISSUED` | Certificate number and dates received |
| `PROPOSAL_REJECTED` | Insurer refused the proposal; the maker may correct and resubmit (back to `DRAFT`) |
| `PROPOSAL_CANCELLED` | Proposal withdrawn with the insurer before payment |
| `NEEDS_ATTENTION` | Unclear outcome, or paid but policy not issued after retries; operations resolve |
| `CANCELLATION_PENDING` | Cancellation of an issued certificate requested or in progress |
| `CANCELLED` | Certificate cancelled; refund posted if one is due |

### Allowed transitions
| From | To | Trigger |
|---|---|---|
| `DRAFT` | `PENDING_CHECK` | Maker submits (maker-checker on) |
| `DRAFT` | `APPROVED` | Maker submits (maker-checker off) |
| `PENDING_CHECK` | `APPROVED` / `REJECTED` | Checker decides (not the maker) |
| `APPROVED` | `PROPOSAL_CREATED` | Insurer confirms the proposal |
| `APPROVED` | `PROPOSAL_REJECTED` | Insurer refuses |
| `PROPOSAL_REJECTED` | `DRAFT` | Maker corrects |
| `PROPOSAL_CREATED` | `PAYMENT_PENDING` | Consent captured and posting started |
| `PROPOSAL_CREATED` | `PROPOSAL_CANCELLED` | Maker abandons, or a timeout job withdraws it |
| `PAYMENT_PENDING` | `PAID` | CBS success |
| `PAYMENT_PENDING` | `PAYMENT_FAILED` | CBS clear failure |
| `PAYMENT_PENDING` | `NEEDS_ATTENTION` | CBS outcome unknown and not resolvable |
| `PAYMENT_FAILED` | `PAYMENT_PENDING` | Retry with fresh consent if required |
| `PAYMENT_FAILED` | `PROPOSAL_CANCELLED` | Abandoned |
| `PAID` | `ISSUED` | Insurer issues the policy |
| `PAID` | `NEEDS_ATTENTION` | Policy not issued after the retry limit, or unknown outcome |
| `NEEDS_ATTENTION` | `PAID`, `ISSUED`, `PAYMENT_FAILED` | Operations confirm the true state with the insurer or the CBS |
| `ISSUED` | `CANCELLATION_PENDING` | Cancellation requested (and approved if required) |
| `CANCELLATION_PENDING` | `CANCELLED` | Insurer cancels; refund posted |
| `CANCELLATION_PENDING` | `NEEDS_ATTENTION` | Unclear outcome |
Every transition writes an `enrolment_status_history` row and an `audit_event`. Any other transition is rejected.

## Failure handling
| Failure | Required behaviour |
|---|---|
| Insurer timeout on proposal | Treat as unknown: call `get_proposal` using our reference before any retry |
| Customer debited, `issue_policy` fails | Keep `PAID`; retry through the job table; after the limit set `NEEDS_ATTENTION` and show it in the operations queue; money is **never** reversed automatically |
| CBS timeout | `UNKNOWN`; call `get_posting_status`; never post again until resolved |
| Insurer premium differs from the plan rate | Stop at `PROPOSAL_CREATED`; a human decides; no posting |
| Duplicate submit (double click, retry) | Idempotency key and unique references prevent a second proposal or posting |
| Token expired | One forced refresh then retry; otherwise a transient error |
| CBS report server unavailable or slow | Clear "CBS data not available, try again" message; no draft is created from partial data; no fallback to keying identity details unless the bank approves it (Q33) |
| Debit account changed state after lookup (closed, frozen) | Re-read the account just before posting; refuse the posting and tell the maker; the CBS transaction is the final authority |

## Acceptance criteria (testable)
1. A user with no role, or without the maker role, cannot create a draft; the attempt returns 403 and is audited.
2. The branch on every sale is the signed-in user's branch from the bank's reply; a different branch sent by the client is ignored.
3. A draft with nominee shares that do not total 100, or a missing required field, is rejected with field-level errors and no insurer call is made.
4. With maker-checker on, the maker cannot approve their own sale; a second user can.
5. Submitting the same approved sale twice creates one proposal at the insurer (one `our_reference_no`) and one `insurer_call` success.
6. If the insurer's premium differs from the plan rate, no CBS posting is created.
7. A CBS posting is created only when consent is recorded and the amount equals the insurer's gross premium.
8. When the CBS result is `UNKNOWN`, the application reads the posting status before any new posting; no second posting is created for the same reference.
9. When `issue_policy` fails after a successful posting, the enrolment stays `PAID`, a retry job exists, and after the retry limit it becomes `NEEDS_ATTENTION`.
10. On success the certificate number, risk dates and PDF are stored; the PDF stored matches the SHA-256 recorded.
11. Every status change has a history row and an audit event; audit rows cannot be updated or deleted by the application role.
12. No log line, audit detail or error response contains a password, token, key, account number or full personal record.
13. All insurer and CBS calls use configured timeouts; a slow fake produces `UnknownOutcome`, not a hang.
14. Reconciliation reports `POSTED_NO_POLICY` for a posting without an issued enrolment and `POLICY_NO_POSTING` for the reverse, on synthetic data.
15. The same flow runs end to end against the fake insurer, fake CBS (customer directory and posting) and fake bank authentication with no network access.
16. Looking up a known account number and a known CIF number each returns the customer with their accounts; an unknown number returns a clear not-found message and creates no draft.
17. The debit account must be one returned by the lookup for that customer; any other account number is refused.
18. Each lookup writes an audit event (who, when, outcome, identifier masked to its last four characters) and no log line contains the full customer record.
19. When the directory is unavailable the maker sees a retry message and nothing is saved.

## Rules we need from a domain expert (not to be invented)
Which CBS facts affect eligibility (account type and status, KYC status, customer status, joint accounts, customer age from date of birth) and what happens when they fail; eligibility (age band, occupation restrictions), plan definitions and sums insured, premium and GST per plan, policy term, waiting periods and exclusions, nominee and appointee rules (minors), disability declaration handling, cancellation and refund terms (full or pro-rata), renewal rules, grace periods.

## Open questions
Q3 (master policyholder), Q26 (insurer API details), Q27 (CBS transaction API), Q28 (consent), Q30 (plan rates), Q31 (retention), Q32 (roles and maker-checker), Q33 (CBS report-server read access).

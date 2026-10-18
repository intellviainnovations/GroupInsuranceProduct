# Contract: USGIC Group Personal Accident adapter

- **Status:** Proposed (architect draft, 2026-10-18). Written in our own words from the insurer's bank-integration API document, which is an insurer-internal file and is **not stored in this repo** (Q24). All values below are synthetic. No URLs, credentials, intermediary codes or real identifiers appear here; they live in configuration.
- **Implements:** `docs/contracts/insurer-adapter.md` for USGIC (Universal Sompo General Insurance), Group Personal Accident, plans A, B, C (D-022).
- **Location in code:** `src/backend/adapters/insurer/usgic/`.

## Transport and security
| Topic | What the insurer's document says | Our handling |
|---|---|---|
| Authentication | A token call first. The response carries two values: a token id (sent in a request header) and a JWT (sent in the `Authorization` header) for every later call. The JWT lifetime in the sample is about one hour | Cache both in memory; refresh shortly before expiry and once on an authentication failure. The token request needs a user name, product code, and intermediary identifiers from configuration |
| Payload protection | The JSON body is wrapped as `{"Value": "<json as a string>"}`, encrypted, and sent as `{"Data": "<ciphertext>"}`. The reply is `{"response": "<ciphertext>"}`, decrypted the same way | The algorithm, mode, key and IV handling are **not in the document we hold (Q26)**. Implement behind a small `PayloadCipher` interface, key from configuration, verified against the insurer's sample ciphertexts in UAT |
| Format | All calls are POST with JSON | `httpx` with timeouts from configuration |
| Environment | A UAT gateway is documented; the production address and network path are not (Q26) | Base URL from configuration |

## Operation mapping
| Our operation | USGIC method | Notes |
|---|---|---|
| (internal) token | `GenerateToken` | Not exposed to services |
| `create_proposal` | `InsertInsuredDetailsGPA` | Creates the proposal. The reply carries a policy-number-like value and a reference number; the reference number is the proposal number used by later calls. Confirm the difference (Q26) |
| `issue_policy` | `GeneratePolicy` | Sends proposal number, bank customer id, payment status, transaction number and date. Returns the certificate number and start and end dates |
| `fetch_certificate` | `FetchPolicy` with proposal type `COI` | Returns the PDF as base64 |
| `get_proposal` | `FetchPolicyDataGPA` | Full record by proposal number: premium, dates, status, payment status |
| `cancel_certificate` | `CertificateCancellationGPA` (by certificate id) | Returns refund amount and date |
| `cancel_proposal` | Documented under the same path as certificate cancellation, with a proposal number | Probably a document error; confirm the real path (Q26) |
| `endorse` | `EndorsePolicy` | Takes a proposal number plus insured, address, nominee and occupation fields and a remark; returns a new proposal number and an endorsed certificate number ending `/001`. What it changes is unclear (Q26) |
| `list_expired` | `GetExpiredPolicyData` | Filter by branch and optional customer, account, dates, plan. There is no documented renewal call (Q26) |

## Field mapping: `create_proposal`
| USGIC request field | Source in our model | Transformation |
|---|---|---|
| `IOBReference_No` | `enrolment.our_reference_no` | As is |
| `PolicyNo`, `ProductCode` | none | Sent empty in the sample; product code is carried by the token request. Confirm (Q26) |
| `BranchCode` | `enrolment.branch_code` | **Mapped through `insurer_code_map` (category `BRANCH`)**: the sample uses six-digit codes while the bank's own codes are shorter |
| `BankCustomerId` | `customer.bank_customer_id` | As is |
| `FirstName`, `MiddleName`, `LastName` | `insured_*_name` | Upper case as the insurer returns it |
| `Gender` | `insured_gender_code` | Through `insurer_code_map` (`Male`/`MALE` differ between calls) |
| `DateOfBirth` | `insured_dob` | `dd/MM/yyyy` |
| `Email`, `Mobile` | `insured_email`, `insured_mobile` | Digits only for the mobile |
| `Address1`, `Address2`, `City`, `State`, `PinCode` | `insured_address1`, `insured_address2`, `insured_city`, `insured_state_code`, `insured_pincode` | State through `insurer_code_map` |
| `Occupation`, `OtherOccupation` | `insured_occupation_code`, `insured_other_occupation` | Occupation through `insurer_code_map` |
| `AnyDisability`, `DisabilityDescription`, `NameAndAddressOfGuardian` | `any_disability`, `disability_description`, `guardian_name_address` | `Y`/`N` for the flag (confirm) |
| `Plan` | `insurer_plan.plan_code` | `A`, `B` or `C` |
| `AccountNo` | `customer_account` (decrypted only for this call) | As is |
| `NomineeDetails[]` | `enrolment_nominee` rows | See below |

Nominee fields: `NomineeName`, `NomineeDOB` (`dd/MM/yyyy`), `NomineeAge`, `Nominee_Relation` (through `insurer_code_map`), mobile, email, gender, present and permanent address, bank account fields, `NomineePerPayAmt` (the percentage share), and appointee name, relation, date of birth, age, gender.

Reply fields we keep: proposal number, product code, branch code, status, error description, net premium, GST amount, gross premium (all strings; convert to `Decimal`).

## Field mapping: `issue_policy`
| USGIC request field | Source |
|---|---|
| `ProposalNumber` | `enrolment.insurer_proposal_no` |
| `BankCustomerId` | `customer.bank_customer_id` |
| `Payment_Status` | `SUCCESS` only after our `cbs_posting.status = SUCCESS` |
| `TransactionNumber` | `cbs_posting.cbs_tran_id` |
| `TransactionDate` | `cbs_posting.cbs_tran_at`, `dd/MM/yyyy` |
| `TokenId` | Sent in the body as null in the sample; the token id travels in the header. Confirm (Q26) |

Reply fields we keep: certificate number (`Policy_No`), `Policy_Start_Date`, `Policy_End_Date`, status, error description.

## Dates and numbers
- Request dates are `dd/MM/yyyy`. The samples are consistent with day first (a policy starting `08/01/2026` ends `07/01/2027`). **Assumption**, confirm in UAT.
- Reply dates appear in four shapes (ISO with time, `dd-MM-yyyy hh:mm:ss`, `dd/MM/yyyy`, and `yyyy-MM-ddTHH:mm:ss`). The parser accepts all and rejects anything else.
- Premiums arrive as strings; some replies use numbers. Parse to `Decimal`, never float.
- Treat the literal string `"null"` as no value.

## Status mapping (to enrolment states, see the sale-flow spec)
| Insurer result | Adapter outcome |
|---|---|
| `Status = SUCCESS` | `Success` |
| Any other `Status` with an error description | `Rejected` (classified from the text) |
| HTTP 401/403 or token error | `TransientError(AUTH)` after one forced token refresh, then `Rejected(AUTH)` |
| Connect refused, DNS failure | `TransientError(UNAVAILABLE)` |
| Read timeout, connection reset after send, undecryptable or unparsable reply | `UnknownOutcome` |

## Inconsistencies in the source document (to raise with the insurer, Q26)
- Field names differ between calls (`IOBReference_No` and `IOB_Reference_No`; `GSTAmount` and `ServiceTax`; `PolicyNo` and `Policy_No` and `Certificate_Id`).
- Gender is `Male` in some calls and `MALE` in others.
- The proposal-cancel and certificate-cancel calls share one path; messages in some samples quote a different number from the request.
- One sample shows a 30-day policy period, the others one year.
- Encrypted and plain samples of the same request differ in the nominee share field.
- The endorsement request treats the insured as a "friend" relation and carries a single nominee; its meaning is unclear.
- No claims, batch, callback or refund-quote operations are documented.

## Fake adapter (for development and tests)
`fake/` implements the same port in memory and can be scripted per reference to return: success with premium for plans A, B, C; a validation rejection; an authentication failure once then success; a transient error; an unknown outcome after the insurer "accepted" the request (the follow-up `get_proposal` then shows the true state); a slow reply. Test data is synthetic only.

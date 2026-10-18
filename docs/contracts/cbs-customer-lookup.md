# Contract: CBS customer and account lookup (read-only)

- **Status:** Proposed shape only. Access details to the bank's CBS report server have not been received (Q33); this contract fixes what the application needs so the bank's answers can be checked against it.
- **Decision behind it (D-031):** the sale process moves out of the CBS's own menus into our application. Today a branch user opens a Finacle menu, keys an account or CIF number, and the screen fetches the customer. Our application does the same: staff key an account or CIF number and we **read** the customer and account details from the CBS report-server database. Staff do not key customer details that the CBS already holds.
- **Transactions are separate:** the debit and pool credit use the CBS transaction path (`cbs-posting.md`). This contract never writes to the CBS.
- **Location in code:** `src/backend/adapters/cbs/customer_directory/` with `base.py` (the port) and `fake/`. The real adapter is written when Q33 is answered; the first real implementation is expected to be a read-only SQL connection (Finacle commonly runs on Oracle; confirm, Q33), behind this port so an API or another database can replace it.

## Port
| Operation | Inputs | Result | Used for |
|---|---|---|---|
| `find_customer` | an account number **or** a CIF number | `CustomerRecord` and the customer's `AccountRecord` list, or `NotFound` | The first step of a sale |
| `get_account` | account number | `AccountRecord`, or `NotFound` | Confirm the chosen debit account still exists and is eligible before posting |
| `get_branch` | bank branch code | branch name, region, IFSC, or `NotFound` | Fill the `branch` table |

### `CustomerRecord` (our types; only fields the CBS actually holds are filled)
CIF number, first/middle/last name (or one full-name field to be split by a documented rule), gender, date of birth, mobile, email, address lines, city, state, PIN code, occupation (if held), KYC status, customer status (for example active, deceased, frozen), home branch.

### `AccountRecord`
Account number, account type and scheme, status (active, dormant, closed, frozen), branch, operating mode and joint-holder indication, currency, holder name(s). Balance is **not** read; the CBS decides at posting time.

All fields beyond the first list are unknown until Q33 is answered; unknown fields stay `None` and the sale form lets the maker key them where the rules allow.

## Rules
1. **Read-only.** The database account used has select rights on a short allow-list of views or tables, nothing else. No write, DDL or procedure rights. The application contains no statement that changes CBS data.
2. **Parameterised queries only**; the account and CIF numbers are bound parameters, never concatenated (matrix C-16). Explicit column lists, never `SELECT *`.
3. **One customer per lookup:** a hard row limit and a statement timeout, so a bad query cannot scan or lock the report server. No wildcard or name search in Phase 1.
4. **Credentials and network:** host, service name, user and password come from configuration or the bank's secret store, never the repo. Access only from the bank-approved network path (Q33). Connection pool kept small.
5. **Data minimisation:** read only what the sale needs; the application stores a snapshot on the sale (`customer`, `customer_account`, `enrolment`), not a copy of the CBS.
6. **Freshness:** the report server may lag the live CBS. The record is for filling the form; the CBS transaction remains the authority (a closed or frozen account fails at posting). Show the `cbs_fetched_at` time to the maker.
7. **Audit:** every lookup writes an `audit_event` (who, when, outcome, masked identifier showing only the last four characters). Never log the full record.
8. **Failure behaviour:** timeouts and connection errors give a clear "CBS data not available, try again" message. There is no fallback to keying identity details by hand unless the bank approves it (Q33).
9. **Eligibility checks that use CBS data** (account status, KYC status, customer status, customer age from date of birth, joint accounts) are insurance and bank rules: they are listed in the sale-flow spec as needed from a human, not invented (Q33).
10. **Tests:** the fake returns synthetic customers for fixed account and CIF numbers, a customer with several accounts, an inactive account, a missing field, a slow reply and an unavailable server. Real queries are tested only in the bank's UAT.

## Matrix rows
C-09 (no hard-coded credentials), C-13 (least privilege), C-16 (parameterised queries), C-27 (generic errors), C-31 (data minimisation), C-32 (logging of access).

## Open points (Q33)
Which database, version and host (the report server); how we connect (direct database account, a view layer, or an API); names of the views or tables and their columns; which fields exist (occupation, KYC, nominee, e-mail, joint holders); replication delay; test data; the read-only account and who issues it; network path and approvals; the bank's infosec position on a direct database connection; whether the maker may correct CBS-sourced fields.
